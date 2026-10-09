"""Raster sources: elevation models and orthophoto read on one common grid.

The surface model (DSM) is the reference grid when present, else the
orthophoto. Other rasters are warped on the fly onto that grid, so sources with
different resolutions or CRSs can be combined. Rasters are always read by
window: a gigapixel orthophoto is never loaded whole.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
from scipy import ndimage

from .backend import Affine, Dataset, Window, open_raster, window_from_bounds, window_transform
from .crs import require_metric

GROUND_WINDOW_M = 30.0  # without a terrain model, ground is estimated over this distance


@dataclass(frozen=True)
class RasterSources:
    dsm: str | Path | None = None
    dtm: str | Path | None = None
    ortho: str | Path | None = None

    def __post_init__(self) -> None:
        if self.dsm is None and self.ortho is None:
            raise ValueError("a surface model (DSM) or an orthophoto is required")

    def describe(self) -> dict[str, str | None]:
        return {k: None if v is None else str(v) for k, v in
                (("dsm", self.dsm), ("dtm", self.dtm), ("ortho", self.ortho))}

    def open(self) -> "OpenSources":
        return OpenSources(self)


@dataclass
class Patch:
    """Aligned arrays over one window of the reference grid."""

    transform: Affine
    crs: object
    resolution: float
    dsm: np.ndarray | None        # float32, NaN where no data
    ndsm: np.ndarray | None       # height above ground
    rgb: np.ndarray | None        # (3, H, W) float32 0-255, NaN where no data
    inside_raster: np.ndarray     # False beyond the reference raster extent

    @property
    def shape(self) -> tuple[int, int]:
        return self.inside_raster.shape

    def bounds(self) -> tuple[float, float, float, float]:
        h, w = self.shape
        x0, y0 = self.transform @ (0, 0)
        x1, y1 = self.transform @ (w, h)
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


class OpenSources:
    """Open datasets, used as a context manager."""

    def __init__(self, sources: RasterSources):
        self.sources = sources
        self.dsm: Dataset | None = None
        self.dtm: Dataset | None = None
        self.ortho: Dataset | None = None

    def __enter__(self) -> "OpenSources":
        s = self.sources
        try:
            self.dsm = open_raster(s.dsm) if s.dsm else None
            self.dtm = open_raster(s.dtm) if s.dtm else None
            self.ortho = open_raster(s.ortho) if s.ortho else None
            require_metric(self.reference.crs)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc) -> None:
        for ds in (self.dsm, self.dtm, self.ortho):
            if ds is not None:
                ds.close()

    @property
    def reference(self) -> Dataset:
        return self.dsm if self.dsm is not None else self.ortho

    @property
    def crs(self):
        return self.reference.crs

    @property
    def resolution(self) -> float:
        return self.reference.transform.resolution

    def full_bounds(self) -> tuple[float, float, float, float]:
        return self.reference.bounds()

    # -------------------------------------------------------------- reading

    def window_for(self, bounds: tuple[float, float, float, float], pad_m: float = 0.0) -> Window:
        x0, y0, x1, y1 = bounds
        return window_from_bounds((x0 - pad_m, y0 - pad_m, x1 + pad_m, y1 + pad_m), self.reference.transform)

    def read(self, window: Window, ground_m: float = GROUND_WINDOW_M) -> Patch:
        ref = self.reference
        transform = window_transform(ref.transform, window)
        h, w = window.height, window.width
        rows = np.arange(window.row_off, window.row_off + h)
        cols = np.arange(window.col_off, window.col_off + w)
        inside = ((rows >= 0) & (rows < ref.height))[:, None] & ((cols >= 0) & (cols < ref.width))[None, :]

        def on_grid(ds: Dataset, band: int, resampling: str = "bilinear") -> np.ndarray:
            if ds is ref:
                return ds.read(band, window)
            return ds.warp(band, transform, ref.crs, (h, w), resampling)

        dsm = ndsm = rgb = None
        if self.dsm is not None:
            dsm = on_grid(self.dsm, 1)
            dtm = on_grid(self.dtm, 1) if self.dtm is not None else estimate_ground(dsm, self.resolution, ground_m)
            ndsm = dsm - dtm
        if self.ortho is not None:
            rgb = np.stack([on_grid(self.ortho, b) for b in (1, 2, 3)])
            if self.ortho.count >= 4:  # alpha band: transparent pixels carry no colour
                alpha = on_grid(self.ortho, 4, "nearest")
                rgb[:, ~(alpha > 0)] = np.nan
        return Patch(transform, ref.crs, self.resolution, dsm, ndsm, rgb, inside)

    def tiles(self, bounds: tuple[float, float, float, float] | None = None,
              tile_m: float = 200.0, overlap_m: float = 20.0) -> Iterator[tuple[Window, tuple[float, float, float, float]]]:
        """Read windows covering `bounds`, with their non-overlapping core.

        An object is kept by the tile whose core holds its centroid, so objects
        across tile edges are detected whole and exactly once.
        """
        x0, y0, x1, y1 = bounds or self.full_bounds()
        fb = self.full_bounds()
        x0, y0, x1, y1 = max(x0, fb[0]), max(y0, fb[1]), min(x1, fb[2]), min(y1, fb[3])
        if x0 >= x1 or y0 >= y1:
            return
        nx, ny = math.ceil((x1 - x0) / tile_m), math.ceil((y1 - y0) / tile_m)
        for j in range(ny):
            for i in range(nx):
                core = (x0 + i * tile_m, y0 + j * tile_m,
                        min(x1, x0 + (i + 1) * tile_m), min(y1, y0 + (j + 1) * tile_m))
                yield self.window_for(core, overlap_m), core


def estimate_ground(dsm: np.ndarray, resolution: float, window_m: float = GROUND_WINDOW_M) -> np.ndarray:
    """Terrain estimate from the surface model alone: a morphological opening at ~1 m."""
    factor = max(1, int(round(1.0 / resolution)))
    h, w = dsm.shape
    ph, pw = -h % factor, -w % factor
    filled = np.where(np.isnan(dsm), np.nanmax(dsm) if np.isfinite(dsm).any() else 0.0, dsm)
    padded = np.pad(filled, ((0, ph), (0, pw)), mode="edge")
    coarse = padded.reshape(padded.shape[0] // factor, factor, padded.shape[1] // factor, factor).min(axis=(1, 3))
    size = max(3, int(math.ceil(window_m / (resolution * factor))) | 1)
    ground = ndimage.grey_opening(coarse, size=(size, size))
    ground = ndimage.uniform_filter(ground, size=max(3, size // 3))
    up = np.repeat(np.repeat(ground, factor, axis=0), factor, axis=1)[:h, :w]
    return up.astype("float32")
