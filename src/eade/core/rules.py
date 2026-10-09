"""Rule language.

Rules are data, never code: a condition is a small JSON tree that can be stored,
validated against the feature dictionary, shown to an expert in plain words and
evaluated safely.

Condition grammar (native keys; the legacy French keys are accepted on input):

    {"all": [c, ...]}                                   et
    {"any": [c, ...]}                                   ou
    {"not": c}                                          non
    {"feature": "k", "op": "<", "value": 3}             car / op / valeur
    {"feature": "k", "between": [a, b]}                 entre (inclusive)
    {"feature": "k", "in": [v1, v2]}                    dans

Evaluation is three-valued (Kleene logic). A comparison on a missing feature is
UNKNOWN, and a rule fires only when its condition is TRUE. A rule that cannot be
evaluated is reported as such instead of silently counting as false.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence

from .features import BOOLEAN, CATEGORY, NUMBER, FeatureCatalog, FeatureVector

MAX_DEPTH = 6
MAX_NODES = 50
_OPS = ("<", "<=", ">", ">=", "=", "!=")
_LEGACY = {"et": "all", "ou": "any", "non": "not", "car": "feature", "valeur": "value", "entre": "between", "dans": "in"}

Truth = bool | None  # None means UNKNOWN


class Effect(str, Enum):
    CONFIRM = "CONFIRM"        # raises the rules component by the rule weight
    REJECT = "REJECT"          # lowers it; when blocking, forces REJECTED
    ABSTAIN = "ABSTAIN"        # an ACCEPTED decision is sent to human review
    RECLASSIFY = "RECLASSIFY"  # changes the class of the object


class RuleError(ValueError):
    pass


# ---------------------------------------------------------------- conditions

def canonical(condition: Any) -> Any:
    """Return the condition with native keys (legacy keys translated)."""
    if isinstance(condition, list):
        return [canonical(c) for c in condition]
    if not isinstance(condition, Mapping):
        return condition
    out: dict[str, Any] = {}
    for k, v in condition.items():
        key = _LEGACY.get(k, k)
        out[key] = canonical(v) if key in ("all", "any", "not") else v
    return out


def validate(condition: Any, catalog: FeatureCatalog | None = None) -> list[str]:
    """Return the list of problems in a condition; empty means valid."""
    errors: list[str] = []
    count = [0]

    def walk(node: Any, depth: int, path: str) -> None:
        count[0] += 1
        if depth > MAX_DEPTH:
            errors.append(f"{path}: nesting deeper than {MAX_DEPTH}")
            return
        if not isinstance(node, Mapping):
            errors.append(f"{path}: expected an object")
            return
        if "all" in node or "any" in node:
            key = "all" if "all" in node else "any"
            items = node[key]
            if not isinstance(items, list) or not items:
                errors.append(f"{path}.{key}: expected a non-empty list")
                return
            for i, child in enumerate(items):
                walk(child, depth + 1, f"{path}.{key}[{i}]")
            return
        if "not" in node:
            walk(node["not"], depth + 1, f"{path}.not")
            return
        feat = node.get("feature")
        if not isinstance(feat, str) or not feat:
            errors.append(f"{path}: missing feature")
            return
        d = catalog.get(feat) if catalog is not None else None
        if catalog is not None and d is None:
            errors.append(f"{path}: unknown feature '{feat}'")
            return
        if "between" in node:
            b = node["between"]
            if not (isinstance(b, list) and len(b) == 2 and all(_is_number(x) for x in b) and b[0] <= b[1]):
                errors.append(f"{path}: 'between' expects [low, high] numbers with low <= high")
            elif d is not None and d.dtype != NUMBER:
                errors.append(f"{path}: 'between' needs a numeric feature")
            return
        if "in" in node:
            if not isinstance(node["in"], list) or not node["in"]:
                errors.append(f"{path}: 'in' expects a non-empty list")
            return
        op = node.get("op")
        if op not in _OPS:
            errors.append(f"{path}: unknown operator {op!r}")
            return
        if "value" not in node:
            errors.append(f"{path}: missing value")
            return
        value = node["value"]
        if d is not None:
            if d.dtype == NUMBER and not _is_number(value):
                errors.append(f"{path}: '{feat}' is numeric, got {value!r}")
            elif d.dtype == BOOLEAN and (not isinstance(value, bool) or op not in ("=", "!=")):
                errors.append(f"{path}: '{feat}' is boolean, use = or != with true/false")
            elif d.dtype == CATEGORY and op not in ("=", "!="):
                errors.append(f"{path}: '{feat}' is a category, use = or !=")

    walk(canonical(condition), 1, "$")
    if count[0] > MAX_NODES:
        errors.append(f"$: more than {MAX_NODES} nodes")
    return errors


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def evaluate(condition: Any, vector: FeatureVector, reads: dict[str, Any] | None = None) -> Truth:
    """Evaluate a canonical condition. `reads` collects the feature values consulted."""
    node = condition
    if "all" in node:
        results = [evaluate(c, vector, reads) for c in node["all"]]
        if any(r is False for r in results):
            return False
        return None if any(r is None for r in results) else True
    if "any" in node:
        results = [evaluate(c, vector, reads) for c in node["any"]]
        if any(r is True for r in results):
            return True
        return None if any(r is None for r in results) else False
    if "not" in node:
        r = evaluate(node["not"], vector, reads)
        return None if r is None else not r

    feat = node["feature"]
    actual = vector.get(feat)
    if reads is not None:
        reads[feat] = actual
    if actual is None or (isinstance(actual, float) and not math.isfinite(actual)):
        return None
    if "between" in node:
        lo, hi = node["between"]
        return _num(actual) is not None and lo <= _num(actual) <= hi
    if "in" in node:
        return actual in node["in"]
    op, expected = node["op"], node["value"]
    if op in ("=", "!="):
        equal = _num(actual) == _num(expected) if _is_number(expected) else actual == expected
        return equal if op == "=" else not equal
    a = _num(actual)
    if a is None:
        return None
    return {"<": a < expected, "<=": a <= expected, ">": a > expected, ">=": a >= expected}[op]


def _num(x: Any) -> float | None:
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    if isinstance(x, (int, float)):
        return float(x)
    return None


def features_used(condition: Any) -> set[str]:
    node = canonical(condition)
    if "all" in node or "any" in node:
        return set().union(*(features_used(c) for c in node.get("all", node.get("any"))))
    if "not" in node:
        return features_used(node["not"])
    return {node["feature"]}


def describe(condition: Any, catalog: FeatureCatalog | None = None) -> str:
    """Human-readable form of a condition, using the feature labels when known."""
    node = canonical(condition)

    def label(k: str) -> str:
        d = catalog.get(k) if catalog is not None else None
        return d.label or k if d else k

    def fmt(v: Any) -> str:
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, float):
            return f"{v:g}"
        return str(v)

    def walk(n: Any, top: bool) -> str:
        if "all" in n or "any" in n:
            key = "all" if "all" in n else "any"
            joiner = " AND " if key == "all" else " OR "
            text = joiner.join(walk(c, False) for c in n[key])
            return text if top or len(n[key]) == 1 else f"({text})"
        if "not" in n:
            return f"NOT {walk(n['not'], False)}"
        if "between" in n:
            return f"{label(n['feature'])} between {fmt(n['between'][0])} and {fmt(n['between'][1])}"
        if "in" in n:
            return f"{label(n['feature'])} in {{{', '.join(fmt(v) for v in n['in'])}}}"
        return f"{label(n['feature'])} {n['op']} {fmt(n['value'])}"

    return walk(node, True)


# ---------------------------------------------------------------------- rules

@dataclass(frozen=True)
class Rule:
    code: str
    target_class: str
    effect: Effect
    condition: Mapping[str, Any]
    weight: float = 0.5
    priority: int = 100
    blocking: bool = False
    active: bool = True
    result_class: str | None = None
    label: str = ""
    rationale: str = ""
    origin: str = "EXPERT"  # EXPERT or LEARNED
    profile: str | None = None
    stats: Mapping[str, Any] | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect", Effect(self.effect))
        object.__setattr__(self, "condition", canonical(self.condition))
        if not 0.0 <= self.weight <= 1.0:
            raise RuleError(f"rule {self.code}: weight must be within [0, 1]")
        if self.effect is Effect.RECLASSIFY and not self.result_class:
            raise RuleError(f"rule {self.code}: RECLASSIFY needs a result class")

    def check(self, catalog: FeatureCatalog | None = None) -> list[str]:
        return [f"rule {self.code}: {e}" for e in validate(self.condition, catalog)]

    def with_(self, **changes: Any) -> "Rule":
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "target_class": self.target_class,
            "effect": self.effect.value,
            "result_class": self.result_class,
            "condition": self.condition,
            "weight": self.weight,
            "priority": self.priority,
            "blocking": self.blocking,
            "active": self.active,
            "rationale": self.rationale,
            "origin": self.origin,
            "profile": self.profile,
            "stats": dict(self.stats) if self.stats else None,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Rule":
        return cls(
            code=d["code"],
            label=d.get("label", ""),
            target_class=d["target_class"],
            effect=Effect(d["effect"]),
            result_class=d.get("result_class"),
            condition=d["condition"],
            weight=float(d.get("weight", 0.5)),
            priority=int(d.get("priority", 100)),
            blocking=bool(d.get("blocking", False)),
            active=bool(d.get("active", True)),
            rationale=d.get("rationale", ""),
            origin=d.get("origin", "EXPERT"),
            profile=d.get("profile"),
            stats=d.get("stats"),
        )


def ordered(rules: Sequence[Rule]) -> list[Rule]:
    """Rules in evaluation order: priority ascending, then code for stability."""
    return sorted(rules, key=lambda r: (r.priority, r.code))
