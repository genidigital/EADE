"""The geo feature dictionary: what EADE Geo measures on every candidate."""

from __future__ import annotations

from ..core.features import BOOLEAN, FeatureCatalog, FeatureDef, Normalizer

EXTRACTOR_VERSION = "geo-1"


def _f(key, label, unit="", group="", norm=None, dtype="number", learnable=True) -> FeatureDef:
    return FeatureDef(key, dtype=dtype, label=label, unit=unit, group=group,
                      normalizer=norm or Normalizer(), learnable=learnable)


def geo_catalog() -> FeatureCatalog:
    log = lambda d: Normalizer("log", divisor=d)  # noqa: E731
    scale = lambda d: Normalizer("scale", divisor=d)  # noqa: E731
    G, E, S, T, Q, C = "geometry", "elevation", "spectral", "texture", "quality", "context"
    return FeatureCatalog([
        _f("area_m2", "Area", "m²", G, log(8)),
        _f("perimeter_m", "Perimeter", "m", G, log(6)),
        _f("compactness", "Compactness", "", G),
        _f("rectangularity", "Rectangularity", "", G),
        _f("elongation", "Elongation", "ratio", G, log(3)),
        _f("orientation_deg", "Orientation", "deg", G, scale(180), learnable=False),
        _f("width_m", "Width", "m", G, log(4)),
        _f("vertex_count", "Vertices", "", G, log(5)),

        _f("height_median_m", "Median height above ground", "m", E, scale(10)),
        _f("height_p90_m", "Height P90", "m", E, scale(10)),
        _f("height_p10_m", "Height P10", "m", E, scale(10)),
        _f("height_spread_m", "Height spread P90 - P25", "m", E, scale(5)),
        _f("slope_mean", "Mean surface slope", "m/m", E, scale(2)),
        _f("steep_edge_share", "Share of outline that is a wall", "", E),
        _f("curvature_median", "Median surface curvature", "1/m", E, scale(0.5)),
        _f("rough_share", "Share of rough surface", "", E),

        _f("red_mean", "Mean red", "0-255", S, scale(255)),
        _f("green_mean", "Mean green", "0-255", S, scale(255)),
        _f("blue_mean", "Mean blue", "0-255", S, scale(255)),
        _f("brightness", "Brightness", "0-255", S, scale(255)),
        _f("contrast", "Contrast", "0-255", S, scale(64)),
        _f("saturation", "Saturation", "", S),
        _f("hue_cos", "Hue (cosine)", "", S),
        _f("hue_sin", "Hue (sine)", "", S),
        _f("excess_green", "Excess green index", "", S),
        _f("green_share", "Share of green pixels", "", S),

        _f("local_variance", "Local variance", "", T, log(6)),
        _f("gradient_mean", "Mean gradient", "0-255", T, scale(64)),
        _f("edge_density", "Edge density", "", T),

        _f("elevation_coverage", "Elevation data coverage", "", Q),
        _f("shadow_share", "Share in shadow", "", Q),
        _f("resolution_m", "Pixel size", "m", Q, learnable=False),
        _f("truncated", "Cut by data edge", "", Q, dtype=BOOLEAN),

        _f("parcel_share", "Share inside its parcel", "", C),
        _f("parcel_count", "Parcels touched", "", C, scale(5)),
        _f("boundary_distance_m", "Distance from centre to parcel boundary", "m", C, log(3)),
        _f("touches_boundary", "Touches the parcel boundary", "", C, dtype=BOOLEAN),
    ])


GEO_CATALOG = geo_catalog()
