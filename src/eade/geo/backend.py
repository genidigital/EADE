"""Raster backends: rasterio when installed, otherwise GDAL's own Python bindings.

A pip installation brings rasterio; QGIS and ArcGIS Pro ship GDAL bindings
(osgeo) but not rasterio, and installing a second GDAL into them invites DLL
conflicts. EADE Geo therefore talks to rasters through this small interface
and picks whichever library the host already has.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np
import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

BACKEND_ENV = "EADE_RASTER_BACKEND"  # force "rasterio" or "gdal"


# ----------------------------------------------------------------- affine

@dataclass(frozen=True)
class Affine:
    """Pixel (col, row) to map (x, y): x = a*col + b*row + c ; y = d*col + e*row + f."""

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @classmethod
    def from_gdal(cls, gt: tuple[float, ...]) -> "Affine":
        return cls(gt[1], gt[2], gt[0], gt[4], gt[5], gt[3])

    def to_gdal(self) -> tuple[float, ...]:
        return (self.c, self.a, self.b, self.f, self.d, self.e)

    @classmethod
    def translation(cls, x: float, y: float) -> "Affine":
        return cls(1.0, 0.0, x, 0.0, 1.0, y)

    def __matmul__(self, other):
        if isinstance(other, Affine):
            o = other
            return Affine(self.a * o.a + self.b * o.d, self.a * o.b + self.b * o.e, self.a * o.c + self.b * o.f + self.c,
                          self.d * o.a + self.e * o.d, self.d * o.b + self.e * o.e, self.d * o.c + self.e * o.f + self.f)
        x, y = other
        return (self.a * x + self.b * y + self.c, self.d * x + self.e * y + self.f)

    def __invert__(self) -> "Affine":
        det = self.a * self.e - self.b * self.d
        if det == 0:
            raise ValueError("transform is not invertible")
        ia, ib, id_, ie = self.e / det, -self.b / det, -self.d / det, self.a / det
        return Affine(ia, ib, -ia * self.c - ib * self.f, id_, ie, -id_ * self.c - ie * self.f)

    @property
    def resolution(self) -> float:
        return abs(self.a)


@dataclass(frozen=True)
class Window:
    col_off: int
    row_off: int
    width: int
    height: int


def window_from_bounds(bounds: tuple[float, float, float, float], transform: Affine) -> Window:
    """The pixel window covering map bounds (north-up rasters)."""
    inv = ~transform
    x0, y0, x1, y1 = bounds
    cols, rows = zip(*(inv @ p for p in ((x0, y0), (x1, y1), (x0, y1), (x1, y0))))
    c0, r0 = math.floor(min(cols) + 1e-9), math.floor(min(rows) + 1e-9)
    c1, r1 = math.ceil(max(cols) - 1e-9), math.ceil(max(rows) - 1e-9)
    return Window(c0, r0, max(1, c1 - c0), max(1, r1 - r0))


def window_transform(transform: Affine, w: Window) -> Affine:
    x, y = transform @ (w.col_off, w.row_off)
    return Affine(transform.a, transform.b, x, transform.d, transform.e, y)


# --------------------------------------------------------------- datasets

class Dataset:
    """What EADE Geo needs from a raster."""

    crs: CRS
    transform: Affine
    width: int
    height: int
    count: int
    nodata: float | None

    def bounds(self) -> tuple[float, float, float, float]:
        x0, y0 = self.transform @ (0, 0)
        x1, y1 = self.transform @ (self.width, self.height)
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def read(self, band: int, window: Window) -> np.ndarray:
        """float32 array of the window, NaN outside the raster and on no-data."""
        raise NotImplementedError

    def warp(self, band: int, transform: Affine, crs: CRS, shape: tuple[int, int],
             resampling: str = "bilinear") -> np.ndarray:
        """This band resampled onto another grid, NaN where there is no data."""
        raise NotImplementedError

    def close(self) -> None:
        pass


def _paste(window: Window, width: int, height: int, reader) -> np.ndarray:
    out = np.full((window.height, window.width), np.nan, dtype="float32")
    c0, r0 = max(0, window.col_off), max(0, window.row_off)
    c1, r1 = min(width, window.col_off + window.width), min(height, window.row_off + window.height)
    if c0 < c1 and r0 < r1:
        out[r0 - window.row_off:r1 - window.row_off, c0 - window.col_off:c1 - window.col_off] = \
            reader(c0, r0, c1 - c0, r1 - r0)
    return out


class _RasterioDataset(Dataset):
    def __init__(self, path: str):
        import rasterio
        self._ds = rasterio.open(path)
        self.crs = CRS.from_wkt(self._ds.crs.to_wkt())
        t = self._ds.transform
        self.transform = Affine(t.a, t.b, t.c, t.d, t.e, t.f)
        self.width, self.height, self.count, self.nodata = self._ds.width, self._ds.height, self._ds.count, self._ds.nodata

    def read(self, band: int, window: Window) -> np.ndarray:
        from rasterio.windows import Window as RW

        def reader(c, r, w, h):
            a = self._ds.read(band, window=RW(c, r, w, h), masked=True)
            return np.ma.filled(a.astype("float32"), np.nan)
        return _paste(window, self.width, self.height, reader)

    def warp(self, band, transform, crs, shape, resampling="bilinear"):
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.transform import Affine as RA
        from rasterio.warp import reproject
        out = np.full(shape, np.nan, dtype="float32")
        reproject(source=rasterio.band(self._ds, band), destination=out, src_nodata=self.nodata,
                  dst_transform=RA(transform.a, transform.b, transform.c, transform.d, transform.e, transform.f),
                  dst_crs=crs.to_wkt(), dst_nodata=np.nan, resampling=getattr(Resampling, resampling))
        return out

    def close(self) -> None:
        self._ds.close()


class _GdalDataset(Dataset):
    def __init__(self, path: str):
        from osgeo import gdal
        gdal.UseExceptions()
        self._gdal = gdal
        self._ds = gdal.Open(str(path), gdal.GA_ReadOnly)
        if self._ds is None:
            raise OSError(f"cannot open {path}")
        self.crs = CRS.from_wkt(self._ds.GetProjection())
        self.transform = Affine.from_gdal(self._ds.GetGeoTransform())
        self.width, self.height, self.count = self._ds.RasterXSize, self._ds.RasterYSize, self._ds.RasterCount
        self.nodata = self._ds.GetRasterBand(1).GetNoDataValue()

    def read(self, band: int, window: Window) -> np.ndarray:
        b = self._ds.GetRasterBand(band)
        nodata = b.GetNoDataValue()

        def reader(c, r, w, h):
            a = b.ReadAsArray(c, r, w, h).astype("float32")
            if nodata is not None:
                a[a == np.float32(nodata)] = np.nan
            return a
        return _paste(window, self.width, self.height, reader)

    def warp(self, band, transform, crs, shape, resampling="bilinear"):
        gdal = self._gdal
        h, w = shape
        mem = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Float32)
        mem.SetGeoTransform(transform.to_gdal())
        mem.SetProjection(crs.to_wkt())
        mb = mem.GetRasterBand(1)
        mb.SetNoDataValue(float("nan"))
        mb.Fill(float("nan"))
        src = gdal.Translate("", self._ds, format="VRT", bandList=[band])
        gdal.Warp(mem, src, resampleAlg=resampling, srcNodata=self.nodata, dstNodata=float("nan"))
        out = mb.ReadAsArray().astype("float32")
        mem = src = None
        return out

    def close(self) -> None:
        self._ds = None


def backend_name() -> str:
    forced = os.environ.get(BACKEND_ENV, "").lower()
    if forced in ("rasterio", "gdal"):
        return forced
    try:
        import rasterio  # noqa: F401
        return "rasterio"
    except ImportError:
        return "gdal"


def open_raster(path: str | os.PathLike) -> Dataset:
    return _RasterioDataset(str(path)) if backend_name() == "rasterio" else _GdalDataset(str(path))


# ------------------------------------------------------ vector <-> raster

def pixel_mask(geom: BaseGeometry, shape: tuple[int, int], transform: Affine, all_touched: bool = False) -> np.ndarray:
    """Pixels whose centre lies in the geometry (or that it touches)."""
    h, w = shape
    cols = np.arange(w) + 0.5
    rows = np.arange(h) + 0.5
    cc, rr = np.meshgrid(cols, rows)
    xs = transform.a * cc + transform.b * rr + transform.c
    ys = transform.d * cc + transform.e * rr + transform.f
    g = geom.buffer(transform.resolution * 0.7072) if all_touched else geom
    shapely.prepare(g)
    return shapely.contains_xy(g, xs, ys)


def polygonize(labels: np.ndarray, transform: Affine) -> Iterator[tuple[BaseGeometry, int]]:
    """Polygons of the connected regions of a label image (0 is background)."""
    if backend_name() == "rasterio":
        from rasterio.features import shapes
        from rasterio.transform import Affine as RA
        from shapely.geometry import shape
        t = RA(transform.a, transform.b, transform.c, transform.d, transform.e, transform.f)
        for g, v in shapes(labels.astype("int32"), mask=labels > 0, transform=t):
            yield shape(g), int(v)
        return
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    h, w = labels.shape
    mem = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Int32)
    mem.SetGeoTransform(transform.to_gdal())
    band = mem.GetRasterBand(1)
    band.WriteArray(labels.astype("int32"))
    band.SetNoDataValue(0)
    vds = ogr.GetDriverByName("Memory").CreateDataSource("")
    layer = vds.CreateLayer("p", geom_type=ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(band, band.GetMaskBand(), layer, 0)
    for f in layer:
        yield shapely.from_wkb(bytes(f.GetGeometryRef().ExportToWkb())), int(f.GetField(0))
    vds = mem = None


def describe() -> dict[str, Any]:
    return {"backend": backend_name()}
