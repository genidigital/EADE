"""Signatures: the average portrait of validated cases, and similarity to them.

For each class EADE keeps up to two signatures built from expert-validated
examples: a positive one (true objects of that class) and a negative one
(candidates that turned out not to be). A candidate's similarity compares its
distance to both.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

POSITIVE = "+"
NEGATIVE = "-"


@dataclass(frozen=True)
class SimilarityParams:
    min_count: int = 5          # a signature built on fewer examples is ignored
    min_shared: int = 3         # features shared with the candidate needed to compare
    std_floor: float = 0.25     # keeps a near-constant feature from dominating the distance
    max_distance: float = 3.0   # distance at which a one-sided similarity reaches 0
    coverage: float = 0.5       # a feature enters a signature if present in this share of examples

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_count": self.min_count,
            "min_shared": self.min_shared,
            "std_floor": self.std_floor,
            "max_distance": self.max_distance,
            "coverage": self.coverage,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> "SimilarityParams":
        d = d or {}
        base = cls()
        return cls(
            min_count=int(d.get("min_count", base.min_count)),
            min_shared=int(d.get("min_shared", base.min_shared)),
            std_floor=float(d.get("std_floor", base.std_floor)),
            max_distance=float(d.get("max_distance", base.max_distance)),
            coverage=float(d.get("coverage", base.coverage)),
        )


@dataclass(frozen=True)
class Signature:
    target_class: str
    polarity: str
    means: Mapping[str, float]
    stds: Mapping[str, float]
    count: int
    profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_class": self.target_class,
            "polarity": self.polarity,
            "profile": self.profile,
            "count": self.count,
            "means": dict(sorted(self.means.items())),
            "stds": dict(sorted(self.stds.items())),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Signature":
        return cls(
            target_class=d["target_class"],
            polarity=d["polarity"],
            profile=d.get("profile"),
            count=int(d["count"]),
            means={k: float(v) for k, v in d["means"].items()},
            stds={k: float(v) for k, v in d["stds"].items()},
        )


def build_signature(
    target_class: str,
    polarity: str,
    vectors: Iterable[Mapping[str, float]],
    params: SimilarityParams = SimilarityParams(),
    profile: str | None = None,
) -> Signature | None:
    """Mean and spread of normalised vectors. None when there are too few examples."""
    vectors = list(vectors)
    n = len(vectors)
    if n < max(params.min_count, 1):
        return None
    keys = {k for v in vectors for k in v}
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    for k in sorted(keys):
        values = [v[k] for v in vectors if k in v]
        if len(values) < params.coverage * n or len(values) < 2:
            continue
        m = sum(values) / len(values)
        var = sum((x - m) ** 2 for x in values) / (len(values) - 1)
        means[k] = m
        stds[k] = math.sqrt(var)
    if not means:
        return None
    return Signature(target_class, polarity, means, stds, n, profile)


def distance(vector: Mapping[str, float], sig: Signature, params: SimilarityParams = SimilarityParams()) -> float | None:
    """Root mean square of z-scores over shared features; None if too few are shared."""
    shared = [k for k in sig.means if k in vector]
    if len(shared) < params.min_shared:
        return None
    total = 0.0
    for k in shared:
        z = (vector[k] - sig.means[k]) / max(sig.stds.get(k, 0.0), params.std_floor)
        total += z * z
    return math.sqrt(total / len(shared))


def similarity(
    vector: Mapping[str, float],
    positive: Signature | None,
    negative: Signature | None,
    params: SimilarityParams = SimilarityParams(),
) -> tuple[float | None, dict[str, Any]]:
    """Similarity in [0, 1] to the positive cases, with the distances used.

    With both signatures, 1 means "looks like the validated positives and not
    like the negatives". With one, the distance is mapped linearly to [0, 1].
    """
    usable = lambda s: s is not None and s.count >= params.min_count  # noqa: E731
    d_pos = distance(vector, positive, params) if usable(positive) else None
    d_neg = distance(vector, negative, params) if usable(negative) else None
    detail = {"distance_positive": d_pos, "distance_negative": d_neg}
    if d_pos is not None and d_neg is not None:
        total = d_pos + d_neg
        return (0.5 if total == 0 else d_neg / total), detail
    if d_pos is not None:
        return max(0.0, 1.0 - d_pos / params.max_distance), detail
    if d_neg is not None:
        return min(1.0, d_neg / params.max_distance), detail
    return None, detail
