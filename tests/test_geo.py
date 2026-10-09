"""EADE Geo on a synthetic drone survey: 40 m x 40 m at 10 cm, UTM 30N.

Scene (heights above a flat 100 m ground):
  house   8 x 6 m, 4 m high, grey roof
  annex   5 x 5 m, 3 m high, grey roof
  tree    disc of radius 2.5 m, 5 m high, green, bumpy canopy
  car     2 x 1.5 m, 1.5 m high, red
"""

import json

import numpy as np
import pytest

pytest.importorskip("rasterio")

import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from eade import Decision, Effect, KnowledgeVersion, Rule
from eade.geo import GEO_CATALOG, GeoFeatureExtractor, GeoPipeline, HeightDetector, RasterSources, grid_key, iou, measure
from eade.geo.crs import require_metric, utm_epsg
from eade.geo.detect import DetectorParams
from eade.geo.raster import estimate_ground
from eade.geo.vector import read_features, write_results

RES = 0.1
X0, Y0 = 500000.0, 1000040.0  # top-left corner, EPSG:32630
N = 400
HOUSE = box(X0 + 5, Y0 - 15, X0 + 13, Y0 - 9)
ANNEX = box(X0 + 25, Y0 - 12, X0 + 30, Y0 - 7)
CAR = box(X0 + 20, Y0 - 35, X0 + 22, Y0 - 33.5)
TREE_C, TREE_R = (X0 + 10, Y0 - 30), 2.5


def _grid():
    xs = X0 + (np.arange(N) + 0.5) * RES
    ys = Y0 - (np.arange(N) + 0.5) * RES
    return np.meshgrid(xs, ys)


def _inside(geom, X, Y):
    x0, y0, x1, y1 = geom.bounds
    return (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)


@pytest.fixture(scope="module")
def survey(tmp_path_factory):
    d = tmp_path_factory.mktemp("survey")
    X, Y = _grid()
    rng = np.random.default_rng(1)
    dtm = np.full((N, N), 100.0, dtype="float32")
    dsm = dtm + rng.normal(0, 0.02, (N, N)).astype("float32")
    rgb = np.zeros((3, N, N), dtype="uint8")
    rgb[:] = np.array([180, 150, 110], dtype="uint8")[:, None, None]  # laterite ground

    tree = (X - TREE_C[0]) ** 2 + (Y - TREE_C[1]) ** 2 <= TREE_R ** 2
    for geom, height, colour in ((HOUSE, 4.0, (150, 150, 155)), (ANNEX, 3.0, (140, 140, 145)),
                                 (CAR, 1.5, (200, 30, 30))):
        m = _inside(geom, X, Y)
        dsm[m] = 100 + height
        rgb[:, m] = np.array(colour, dtype="uint8")[:, None]
    dsm[tree] = 105 + rng.normal(0, 0.4, tree.sum())
    rgb[:, tree] = np.array([40, 120, 40], dtype="uint8")[:, None]

    profile = dict(driver="GTiff", width=N, height=N, crs="EPSG:32630",
                   transform=from_origin(X0, Y0, RES, RES))
    paths = {}
    for name, arr in (("dsm", dsm), ("dtm", dtm)):
        paths[name] = d / f"{name}.tif"
        with rasterio.open(paths[name], "w", count=1, dtype="float32", nodata=-9999, **profile) as ds:
            ds.write(arr.astype("float32"), 1)
    paths["ortho"] = d / "ortho.tif"
    with rasterio.open(paths["ortho"], "w", count=3, dtype="uint8", **profile) as ds:
        ds.write(rgb)
    return paths


def detect(survey, **kw):
    return list(HeightDetector(DetectorParams(**kw)).candidates(
        RasterSources(survey["dsm"], survey["dtm"], survey["ortho"])))


def nearest(cands, geom):
    return max(cands, key=lambda c: iou(c.geometry, geom))


def test_detects_every_raised_object_with_a_verdict(survey):
    cands = detect(survey)
    assert len(cands) == 4
    house, annex, car = nearest(cands, HOUSE), nearest(cands, ANNEX), nearest(cands, CAR)
    tree = min(cands, key=lambda c: c.geometry.centroid.distance(box(*TREE_C, *TREE_C)))
    assert iou(house.geometry, HOUSE) > 0.9 and iou(annex.geometry, ANNEX) > 0.85
    assert house.classic_accepted and annex.classic_accepted
    assert (car.classic_accepted, car.meta["classic_reason"]) == (False, "SMALL")
    assert (tree.classic_accepted, tree.meta["classic_reason"]) == (False, "VEGETATION")


def test_features_of_a_house(survey):
    house = nearest(detect(survey), HOUSE)
    f = house.features
    assert f["area_m2"] == pytest.approx(48, rel=0.05)
    assert f["height_median_m"] == pytest.approx(4.0, abs=0.1)
    assert f["rectangularity"] > 0.95 and f["elongation"] == pytest.approx(8 / 6, rel=0.08)
    assert f["green_share"] == 0 and f["brightness"] == pytest.approx(151.7, abs=2)
    assert f["steep_edge_share"] > 0.5 and f["elevation_coverage"] == 1.0
    assert f["truncated"] is False and f["resolution_m"] == pytest.approx(RES)
    assert set(f) <= {d.key for d in GEO_CATALOG}


