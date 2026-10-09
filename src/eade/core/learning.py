"""Learning without a neural network.

EADE learns only from expert-validated examples, and learning never touches the
active version: it builds a new DRAFT that must then be simulated, evaluated on
the held-out test set and explicitly published.

Three mechanisms:
  * signatures   average portrait of each class, positives and negatives;
  * recalibrate  each rule's weight follows its measured precision, and a rule
                 that is wrong more often than right is switched off;
  * thresholds   simple one-feature rules that isolate false positives,
                 proposed for expert review.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .features import NUMBER, FeatureCatalog, FeatureVector
from .knowledge import KnowledgeVersion, merge_rules
from .rules import Effect, Rule, evaluate
from .signatures import NEGATIVE, POSITIVE, Signature, SimilarityParams, build_signature

TRAIN = "TRAIN"
TEST = "TEST"


def split_for(group_key: str, folds: int = 5) -> str:
    """Deterministic train/test assignment of a spatial or logical group.

    Whole groups (for instance a 200 m grid cell) go to the same side so that
    neighbouring, near-identical objects never sit on both sides of the split.
    One group in `folds` is held out for testing.
    """
    digest = hashlib.sha256(group_key.encode("utf-8")).digest()
    return TEST if digest[0] % folds == 0 else TRAIN


@dataclass(frozen=True)
class Example:
    """A validated case: the expert's verdict on a candidate, with its measures."""

    id: str
    target_class: str
    polarity: str               # POSITIVE: a true object of the class; NEGATIVE: it is not
    features: FeatureVector
    classic_accepted: bool | None = None
    split: str = TRAIN
    profile: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LearningOptions:
    signatures: bool = True
    recalibrate: bool = True
    thresholds: bool = True
    min_support_reweight: int = 5
    min_support_disable: int = 10
    min_examples_per_side: int = 10
    min_threshold_precision: float = 0.85
    max_learned_rules_per_class: int = 3


@dataclass
class LearningReport:
    train_examples: int = 0
    signatures: list[dict[str, Any]] = field(default_factory=list)
    reweighted: list[dict[str, Any]] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    learned_rules: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- signatures

def build_signatures(examples: Iterable[Example], catalog: FeatureCatalog,
                     params: SimilarityParams = SimilarityParams()) -> tuple[Signature, ...]:
    groups: dict[tuple[str, str, str | None], list[Mapping[str, float]]] = {}
    for ex in examples:
        vec = catalog.normalize(ex.features)
        groups.setdefault((ex.target_class, ex.polarity, None), []).append(vec)
        if ex.profile is not None:
            groups.setdefault((ex.target_class, ex.polarity, ex.profile), []).append(vec)
    out = []
    for (cls, pol, prof), vectors in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "")):
        sig = build_signature(cls, pol, vectors, params, prof)
        if sig is not None:
            out.append(sig)
    return tuple(out)


# ---------------------------------------------------------------- rule stats

def _relevant(rule: Rule, examples: Sequence[Example]) -> list[Example]:
    return [e for e in examples
            if e.target_class == rule.target_class and (rule.profile is None or e.profile == rule.profile)]


def rule_precision(rule: Rule, examples: Sequence[Example]) -> dict[str, Any]:
    """How often a rule was right when it fired, on validated examples.

    CONFIRM is right on positives; REJECT and RECLASSIFY on negatives; ABSTAIN
    is right when it fires on a candidate the classic engine wrongly accepted.
    """
    support = correct = 0
    for ex in _relevant(rule, examples):
        if rule.effect is Effect.ABSTAIN and ex.classic_accepted is not True:
            continue
        if evaluate(rule.condition, ex.features) is not True:
            continue
        support += 1
        if rule.effect is Effect.CONFIRM:
            correct += ex.polarity == POSITIVE
        else:
            correct += ex.polarity == NEGATIVE
    precision = correct / support if support else None
    return {"support": support, "correct": correct, "precision": precision}


def recalibrate(rules: Sequence[Rule], examples: Sequence[Example], options: LearningOptions = LearningOptions(),
                report: LearningReport | None = None) -> tuple[Rule, ...]:
    out = []
    for rule in rules:
        stats = rule_precision(rule, examples)
        p, n = stats["precision"], stats["support"]
        new = rule.with_(stats=stats)
        if p is not None and n >= options.min_support_disable and p < 0.5 and rule.active:
            new = new.with_(active=False)
            if report is not None:
                report.disabled.append(rule.code)
        elif (p is not None and n >= options.min_support_reweight
              and rule.effect in (Effect.CONFIRM, Effect.REJECT)):
            weight = round(min(1.0, max(0.05, 2.0 * (p - 0.5))), 4)
            if weight != rule.weight:
                new = new.with_(weight=weight)
                if report is not None:
                    report.reweighted.append({"code": rule.code, "from": rule.weight, "to": weight, "precision": p})
        out.append(new)
    return tuple(out)


