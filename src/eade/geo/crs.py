"""Coordinate reference systems: metric work, UTM zones and the evaluation grid."""

from __future__ import annotations

import math
from functools import lru_cache

from pyproj import CRS, Transformer
import shapely
from shapely.geometry.base import BaseGeometry

WGS84 = CRS.from_epsg(4326)


def utm_epsg(lon: float, lat: float) -> int:
    """EPSG code of the WGS 84 / UTM zone containing a point."""
    zone = min(60, max(1, int((lon + 180) // 6) + 1))
    return (32600 if lat >= 0 else 32700) + zone


@lru_cache(maxsize=64)
def _transformer(src: str, dst: str) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(src), CRS.from_user_input(dst), always_xy=True)


def reproject(geom: BaseGeometry, src, dst) -> BaseGeometry:
    s, d = CRS.from_user_input(src), CRS.from_user_input(dst)
    if s == d:
        return geom
    t = _transformer(s.to_wkt(), d.to_wkt())
    return shapely.transform(geom, lambda x, y: t.transform(x, y), interleaved=False)


def require_metric(crs) -> CRS:
    """The CRS, if it is projected in metres; otherwise a clear error."""
    c = CRS.from_user_input(crs)
    if not c.is_projected:
        raise ValueError(f"{c.name} is not projected: reproject the data to a metric CRS (for example UTM)")
    unit = c.axis_info[0].unit_name.lower() if c.axis_info else ""
    if unit not in ("metre", "meter", "m"):
        raise ValueError(f"{c.name} uses '{unit}' units: a CRS in metres is required")
    return c


def grid_key(geom: BaseGeometry, crs, cell_m: float = 200.0) -> str:
    """Key of the UTM grid cell holding the geometry's centroid.

    Examples are grouped by cell before the train/test split so that
    near-identical neighbours never fall on both sides.
    """
    c = geom.centroid
    lon, lat = (c.x, c.y)
    src = CRS.from_user_input(crs)
    if src != WGS84:
        lon, lat = _transformer(src.to_wkt(), WGS84.to_wkt()).transform(c.x, c.y)
    epsg = utm_epsg(lon, lat)
    x, y = _transformer(WGS84.to_wkt(), CRS.from_epsg(epsg).to_wkt()).transform(lon, lat)
    return f"{epsg}:{math.floor(x / cell_m)}:{math.floor(y / cell_m)}"
