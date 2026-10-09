import pytest

from eade import FeatureCatalog, FeatureDef, Normalizer


@pytest.fixture
def catalog() -> FeatureCatalog:
    """A small building-detection dictionary, enough to exercise every feature type."""
    return FeatureCatalog([
        FeatureDef("area_m2", label="Area", unit="m²", group="geometry", normalizer=Normalizer("log", divisor=8.0)),
        FeatureDef("rectangularity", label="Rectangularity", group="geometry"),
        FeatureDef("height_m", label="Height above ground", unit="m", group="elevation",
                   normalizer=Normalizer("scale", divisor=10.0)),
        FeatureDef("green_share", label="Green share", group="spectral"),
        FeatureDef("shadow_share", label="Shadow share", group="quality"),
        FeatureDef("truncated", dtype="boolean", label="Cut by survey edge", group="quality"),
        FeatureDef("roof", dtype="category", label="Roof material", group="spectral"),
        FeatureDef("resolution_m", label="Resolution", unit="m", group="quality", learnable=False),
    ])


# Axis-aligned boxes (x1, y1, x2, y2) stand in for geometries in evaluation tests.
def box_iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = box_area(a) + box_area(b) - inter
    return inter / union if union else 0.0


def box_area(a) -> float:
    return (a[2] - a[0]) * (a[3] - a[1])


@pytest.fixture(scope="session")
def survey(tmp_path_factory):
    pytest.importorskip("eade.geo")
    from synthetic import make_survey
    return make_survey(tmp_path_factory.mktemp("survey"))