def test_tree_looks_green_and_bumpy(survey):
    cands = detect(survey)
    tree = min(cands, key=lambda c: c.geometry.centroid.distance(box(*TREE_C, *TREE_C)))
    house = nearest(cands, HOUSE)
    assert tree.features["green_share"] > 0.9
    assert tree.features["rough_share"] > house.features["rough_share"]
    assert tree.features["compactness"] > 0.8


def test_tiling_detects_objects_across_edges_once(survey):
    # 15 m tiles cut the house and the annex; each must still come out whole, once
    cands = detect(survey, tile_m=15.0, overlap_m=10.0)
    assert len(cands) == 4
    assert iou(nearest(cands, HOUSE).geometry, HOUSE) > 0.9


def test_without_terrain_model_ground_is_estimated(survey):
    cands = list(HeightDetector().candidates(RasterSources(survey["dsm"], None, survey["ortho"])))
    house = nearest(cands, HOUSE)
    assert house.classic_accepted and house.features["height_median_m"] == pytest.approx(4.0, abs=0.3)


def test_ground_estimate_ignores_buildings():
    dsm = np.full((300, 300), 50.0, dtype="float32")
    dsm[100:180, 100:160] = 56.0  # 8 x 6 m at 0.1 m
    ground = estimate_ground(dsm, 0.1)
    assert np.abs(ground[140, 130] - 50.0) < 0.5


def test_measure_an_operator_drawing(survey):
    drawn = box(X0 + 5.2, Y0 - 14.8, X0 + 12.8, Y0 - 9.2)
    with RasterSources(survey["dsm"], survey["dtm"], survey["ortho"]).open() as src:
        f = GeoFeatureExtractor().measure(drawn, src)
    assert f["height_median_m"] == pytest.approx(4.0, abs=0.1)
    assert f["area_m2"] == pytest.approx(drawn.area)


def test_pipeline_with_parcels_and_knowledge(survey, tmp_path):
    parcels = [("P1", box(X0, Y0 - 20, X0 + 20, Y0)), ("P2", box(X0 + 20, Y0 - 20, X0 + 40, Y0)),
               ("P3", box(X0, Y0 - 40, X0 + 40, Y0 - 20))]
    small_low = Rule("SMALL_LOW", "BUILDING", Effect.ABSTAIN,
                     {"all": [{"feature": "area_m2", "op": "<", "value": 30},
                              {"feature": "height_median_m", "op": "<", "value": 3.5}]})
    pipe = GeoPipeline(KnowledgeVersion(number=3, rules=(small_low,)))
    out = pipe.run(RasterSources(survey["dsm"], survey["dtm"], survey["ortho"]), parcels=parcels)
    by_parcel = {r.candidate.meta["parcel_id"]: r for r in out.results if r.candidate.geometry.intersects(HOUSE)}
    house = by_parcel["P1"]
    assert house.decision is Decision.ACCEPTED and house.candidate.features["parcel_share"] == 1.0
    annex = nearest([r.candidate for r in out.results], ANNEX)
    annex_r = next(r for r in out.results if r.candidate is annex)
    assert annex_r.decision is Decision.REVIEW and annex_r.fired[0].code == "SMALL_LOW"
    assert out.counts() == {"ACCEPTED": 1, "REVIEW": 1, "REJECTED": 2}
    assert out.provenance["knowledge"]["version"] == 3

    gpkg = tmp_path / "predictions.gpkg"
    assert write_results(gpkg, out.results, out.crs, extra=["parcel_id"]) == 4
    back = read_features(gpkg)
    assert {p["decision"] for _, _, p in back} == {"ACCEPTED", "REVIEW", "REJECTED"}
    assert json.loads(back[0][2]["explanation"])["knowledge"]["version"] == 3


def test_iou_measure_and_grid():
    a, b = box(0, 0, 10, 10), box(0, 0, 10, 5)
    assert iou(a, b) == pytest.approx(0.5) and iou(a, box(20, 20, 21, 21)) == 0
    assert measure(a) == 100
    from shapely.geometry import LineString
    fence = LineString([(0, 0), (10, 0)])
    assert measure(fence) == 10 and iou(fence, LineString([(0, 0.1), (10, 0.1)])) > 0.7
    assert utm_epsg(-4.0, 5.3) == 32630 and utm_epsg(-4.0, -5.3) == 32730
    k = grid_key(box(X0 + 1, Y0 - 2, X0 + 3, Y0 - 1), "EPSG:32630")
    assert k == "32630:2500:5000"
    with pytest.raises(ValueError, match="not projected"):
        require_metric("EPSG:4326")


def test_cli_geo_detect(survey, tmp_path, capsys):
    from eade.cli import main

    out = tmp_path / "out.geojson"
    prov = tmp_path / "prov.json"
    assert main(["geo", "detect", "--dsm", str(survey["dsm"]), "--dtm", str(survey["dtm"]),
                 "--ortho", str(survey["ortho"]), "-o", str(out), "--provenance", str(prov)]) == 0
    assert "4 objects" in capsys.readouterr().out
    assert len(read_features(out)) == 4
    assert json.loads(prov.read_text(encoding="utf-8"))["detector"]["name"] == "eade-geo-height"
    assert main(["geo", "catalog"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == len(GEO_CATALOG)
