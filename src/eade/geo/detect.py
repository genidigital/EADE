"""Classic candidate detection from elevation: anything standing above the ground.

This is EADE Geo's built-in detection provider. It deliberately over-proposes
(low height threshold) and gives its own verdict with a reason, so EADE can
confirm, doubt or overturn it. Other providers (a host platform's engine, a
neural network) can replace it as long as they emit Candidates.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Iterator, Mapping

import numpy as np
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import shape
from shapely.validation import make_valid

from ..core.decision import Candidate
from .extract import GeoFeatureExtractor
from .raster import OpenSources, Patch, RasterSources

BUILDING = "BUILDING"


@dataclass(frozen=True)
class DetectorParams:
    candidate_height_m: float = 1.2   # pixels above this height form candidates
    min_candidate_m2: float = 2.0     # smaller blobs are noise and dropped entirely
    accept_height_m: float = 2.2      # the classic verdict: median height needed
    accept_area_m2: float = 10.0      #   minimum footprint
    max_green_share: float = 0.45     #   a greener candidate is taken for vegetation
    simplify_m: float = 0.25
    opening_m: float = 0.4
    tile_m: float = 200.0
    overlap_m: float = 25.0


class HeightDetector:
    name = "eade-geo-height"
    version = "1"

    def __init__(self, params: DetectorParams = DetectorParams(), extractor: GeoFeatureExtractor | None = None):
        self.params = params
        self.extractor = extractor or GeoFeatureExtractor()

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "extractor": self.extractor.version,
                "params": asdict(self.params)}

    def candidates(self, source: RasterSources | OpenSources, options: Mapping[str, Any] | None = None
                   ) -> Iterator[Candidate]:
        """Candidates over `options["bounds"]` (reference CRS), or the whole raster."""
        options = options or {}
        if isinstance(source, RasterSources):
            with source.open() as opened:
                yield from self.candidates(opened, options)
            return
        if source.dsm is None:
            raise ValueError("the height detector needs a surface model (DSM)")
        p = self.params
        for window, core in source.tiles(options.get("bounds"), p.tile_m, p.overlap_m):
            patch = source.read(window)
            yield from self.detect_tile(patch, core)

    def verdict(self, f: Mapping[str, Any]) -> tuple[bool, str | None]:
        """The classic decision and, when rejected, why."""
        p = self.params
        if f.get("area_m2", 0) < p.accept_area_m2:
            return False, "SMALL"
        if (f.get("green_share") or 0) > p.max_green_share:
            return False, "VEGETATION"
        h = f.get("height_median_m")
        if h is None or h < p.accept_height_m:
            return False, "LOW"
        return True, None

    def detect_tile(self, patch: Patch, core: tuple[float, float, float, float]) -> Iterator[Candidate]:
        """Candidates whose centroid lies in `core`, measured on an already read patch."""
        p, res = self.params, patch.resolution
        ndsm = patch.ndsm
        mask = np.nan_to_num(ndsm, nan=-1.0) >= p.candidate_height_m
        radius = max(1, int(round(p.opening_m / res / 2)))
        mask = ndimage.binary_opening(mask, structure=np.ones((2 * radius + 1,) * 2, bool))
        mask = ndimage.binary_fill_holes(mask)
        labels, n = ndimage.label(mask)
        if n == 0:
            return
        min_px = p.min_candidate_m2 / (res * res)
        sizes = ndimage.sum_labels(mask, labels, index=np.arange(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes >= min_px
        labels = np.where(keep[labels], labels, 0).astype("int32")

        cx0, cy0, cx1, cy1 = core
        for geom_json, value in shapes(labels, mask=labels > 0, transform=patch.transform):
            geom = make_valid(shape(geom_json)).simplify(p.simplify_m, preserve_topology=True)
            if geom.geom_type == "GeometryCollection":
                polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
                if not polys:
                    continue
                geom = max(polys, key=lambda g: g.area)
            if geom.is_empty or geom.area < p.min_candidate_m2:
                continue
            c = geom.centroid
            if not (cx0 <= c.x < cx1 and cy0 <= c.y < cy1):
                continue  # another tile owns this object
            features = self.extractor.measure_on_patch(geom, patch)
            accepted, reason = self.verdict(features)
            cid = hashlib.sha1(f"{c.x:.2f}:{c.y:.2f}".encode()).hexdigest()[:12]
            yield Candidate(id=cid, target_class=BUILDING, features=features, classic_accepted=accepted,
                            context={"resolution_m": res}, geometry=geom,
                            meta={"provider": self.name, "provider_version": self.version,
                                  "classic_reason": reason})
