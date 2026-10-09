"""End-to-end geo run: detect candidates, add parcel context, decide, keep provenance."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable

from shapely.geometry.base import BaseGeometry

from ..core.decision import Decision, Engine, Result
from ..core.knowledge import KnowledgeVersion
from .catalog import geo_catalog
from .detect import HeightDetector
from .extract import ParcelIndex
from .raster import RasterSources
from .vector import read_features


@dataclass
class PipelineResult:
    results: list[Result]
    crs: Any
    provenance: dict[str, Any] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        out = {d.value: 0 for d in Decision}
        for r in self.results:
            out[r.decision.value] += 1
        return out


class GeoPipeline:
    """Runs the detection provider and the decision engine over raster sources.

    Without a knowledge version the classic verdicts are kept as they are,
    which is exactly the behaviour of a platform where EADE is switched off.
    """

    def __init__(self, version: KnowledgeVersion | None = None, detector: HeightDetector | None = None):
        self.detector = detector or HeightDetector()
        self.version = version or KnowledgeVersion(number=0, label="Classic engine only")
        self.engine = Engine(self.version, geo_catalog())

    def run(self, sources: RasterSources, bounds: tuple[float, float, float, float] | None = None,
            parcels: Iterable[tuple[Any, BaseGeometry]] | str | None = None,
            parcel_id_field: str | None = None) -> PipelineResult:
        started = datetime.now(timezone.utc)
        results: list[Result] = []
        with sources.open() as opened:
            crs = opened.crs
            index = None
            if isinstance(parcels, str):
                parcels = [(pid, g) for pid, g, _ in read_features(parcels, crs, parcel_id_field)]
            if parcels is not None:
                index = ParcelIndex(parcels)
            for cand in self.detector.candidates(opened, {"bounds": bounds}):
                if index is not None:
                    ctx, parcel_id = index.context(cand.geometry)
                    cand = replace(cand, features={**cand.features, **ctx},
                                   meta={**cand.meta, "parcel_id": parcel_id})
                results.append(self.engine.decide(cand))
        return PipelineResult(results, crs, {
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sources": sources.describe(),
            "detector": self.detector.describe(),
            "knowledge": {"version": self.version.number, "label": self.version.label,
                          "fingerprint": self.engine.fingerprint},
        })
