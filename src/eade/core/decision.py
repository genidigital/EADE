"""The decision engine.

EADE never draws a contour. It judges candidates produced by a detection
provider (the "classic" engine): it measures them, applies the rules of the
active knowledge version, compares them with validated cases and returns a
decision with its full explanation.

    score = sum(weight_i * component_i) / sum(weight_i)   over available components

    ACCEPTED  score >= accept threshold
    REVIEW    in between: a human decides
    REJECTED  score <= reject threshold

Guardrails applied after scoring, in this order:
  1. a blocking REJECT rule that fires forces REJECTED;
  2. an ABSTAIN rule that fires turns ACCEPTED into REVIEW;
  3. a candidate the classic engine rejected can reach REVIEW at most.
The score is a decision strength, not a probability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Iterator, Mapping

from .features import FeatureCatalog, FeatureVector
from .knowledge import KnowledgeVersion
from .rules import Effect, evaluate
from .signatures import NEGATIVE, POSITIVE, similarity


class Decision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Candidate:
    """An object proposed by a detection provider.

    `classic_accepted` is the provider's own verdict (None when it has none).
    `context` drives profile selection (region, resolution, sensor...).
    `geometry` and `meta` are carried through untouched for the host application.
    """

    id: str
    target_class: str
    features: FeatureVector
    classic_accepted: bool | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    geometry: Any = None
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleTrace:
    code: str
    effect: str
    outcome: str  # FIRED, NOT_FIRED, UNKNOWN
    weight: float
    blocking: bool
    reads: Mapping[str, Any]


@dataclass(frozen=True)
class Result:
    candidate: Candidate
    decision: Decision
    score: float | None
    final_class: str
    components: Mapping[str, Mapping[str, float]]
    rules: tuple[RuleTrace, ...]
    guardrails: tuple[str, ...]
    profile: str | None
    version: int
    fingerprint: str
    similarity_detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def fired(self) -> list[RuleTrace]:
        return [r for r in self.rules if r.outcome == "FIRED"]

    @property
    def unknown(self) -> list[RuleTrace]:
        return [r for r in self.rules if r.outcome == "UNKNOWN"]

    def explanation(self) -> dict[str, Any]:
        """A JSON-ready account of the decision, to store next to the prediction."""
        return {
            "candidate": self.candidate.id,
            "decision": self.decision.value,
            "score": None if self.score is None else round(self.score, 4),
            "class": {"initial": self.candidate.target_class, "final": self.final_class},
            "classic_accepted": self.candidate.classic_accepted,
            "components": {k: dict(v) for k, v in self.components.items()},
            "rules_fired": [{"code": r.code, "effect": r.effect, "weight": r.weight,
                             "blocking": r.blocking, "reads": dict(r.reads)} for r in self.fired],
            "rules_unknown": [{"code": r.code, "missing": [k for k, v in r.reads.items() if v is None]}
                              for r in self.unknown],
            "guardrails": list(self.guardrails),
            "similarity": dict(self.similarity_detail),
            "profile": self.profile,
            "knowledge": {"version": self.version, "fingerprint": self.fingerprint},
        }


class Engine:
    """Applies one knowledge version. Cheap to build; safe to share across threads."""

    def __init__(self, version: KnowledgeVersion, catalog: FeatureCatalog):
        self.version = version
        self.catalog = catalog
        self._fingerprint = version.fingerprint()
        problems = [p for r in version.rules for p in r.check(catalog)]
        if problems:
            raise ValueError("invalid rules in version %d:\n  %s" % (version.number, "\n  ".join(problems)))

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def decide(self, candidate: Candidate) -> Result:
        v, cfg = self.version, self.version.config
        profile = v.profile_for(candidate.context)
        pcode = profile.code if profile else None

        rules = v.rules_for(candidate.target_class, pcode)
        traces: list[RuleTrace] = []
        for rule in rules:
            reads: dict[str, Any] = {}
            truth = evaluate(rule.condition, candidate.features, reads)
            outcome = "FIRED" if truth is True else "UNKNOWN" if truth is None else "NOT_FIRED"
            traces.append(RuleTrace(rule.code, rule.effect.value, outcome, rule.weight, rule.blocking, reads))
        fired = [(t, r) for t, r in zip(traces, rules) if t.outcome == "FIRED"]

        components: dict[str, dict[str, float]] = {}

        def add(name: str, value: float, weight: float) -> None:
            if weight > 0:
                components[name] = {"value": round(value, 6), "weight": weight}

        if candidate.classic_accepted is not None:
            add("classic", 1.0 if candidate.classic_accepted else 0.0, cfg.classic_weight)

        weighted = [r for _, r in fired if r.effect in (Effect.CONFIRM, Effect.REJECT)]
        if weighted:
            net = sum(r.weight if r.effect is Effect.CONFIRM else -r.weight for r in weighted)
            add("rules", _clamp(0.5 + net / 2.0), cfg.rules_weight)

        normalized = self.catalog.normalize(candidate.features)
        sim, sim_detail = similarity(
            normalized,
            v.signature(candidate.target_class, POSITIVE, pcode),
            v.signature(candidate.target_class, NEGATIVE, pcode),
            cfg.similarity,
        )
        if sim is not None:
            add("similarity", sim, cfg.similarity_weight)

        for ramp in cfg.ramps:
            if ramp.classes and candidate.target_class not in ramp.classes:
                continue
            raw = self.catalog.numeric_value(ramp.feature, candidate.features.get(ramp.feature))
            if raw is not None:
                add(ramp.name, ramp.value(raw), ramp.weight)

        total_w = sum(c["weight"] for c in components.values())
        score = sum(c["value"] * c["weight"] for c in components.values()) / total_w if total_w else None

        if score is None:
            decision = Decision.REVIEW
        elif score >= cfg.accept_threshold:
            decision = Decision.ACCEPTED
        elif score <= cfg.reject_threshold:
            decision = Decision.REJECTED
        else:
            decision = Decision.REVIEW

        guardrails: list[str] = []
        if score is None:
            guardrails.append("NO_EVIDENCE")
        blocking = [r for _, r in fired if r.effect is Effect.REJECT and r.blocking]
        if blocking:
            decision = Decision.REJECTED
            guardrails.append(f"BLOCKING_RULE:{blocking[0].code}")
        if decision is Decision.ACCEPTED:
            abstain = [r for _, r in fired if r.effect is Effect.ABSTAIN]
            if abstain:
                decision = Decision.REVIEW
                guardrails.append(f"ABSTAIN_RULE:{abstain[0].code}")
        if decision is Decision.ACCEPTED and candidate.classic_accepted is False:
            decision = Decision.REVIEW
            guardrails.append("CLASSIC_REJECTED_CAPPED_AT_REVIEW")

        final_class = candidate.target_class
        reclass = [r for _, r in fired if r.effect is Effect.RECLASSIFY]
        if reclass:
            final_class = reclass[0].result_class or final_class
            guardrails.append(f"RECLASSIFIED:{reclass[0].code}")

        return Result(candidate, decision, score, final_class, components, tuple(traces),
                      tuple(guardrails), pcode, v.number, self._fingerprint, sim_detail)

    def decide_all(self, candidates: Iterable[Candidate]) -> Iterator[Result]:
        for c in candidates:
            yield self.decide(c)


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))
