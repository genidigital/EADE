"""Geometry measures. Inputs are expected in a metric CRS."""

from __future__ import annotations

import math

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

LINE_BUFFER_M = 0.5  # linear objects (fences) are compared as 0.5 m corridors


def _is_linear(g: BaseGeometry) -> bool:
    return isinstance(g, (LineString, MultiLineString))


def measure(g: BaseGeometry) -> float:
    """Area for surfaces, length for linear objects."""
    return g.length if _is_linear(g) else g.area


def iou(a: BaseGeometry, b: BaseGeometry) -> float:
    """Intersection over union, 1 = identical, 0 = disjoint."""
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    if _is_linear(a):
        a = a.buffer(LINE_BUFFER_M, cap_style="flat")
    if _is_linear(b):
        b = b.buffer(LINE_BUFFER_M, cap_style="flat")
    if not a.intersects(b):
        return 0.0
    union = a.union(b).area
    return a.intersection(b).area / union if union else 0.0


def shape_features(g: Polygon | MultiPolygon) -> dict[str, float]:
    """Geometry group of the geo dictionary."""
    area, perim = g.area, g.length
    rect = g.minimum_rotated_rectangle
    coords = list(rect.exterior.coords) if isinstance(rect, Polygon) else []
    sides = []
    if len(coords) >= 4:
        sides = [math.dist(coords[i], coords[i + 1]) for i in range(2)]
        long_i = 0 if sides[0] >= sides[1] else 1
        dx = coords[long_i + 1][0] - coords[long_i][0]
        dy = coords[long_i + 1][1] - coords[long_i][1]
        orientation = math.degrees(math.atan2(dy, dx)) % 180.0
    else:
        orientation = 0.0
    long_side, short_side = (max(sides), min(sides)) if sides else (0.0, 0.0)
    polys = g.geoms if isinstance(g, MultiPolygon) else [g]
    vertices = sum(len(p.exterior.coords) - 1 for p in polys)
    return {
        "area_m2": area,
        "perimeter_m": perim,
        "compactness": 4 * math.pi * area / perim ** 2 if perim else 0.0,
        "rectangularity": area / rect.area if rect.area else 0.0,
        "elongation": long_side / short_side if short_side else 0.0,
        "orientation_deg": orientation,
        "width_m": short_side,
        "vertex_count": float(vertices),
    }
