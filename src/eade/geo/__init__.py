"""EADE Geo: the geospatial adapter.

Reads rasters and vectors through GDAL, proposes candidates from elevation
models and orthophotos, measures them with the geo feature dictionary and
computes overlaps and measures for evaluation.

Install with `pip install eade[geo]`.
"""

try:
    import numpy  # noqa: F401
    import rasterio  # noqa: F401
    import shapely  # noqa: F401
except ImportError as e:  # pragma: no cover
    raise ImportError("eade.geo needs the geospatial extra: pip install \"eade[geo]\"") from e

from .catalog import GEO_CATALOG, geo_catalog
from .crs import grid_key, utm_epsg
from .detect import DetectorParams, HeightDetector
from .extract import GeoFeatureExtractor
from .geometry import iou, measure
from .pipeline import GeoPipeline, PipelineResult
from .raster import RasterSources

__all__ = [
    "GEO_CATALOG", "geo_catalog", "grid_key", "utm_epsg", "DetectorParams", "HeightDetector",
    "GeoFeatureExtractor", "iou", "measure", "GeoPipeline", "PipelineResult", "RasterSources",
]
