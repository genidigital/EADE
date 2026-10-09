"""Knowledge versions: everything the engine decides with, versioned and fingerprinted.

A version bundles the fusion settings, the profiles, the rules and the
signatures. Only a DRAFT can change; once published a version is frozen, and
its fingerprint certifies that what was evaluated is exactly what is deployed.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .rules import Rule, ordered
from .signatures import Signature, SimilarityParams


class Status(str, Enum):
    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class FrozenVersionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Ramp:
    """Evidence from one feature rising linearly from `low` (0) to `full` (1).

    Typical use: height above ground for buildings. A ramp only applies to the
    listed classes (all classes when empty), and is omitted when the feature is
    missing, so missing elevation data never invalidates a candidate.
    """

    name: str
    feature: str
    low: float
    full: float
    weight: float = 0.5
    classes: tuple[str, ...] = ()

    def value(self, raw: float) -> float:
        if self.full == self.low:
            return 1.0 if raw >= self.full else 0.0
        return min(1.0, max(0.0, (raw - self.low) / (self.full - self.low)))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "feature": self.feature, "low": self.low, "full": self.full,
                "weight": self.weight, "classes": list(self.classes)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Ramp":
        return cls(d["name"], d["feature"], float(d["low"]), float(d["full"]),
                   float(d.get("weight", 0.5)), tuple(d.get("classes", ())))


@dataclass(frozen=True)
class EngineConfig:
    classic_weight: float = 1.0
    rules_weight: float = 1.0
    similarity_weight: float = 1.0
    ramps: tuple[Ramp, ...] = ()
    accept_threshold: float = 0.60
    reject_threshold: float = 0.35
    similarity: SimilarityParams = field(default_factory=SimilarityParams)

    def __post_init__(self) -> None:
        if not 0.0 <= self.reject_threshold < self.accept_threshold <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= reject < accept <= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": {"classic": self.classic_weight, "rules": self.rules_weight,
                        "similarity": self.similarity_weight},
            "thresholds": {"accept": self.accept_threshold, "reject": self.reject_threshold},
            "ramps": [r.to_dict() for r in self.ramps],
            "similarity": self.similarity.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> "EngineConfig":
        d = d or {}
        w = d.get("weights", {})
        t = d.get("thresholds", {})
        base = cls()
        return cls(
            classic_weight=float(w.get("classic", base.classic_weight)),
            rules_weight=float(w.get("rules", base.rules_weight)),
            similarity_weight=float(w.get("similarity", base.similarity_weight)),
            ramps=tuple(Ramp.from_dict(r) for r in d.get("ramps", ())),
            accept_threshold=float(t.get("accept", base.accept_threshold)),
            reject_threshold=float(t.get("reject", base.reject_threshold)),
            similarity=SimilarityParams.from_dict(d.get("similarity")),
        )


@dataclass(frozen=True)
class Profile:
    """A context in which specific rules and signatures apply (a region, a sensor...).

    `criteria` maps a context key to an exact value or to a {"min", "max"} range.
    """

    code: str
    label: str = ""
    criteria: Mapping[str, Any] = field(default_factory=dict)

    def matches(self, context: Mapping[str, Any]) -> bool:
        for key, expected in self.criteria.items():
            actual = context.get(key)
            if actual is None:
                return False
            if isinstance(expected, Mapping):
                lo, hi = expected.get("min"), expected.get("max")
                if not isinstance(actual, (int, float)):
                    return False
                if lo is not None and actual < lo:
                    return False
                if hi is not None and actual > hi:
                    return False
            elif actual != expected:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "label": self.label, "criteria": dict(self.criteria)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Profile":
        return cls(d["code"], d.get("label", ""), dict(d.get("criteria", {})))


@dataclass(frozen=True)
class KnowledgeVersion:
    number: int
    label: str = ""
    description: str = ""
    status: Status = Status.DRAFT
    parent: int | None = None
    config: EngineConfig = field(default_factory=EngineConfig)
    profiles: tuple[Profile, ...] = ()
    rules: tuple[Rule, ...] = ()
    signatures: tuple[Signature, ...] = ()
    publication: str | None = None  # EVALUATED or MANUAL once published

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", Status(self.status))
        object.__setattr__(self, "rules", tuple(ordered(self.rules)))
        codes = [r.code for r in self.rules]
        if len(codes) != len(set(codes)):
            raise ValueError("rule codes must be unique within a version")
        known = {p.code for p in self.profiles}
        for r in self.rules:
            if r.profile is not None and r.profile not in known:
                raise ValueError(f"rule {r.code}: unknown profile {r.profile}")

    # ------------------------------------------------------------ lifecycle

    @property
    def frozen(self) -> bool:
        return self.status in (Status.PUBLISHED, Status.ARCHIVED)

    def evolve(self, **changes: Any) -> "KnowledgeVersion":
        """A modified copy. Only a draft or candidate can change."""
        if self.frozen:
            raise FrozenVersionError(f"version {self.number} is {self.status.value} and cannot change")
        return replace(self, **changes)

    def new_draft(self, number: int, label: str = "", description: str = "") -> "KnowledgeVersion":
        """A full copy as a new draft, whatever the status of this version."""
        return replace(self, number=number, label=label or self.label, description=description,
                       status=Status.DRAFT, parent=self.number, publication=None)

    def published(self, how: str = "EVALUATED") -> "KnowledgeVersion":
        if self.frozen:
            raise FrozenVersionError(f"version {self.number} is already {self.status.value}")
        return replace(self, status=Status.PUBLISHED, publication=how)

    def archived(self) -> "KnowledgeVersion":
        return replace(self, status=Status.ARCHIVED)

    def with_rule(self, rule: Rule) -> "KnowledgeVersion":
        others = tuple(r for r in self.rules if r.code != rule.code)
        return self.evolve(rules=others + (rule,))

    def without_rule(self, code: str) -> "KnowledgeVersion":
        return self.evolve(rules=tuple(r for r in self.rules if r.code != code))

    # ------------------------------------------------------------ lookups

    def profile_for(self, context: Mapping[str, Any] | None) -> Profile | None:
        if not context:
            return None
        return next((p for p in self.profiles if p.matches(context)), None)

    def rules_for(self, target_class: str, profile: str | None) -> list[Rule]:
        return [r for r in self.rules
                if r.active and r.target_class == target_class and r.profile in (None, profile)]

    def signature(self, target_class: str, polarity: str, profile: str | None) -> Signature | None:
        """The profile-specific signature if any, else the general one."""
        general = None
        for s in self.signatures:
            if s.target_class == target_class and s.polarity == polarity:
                if profile is not None and s.profile == profile:
                    return s
                if s.profile is None:
                    general = s
        return general

    # ------------------------------------------------------------ identity

    def fingerprint(self) -> str:
        """SHA-256 of everything that affects decisions, in canonical form.

        Labels, descriptions, rationales and statistics are left out: renaming a
        rule must not force a new evaluation, changing a threshold must.
        """
        payload = {
            "config": self.config.to_dict(),
            "profiles": sorted((p.to_dict() for p in self.profiles), key=lambda p: p["code"]),
            "rules": sorted(
                ({k: v for k, v in r.to_dict().items() if k not in ("label", "rationale", "stats", "origin")}
                 for r in self.rules),
                key=lambda r: r["code"]),
            "signatures": sorted((s.to_dict() for s in self.signatures),
                                 key=lambda s: (s["target_class"], s["polarity"], s["profile"] or "")),
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no spaces, numbers normalised (1 == 1.0)."""
    return json.dumps(_canon(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canon(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        if not math.isfinite(f):
            raise ValueError("non-finite number in knowledge")
        return int(f) if f.is_integer() else round(f, 12)
    if isinstance(v, Mapping):
        return {str(k): _canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    if isinstance(v, Enum):
        return v.value
    raise TypeError(f"cannot canonicalise {type(v).__name__}")


def empty_version(number: int = 1, label: str = "Initial") -> KnowledgeVersion:
    return KnowledgeVersion(number=number, label=label)


def merge_rules(base: Sequence[Rule], extra: Iterable[Rule]) -> tuple[Rule, ...]:
    """Rules of `base` with those of `extra` added or replacing same-code ones."""
    out = {r.code: r for r in base}
    for r in extra:
        out[r.code] = r
    return tuple(out.values())
