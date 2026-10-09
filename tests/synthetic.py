"""A synthetic drone survey: 40 m x 40 m at 10 cm, UTM 30N (EPSG:32630).

Scene (heights above a flat 100 m ground):
  house   8 x 6 m, 4 m high, grey roof
  annex   5 x 5 m, 3 m high, grey roof
  tree    disc of radius 2.5 m, 5 m high, green, bumpy canopy
  car     2 x 1.5 m, 1.5 m high, red
"""

import numpy as np
from pyproj import CRS
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

    paths = {"dsm": d / "dsm.tif", "dtm": d / "dtm.tif", "ortho": d / "ortho.tif"}
    write_tif(paths["dsm"], dsm[None].astype("float32"), nodata=-9999)
    write_tif(paths["dtm"], dtm[None].astype("float32"), nodata=-9999)
    write_tif(paths["ortho"], rgb)
    return paths


def write_tif(path, bands, nodata=None):
    """A north-up GeoTIFF in EPSG:32630, with rasterio or else GDAL's own bindings."""
    count, h, w = bands.shape
    try:
        import rasterio
        from rasterio.transform import from_origin
        with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=count, dtype=bands.dtype.name,
                           crs="EPSG:32630", transform=from_origin(X0, Y0, RES, RES), nodata=nodata) as ds:
            ds.write(bands)
    except ImportError:
        from osgeo import gdal
        gdal.UseExceptions()
        types = {"float32": gdal.GDT_Float32, "uint8": gdal.GDT_Byte}
        ds = gdal.GetDriverByName("GTiff").Create(str(path), w, h, count, types[bands.dtype.name])
        ds.SetGeoTransform((X0, RES, 0.0, Y0, 0.0, -RES))
        ds.SetProjection(CRS.from_epsg(32630).to_wkt())
        for i in range(count):
            b = ds.GetRasterBand(i + 1)
            if nodata is not None:
                b.SetNoDataValue(nodata)
            b.WriteArray(bands[i])
        ds = None
