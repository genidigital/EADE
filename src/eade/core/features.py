"""Feature dictionary and normalisation.

A domain adapter declares the features it measures. The core never knows what
a feature means; it only needs its type and how to bring it to a comparable
scale so that rules can be validated and examples compared.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

FeatureValue = float | int | bool | str | None
FeatureVector = Mapping[str, FeatureValue]

NUMBER = "number"
BOOLEAN = "boolean"
CATEGORY = "category"
_TYPES = {NUMBER, BOOLEAN, CATEGORY}


@dataclass(frozen=True)
class Normalizer:
    """How a raw value is mapped to a comparable scale.

    kind:
      identity  value as is
      scale     value / divisor
      log       log1p(value) / divisor (for heavy-tailed sizes such as areas)
      minmax    (value - low) / (high - low)
    """

    kind: str = "identity"
    divisor: float = 1.0
    low: float = 0.0
    high: float = 1.0

    def apply(self, value: float) -> float:
        if self.kind == "identity":
            return value
        if self.kind == "scale":
            return value / self.divisor
        if self.kind == "log":
            return math.log1p(max(value, 0.0)) / self.divisor
        if self.kind == "minmax":
            span = self.high - self.low
            return (value - self.low) / span if span else 0.0
        raise ValueError(f"unknown normalizer kind: {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.kind in ("scale", "log"):
            out["divisor"] = self.divisor
        if self.kind == "minmax":
            out["low"], out["high"] = self.low, self.high
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Normalizer":
        if not data:
            return cls()
        return cls(
            kind=data.get("kind", "identity"),
            divisor=float(data.get("divisor", 1.0)),
            low=float(data.get("low", 0.0)),
            high=float(data.get("high", 1.0)),
        )


@dataclass(frozen=True)
class FeatureDef:
    key: str
    dtype: str = NUMBER
    label: str = ""
    unit: str = ""
    group: str = ""
    normalizer: Normalizer = field(default_factory=Normalizer)
    # Features that describe the acquisition rather than the object (resolution,
    # orientation...) must not be used to learn decision thresholds.
    learnable: bool = True

    def __post_init__(self) -> None:
        if self.dtype not in _TYPES:
            raise ValueError(f"feature {self.key}: unknown type {self.dtype}")


class FeatureCatalog:
    """The set of features a domain can measure, keyed by feature code."""

    def __init__(self, definitions: Iterable[FeatureDef] = ()):
        self._defs: dict[str, FeatureDef] = {}
        for d in definitions:
            self.add(d)

    def add(self, definition: FeatureDef) -> None:
        if definition.key in self._defs:
            raise ValueError(f"duplicate feature: {definition.key}")
        self._defs[definition.key] = definition

    def __contains__(self, key: object) -> bool:
        return key in self._defs

    def __getitem__(self, key: str) -> FeatureDef:
        return self._defs[key]

    def __iter__(self):
        return iter(self._defs.values())

    def __len__(self) -> int:
        return len(self._defs)

    def get(self, key: str) -> FeatureDef | None:
        return self._defs.get(key)

    def numeric_value(self, key: str, value: FeatureValue) -> float | None:
        """Raw value as a float, or None when missing or not numeric."""
        if value is None:
            return None
        d = self._defs.get(key)
        if d is not None and d.dtype == CATEGORY:
            return None
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            f = float(value)
            return f if math.isfinite(f) else None
        return None

    def normalize(self, vector: FeatureVector) -> dict[str, float]:
        """Normalised numeric view of a vector. Unknown or missing features are dropped."""
        out: dict[str, float] = {}
        for key, raw in vector.items():
            d = self._defs.get(key)
            if d is None:
                continue
            v = self.numeric_value(key, raw)
            if v is None:
                continue
            out[key] = v if d.dtype == BOOLEAN else d.normalizer.apply(v)
        return out

    def to_list(self) -> list[dict[str, Any]]:
        return [
            {
                "key": d.key,
                "type": d.dtype,
                "label": d.label,
                "unit": d.unit,
                "group": d.group,
                "normalizer": d.normalizer.to_dict(),
                "learnable": d.learnable,
            }
            for d in self._defs.values()
        ]

    @classmethod
    def from_list(cls, items: Iterable[Mapping[str, Any]]) -> "FeatureCatalog":
        return cls(
            FeatureDef(
                key=i["key"],
                dtype=i.get("type", NUMBER),
                label=i.get("label", ""),
                unit=i.get("unit", ""),
                group=i.get("group", ""),
                normalizer=Normalizer.from_dict(i.get("normalizer")),
                learnable=i.get("learnable", True),
            )
            for i in items
        )
