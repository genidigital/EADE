"""Feature extraction: measuring a footprint on the elevation models and orthophoto."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

import numpy as np
from rasterio.features import geometry_mask
from scipy import ndimage
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from ..core.features import FeatureCatalog
from .catalog import EXTRACTOR_VERSION, geo_catalog
from .geometry import shape_features
from .raster import OpenSources, Patch

STEEP_SLOPE = 1.0        # 45 degrees: an outline pixel steeper than this is a wall
ROUGH_M = 0.15           # deviation from the smoothed surface counted as rough
SHADOW_BRIGHTNESS = 45.0
GREEN_EXG = 0.08
EDGE_GRADIENT = 40.0


class ParcelIndex:
    """Parcels for context features, in the same metric CRS as the candidates."""

    def __init__(self, parcels: Iterable[tuple[Any, BaseGeometry]]):
        items = [(pid, g) for pid, g in parcels if g is not None and not g.is_empty]
        self.ids = [pid for pid, _ in items]
        self.geoms = [g for _, g in items]
        self.tree = STRtree(self.geoms) if self.geoms else None

    def context(self, geom: BaseGeometry) -> tuple[dict[str, Any], Any]:
        """Context features and the id of the parcel holding most of the object."""
        if self.tree is None or geom.area == 0:
            return {}, None
        best, best_area, touched = None, 0.0, 0
        for i in self.tree.query(geom):
            inter = self.geoms[i].intersection(geom).area
            if inter > 1.0:
                touched += 1
            if inter > best_area:
                best, best_area = i, inter
        if best is None:
            return {"parcel_share": 0.0, "parcel_count": 0.0}, None
        parcel = self.geoms[best]
        return {
            "parcel_share": best_area / geom.area,
            "parcel_count": float(touched),
            "boundary_distance_m": geom.centroid.distance(parcel.boundary),
            "touches_boundary": geom.intersects(parcel.boundary.buffer(0.3)),
        }, self.ids[best]


class GeoFeatureExtractor:
    version = EXTRACTOR_VERSION

    def catalog(self) -> FeatureCatalog:
        return geo_catalog()

    def measure(self, geom: BaseGeometry, sources: OpenSources, context: Mapping[str, Any] | None = None,
                pad_m: float = 3.0) -> dict[str, Any]:
        """Measure any footprint, for instance one drawn by an operator."""
        patch = sources.read(sources.window_for(geom.bounds, pad_m))
        return self.measure_on_patch(geom, patch)

    def measure_on_patch(self, geom: BaseGeometry, patch: Patch) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if isinstance(geom, Polygon) or geom.geom_type == "MultiPolygon":
            out.update(shape_features(geom))
        out["resolution_m"] = patch.resolution

        sub, mask = _crop(patch, geom)
        if mask is None or not mask.any():
            out["truncated"] = True
            return out
        # Cut by data edge: the footprint reaches beyond the raster or onto no-data
        ring = ndimage.binary_dilation(mask, iterations=2)
        nodata = ~sub.inside_raster
        if sub.dsm is not None:
            nodata |= np.isnan(sub.dsm)
        elif sub.rgb is not None:
            nodata |= np.isnan(sub.rgb[0])
        out["truncated"] = bool((ring & nodata).any())

        if sub.ndsm is not None:
            out.update(_elevation(sub, mask))
        if sub.rgb is not None:
            out.update(_spectral(sub.rgb, mask))
        return out


def _crop(patch: Patch, geom: BaseGeometry, pad_px: int = 3) -> tuple[Patch, np.ndarray | None]:
    """The part of the patch around the geometry, and the geometry's pixel mask."""
    inv = ~patch.transform
    x0, y0, x1, y1 = geom.bounds
    cols = [c for c, _ in (inv @ (x0, y0), inv @ (x1, y1))]
    rows = [r for _, r in (inv @ (x0, y0), inv @ (x1, y1))]
    h, w = patch.shape
    c0, c1 = max(0, int(math.floor(min(cols))) - pad_px), min(w, int(math.ceil(max(cols))) + pad_px)
    r0, r1 = max(0, int(math.floor(min(rows))) - pad_px), min(h, int(math.ceil(max(rows))) + pad_px)
    if c0 >= c1 or r0 >= r1:
        return patch, None
    sl = (slice(r0, r1), slice(c0, c1))
    t = patch.transform @ patch.transform.translation(c0, r0)
    sub = Patch(t, patch.crs, patch.resolution,
                None if patch.dsm is None else patch.dsm[sl],
                None if patch.ndsm is None else patch.ndsm[sl],
                None if patch.rgb is None else patch.rgb[:, sl[0], sl[1]],
                patch.inside_raster[sl])
    mask = geometry_mask([geom], out_shape=(r1 - r0, c1 - c0), transform=t, invert=True, all_touched=False)
    if not mask.any():  # very small objects: take every touched pixel
        mask = geometry_mask([geom], out_shape=(r1 - r0, c1 - c0), transform=t, invert=True, all_touched=True)
    return sub, mask


