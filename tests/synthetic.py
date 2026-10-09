"""A synthetic drone survey: 40 m x 40 m at 10 cm, UTM 30N (EPSG:32630).

Scene (heights above a flat 100 m ground):
  house   8 x 6 m, 4 m high, grey roof
  annex   5 x 5 m, 3 m high, grey roof
  tree    disc of radius 2.5 m, 5 m high, green, bumpy canopy
  car     2 x 1.5 m, 1.5 m high, red
"""

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

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


def make_survey(d):
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