# ---------------------------------------------------------- learned thresholds

def _deciles(values: list[float]) -> list[float]:
    s = sorted(values)
    cuts = {s[min(len(s) - 1, int(len(s) * q / 10))] for q in range(1, 10)}
    return sorted(cuts)


def propose_thresholds(examples: Sequence[Example], catalog: FeatureCatalog,
                       options: LearningOptions = LearningOptions(),
                       report: LearningReport | None = None) -> tuple[Rule, ...]:
    """One-feature REJECT rules that isolate negatives with high precision."""
    proposals: list[Rule] = []
    for cls in sorted({e.target_class for e in examples}):
        pos = [e for e in examples if e.target_class == cls and e.polarity == POSITIVE]
        neg = [e for e in examples if e.target_class == cls and e.polarity == NEGATIVE]
        if len(pos) < options.min_examples_per_side or len(neg) < options.min_examples_per_side:
            if report is not None:
                report.skipped.append(f"{cls}: {len(pos)} positives / {len(neg)} negatives, "
                                      f"{options.min_examples_per_side} of each needed")
            continue
        min_hits = max(5, int(0.1 * len(neg) + 0.999))
        best_per_feature = []
        for d in catalog:
            if d.dtype != NUMBER or not d.learnable:
                continue
            pv = [v for v in (catalog.numeric_value(d.key, e.features.get(d.key)) for e in pos) if v is not None]
            nv = [v for v in (catalog.numeric_value(d.key, e.features.get(d.key)) for e in neg) if v is not None]
            if len(pv) < options.min_examples_per_side or len(nv) < options.min_examples_per_side:
                continue
            best = None
            for cut in _deciles(pv + nv):
                for op in ("<", ">="):
                    hit_n = sum(1 for v in nv if (v < cut if op == "<" else v >= cut))
                    hit_p = sum(1 for v in pv if (v < cut if op == "<" else v >= cut))
                    if hit_n < min_hits:
                        continue
                    precision = hit_n / (hit_n + hit_p)
                    if precision < options.min_threshold_precision:
                        continue
                    key = (hit_n, precision)
                    if best is None or key > best[0]:
                        best = (key, op, cut, hit_n, hit_p, precision)
            if best is not None:
                best_per_feature.append((d.key, *best))
        best_per_feature.sort(key=lambda b: b[1], reverse=True)
        for feat, _, op, cut, hit_n, hit_p, precision in best_per_feature[: options.max_learned_rules_per_class]:
            code = f"LEARNED_{cls}_{feat}_{'LT' if op == '<' else 'GE'}"
            label = catalog[feat].label or feat
            proposals.append(Rule(
                code=code,
                label=f"{label} {op} {cut:g}",
                target_class=cls,
                effect=Effect.REJECT,
                condition={"feature": feat, "op": op, "value": round(cut, 6)},
                weight=round(min(1.0, max(0.05, 2.0 * (precision - 0.5))), 4),
                priority=500,
                origin="LEARNED",
                rationale=(f"Isolates {hit_n} of {len(neg)} validated negatives "
                           f"for {hit_p} of {len(pos)} positives (precision {precision:.2f}). Review before use."),
                stats={"support": hit_n + hit_p, "correct": hit_n, "precision": precision},
            ))
            if report is not None:
                report.learned_rules.append(code)
    return tuple(proposals)


# ---------------------------------------------------------- candidate version

def build_candidate(base: KnowledgeVersion, examples: Iterable[Example], catalog: FeatureCatalog,
                    number: int, options: LearningOptions = LearningOptions(),
                    label: str = "") -> tuple[KnowledgeVersion, LearningReport]:
    """A new DRAFT learned from the TRAIN examples only. `base` is never modified."""
    train = [e for e in examples if e.split == TRAIN]
    report = LearningReport(train_examples=len(train))
    draft = base.new_draft(number, label or f"Candidate learned from v{base.number}",
                           f"Built from {len(train)} training examples.")

    signatures = draft.signatures
    if options.signatures:
        signatures = build_signatures(train, catalog, base.config.similarity)
        report.signatures = [{"class": s.target_class, "polarity": s.polarity, "profile": s.profile,
                              "count": s.count} for s in signatures]

    rules = tuple(r for r in draft.rules if r.origin != "LEARNED")
    if options.recalibrate:
        rules = recalibrate(rules, train, options, report)
    if options.thresholds:
        rules = merge_rules(rules, propose_thresholds(train, catalog, options, report))

    return draft.evolve(signatures=signatures, rules=rules), report