def _elevation(p: Patch, mask: np.ndarray) -> dict[str, float]:
    res = p.resolution
    h = p.ndsm[mask]
    valid = np.isfinite(h)
    out: dict[str, float] = {"elevation_coverage": float(valid.mean())}
    if valid.sum() < 3:
        return out
    hv = h[valid]
    p10, p25, p50, p90 = np.percentile(hv, [10, 25, 50, 90])
    out.update(height_median_m=float(p50), height_p90_m=float(p90), height_p10_m=float(p10),
               height_spread_m=float(p90 - p25))

    surface = np.where(np.isfinite(p.dsm), p.dsm, np.nanmedian(p.dsm[mask]) if np.isfinite(p.dsm[mask]).any() else 0)
    gy, gx = np.gradient(surface, res)
    slope = np.hypot(gx, gy)
    inner = ndimage.binary_erosion(mask, iterations=1)
    interior = inner if inner.any() else mask
    out["slope_mean"] = float(np.mean(slope[interior]))
    edge = mask & ~inner
    out["steep_edge_share"] = float(np.mean(slope[edge] > STEEP_SLOPE)) if edge.any() else 0.0
    curvature = np.abs(ndimage.laplace(surface)) / (res * res)
    out["curvature_median"] = float(np.median(curvature[interior]))
    smooth = ndimage.gaussian_filter(surface, sigma=max(1.0, 0.3 / res))
    out["rough_share"] = float(np.mean(np.abs(surface - smooth)[interior] > ROUGH_M))
    return out


def _spectral(rgb: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    px = rgb[:, mask]
    px = px[:, np.isfinite(px).all(axis=0)]
    if px.shape[1] == 0:
        return {}
    r, g, b = px
    total = r + g + b + 1e-6
    exg = (2 * g - r - b) / total
    mx, mn = px.max(axis=0), px.min(axis=0)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    # hue on the colour circle, averaged as a vector weighted by saturation
    hue = np.arctan2(math.sqrt(3) * (g - b), 2 * r - g - b)
    wsum = sat.sum()
    hc = float((np.cos(hue) * sat).sum() / wsum) if wsum > 0 else 0.0
    hs = float((np.sin(hue) * sat).sum() / wsum) if wsum > 0 else 0.0
    brightness = (r + g + b) / 3.0

    gray = np.nanmean(rgb, axis=0)
    gray = np.where(np.isfinite(gray), gray, np.nanmean(gray) if np.isfinite(gray).any() else 0.0)
    mean3 = ndimage.uniform_filter(gray, 3)
    local_var = ndimage.uniform_filter(gray * gray, 3) - mean3 * mean3
    grad = np.hypot(ndimage.sobel(gray, axis=0), ndimage.sobel(gray, axis=1)) / 8.0
    return {
        "red_mean": float(r.mean()), "green_mean": float(g.mean()), "blue_mean": float(b.mean()),
        "brightness": float(brightness.mean()), "contrast": float(brightness.std()),
        "saturation": float(sat.mean()), "hue_cos": hc, "hue_sin": hs,
        "excess_green": float(exg.mean()), "green_share": float(np.mean(exg > GREEN_EXG)),
        "shadow_share": float(np.mean(brightness < SHADOW_BRIGHTNESS)),
        "local_variance": float(np.mean(np.maximum(local_var[mask], 0))),
        "gradient_mean": float(np.mean(grad[mask])),
        "edge_density": float(np.mean(grad[mask] > EDGE_GRADIENT)),
    }
