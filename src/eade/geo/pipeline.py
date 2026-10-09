"""End-to-end geo run: detect candidates, add parcel context, decide, keep provenance."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from shapely.geometry.base import BaseGeometry

from ..core.decision import Decision, Engine, Result
from ..core.knowledge import KnowledgeVersion
from .backend import backend_name
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
            parcel_id_field: str | None = None,
            progress: Callable[[int, int], bool | None] | None = None) -> PipelineResult:
        """Detect and decide. `progress(done, total)` is called after each tile; returning False stops."""
        started = datetime.now(timezone.utc)
        results: list[Result] = []
        cancelled = False
        with sources.open() as opened:
            if opened.dsm is None:
                raise ValueError("the height detector needs a surface model (DSM)")
            crs = opened.crs
            index = None
            if isinstance(parcels, str):
                parcels = [(pid, g) for pid, g, _ in read_features(parcels, crs, parcel_id_field)]
            if parcels is not None:
                index = ParcelIndex(parcels)
            p = self.detector.params
            tiles = list(opened.tiles(bounds, p.tile_m, p.overlap_m))
            for i, (window, core) in enumerate(tiles):
                for cand in self.detector.detect_tile(opened.read(window), core):
                    if index is not None:
                        ctx, parcel_id = index.context(cand.geometry)
                        cand = replace(cand, features={**cand.features, **ctx},
                                       meta={**cand.meta, "parcel_id": parcel_id})
                    results.append(self.engine.decide(cand))
                if progress is not None and progress(i + 1, len(tiles)) is False:
                    cancelled = True
                    break
        return PipelineResult(results, crs, {
            "started_at": started.isoformat(timespec="seconds"),
            "cancelled": cancelled,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sources": sources.describe(),
            "detector": self.detector.describe(),
            "raster_backend": backend_name(),
            "knowledge": {"version": self.version.number, "label": self.version.label,
                          "fingerprint": self.engine.fingerprint},
        })
