"""Evaluation of a knowledge version against validated reference objects.

Geometry stays opaque to the core: the caller provides `overlap(a, b)` (the
IoU of two objects, 1 = identical, 0 = disjoint) and `measure(a)` (area, or
length for linear objects). The geo adapter supplies both.

Matching is one-to-one and greedy by decreasing overlap, per class. A retained
prediction is a true positive when it overlaps a reference by at least
`match_iou`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from .decision import Decision, Result

Overlap = Callable[[Any, Any], float]
Measure = Callable[[Any], float]


@dataclass(frozen=True)
class Reference:
    id: str
    target_class: str
    geometry: Any


@dataclass
class ClassMetrics:
    target_class: str
    references: int = 0
    true_positives: int = 0
    false_positives: int = 0
    misses: int = 0
    review: int = 0
    iou_sum: float = 0.0
    measure_error: float = 0.0
    measure_reference: float = 0.0

    @property
    def mean_iou(self) -> float:
        n = self.true_positives + self.false_positives + self.misses
        return self.iou_sum / n if n else 0.0

    @property
    def precision(self) -> float | None:
        n = self.true_positives + self.false_positives
        return self.true_positives / n if n else None

    @property
    def recall(self) -> float | None:
        n = self.true_positives + self.misses
        return self.true_positives / n if n else None

    @property
    def relative_measure_error(self) -> float | None:
        return self.measure_error / self.measure_reference if self.measure_reference else None

    def to_dict(self) -> dict[str, Any]:
        r = lambda x: None if x is None else round(x, 4)  # noqa: E731
        return {
            "class": self.target_class,
            "references": self.references,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "misses": self.misses,
            "review": self.review,
            "mean_iou": r(self.mean_iou),
            "precision": r(self.precision),
            "recall": r(self.recall),
            "relative_measure_error": r(self.relative_measure_error),
        }


@dataclass
class Metrics:
    by_class: dict[str, ClassMetrics] = field(default_factory=dict)

    def _sum(self, attr: str) -> float:
        return sum(getattr(m, attr) for m in self.by_class.values())

    @property
    def references(self) -> int:
        return int(self._sum("references"))

    @property
    def false_positives(self) -> int:
        return int(self._sum("false_positives"))

    @property
    def mean_iou(self) -> float:
        n = self._sum("true_positives") + self._sum("false_positives") + self._sum("misses")
        return self._sum("iou_sum") / n if n else 0.0

    @property
    def relative_measure_error(self) -> float | None:
        ref = self._sum("measure_reference")
        return self._sum("measure_error") / ref if ref else None

    def to_dict(self) -> dict[str, Any]:
        rme = self.relative_measure_error
        return {
            "references": self.references,
            "mean_iou": round(self.mean_iou, 4),
            "false_positives": self.false_positives,
            "relative_measure_error": None if rme is None else round(rme, 4),
            "by_class": {k: m.to_dict() for k, m in sorted(self.by_class.items())},
        }


def evaluate(results: Iterable[Result], references: Iterable[Reference], overlap: Overlap,
             measure: Measure, match_iou: float = 0.5) -> Metrics:
    results = list(results)
    refs = list(references)
    metrics = Metrics()
    classes = {r.target_class for r in refs} | {r.final_class for r in results if r.decision is Decision.ACCEPTED}
    for cls in sorted(classes):
        m = ClassMetrics(cls)
        cls_refs = [r for r in refs if r.target_class == cls]
        kept = [r for r in results if r.decision is Decision.ACCEPTED and r.final_class == cls]
        m.review = sum(1 for r in results if r.decision is Decision.REVIEW and r.final_class == cls)
        m.references = len(cls_refs)

        pairs = []
        for i, p in enumerate(kept):
            for j, ref in enumerate(cls_refs):
                o = overlap(p.candidate.geometry, ref.geometry)
                if o >= match_iou:
                    pairs.append((o, i, j))
        pairs.sort(reverse=True)
        used_p: set[int] = set()
        used_r: set[int] = set()
        for o, i, j in pairs:
            if i in used_p or j in used_r:
                continue
            used_p.add(i)
            used_r.add(j)
            m.true_positives += 1
            m.iou_sum += o
            m.measure_error += abs(measure(kept[i].candidate.geometry) - measure(cls_refs[j].geometry))
        for i, p in enumerate(kept):
            if i not in used_p:
                m.false_positives += 1
                m.measure_error += measure(p.candidate.geometry)
        for j, ref in enumerate(cls_refs):
            if j not in used_r:
                m.misses += 1
                m.measure_error += measure(ref.geometry)
        m.measure_reference = sum(measure(r.geometry) for r in cls_refs)
        metrics.by_class[cls] = m
    return metrics


# ---------------------------------------------------------------- publication

@dataclass(frozen=True)
class PublicationCriteria:
    min_iou_gain: float = 0.02
    min_test_units: int = 20

    def to_dict(self) -> dict[str, Any]:
        return {"min_iou_gain": self.min_iou_gain, "min_test_units": self.min_test_units}


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    checks: tuple[Mapping[str, Any], ...]
    candidate: Mapping[str, Any]
    baseline: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "checks": [dict(c) for c in self.checks],
                "candidate": dict(self.candidate), "baseline": dict(self.baseline)}


def judge(candidate: Metrics, baseline: Metrics, criteria: PublicationCriteria = PublicationCriteria()) -> Verdict:
    """May the candidate replace the baseline? Every check must pass."""
    gain = candidate.mean_iou - baseline.mean_iou
    c_err, b_err = candidate.relative_measure_error, baseline.relative_measure_error
    checks: list[dict[str, Any]] = [
        {"check": "test_units", "ok": candidate.references >= criteria.min_test_units,
         "value": candidate.references, "required": criteria.min_test_units},
        {"check": "iou_gain", "ok": gain >= criteria.min_iou_gain - 1e-12,
         "value": round(gain, 4), "required": criteria.min_iou_gain},
        {"check": "measure_error_not_worse",
         "ok": c_err is None or b_err is None or c_err <= b_err + 1e-12,
         "value": c_err, "baseline": b_err},
        {"check": "false_positives_not_more", "ok": candidate.false_positives <= baseline.false_positives,
         "value": candidate.false_positives, "baseline": baseline.false_positives},
    ]
    return Verdict(all(c["ok"] for c in checks), tuple(checks), candidate.to_dict(), baseline.to_dict())


def compare_decisions(before: Sequence[Result], after: Sequence[Result]) -> dict[str, Any]:
    """Simulation summary: how decisions move from one version to another."""
    by_id = {r.candidate.id: r for r in before}
    transitions: dict[str, int] = {}
    changed = []
    rule_hits: dict[str, int] = {}
    for a in after:
        for t in a.fired:
            rule_hits[t.code] = rule_hits.get(t.code, 0) + 1
        b = by_id.get(a.candidate.id)
        if b is None:
            continue
        key = f"{b.decision.value}->{a.decision.value}"
        transitions[key] = transitions.get(key, 0) + 1
        if b.decision != a.decision or b.final_class != a.final_class:
            changed.append({"id": a.candidate.id, "before": b.decision.value, "after": a.decision.value,
                            "class_before": b.final_class, "class_after": a.final_class,
                            "rules": [t.code for t in a.fired]})
    return {"compared": len(after), "changed": len(changed), "transitions": dict(sorted(transitions.items())),
            "rule_hits": dict(sorted(rule_hits.items(), key=lambda kv: -kv[1])), "changes": changed}
