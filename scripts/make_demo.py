"""Write a small demo survey to try EADE in QGIS or on the command line.

    python scripts/make_demo.py [folder]      (default: dist/demo)

Creates dsm.tif, dtm.tif, ortho.tif (40 m x 40 m at 10 cm, UTM 30N), a parcel
layer parcels.gpkg and an empty project demo.eade.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from shapely.affinity import translate  # noqa: E402
from shapely.geometry import box  # noqa: E402

from synthetic import ANNEX, HOUSE, N, X0, Y0, _grid, _inside, make_survey, write_tif  # noqa: E402


def weather_ortho(path: Path) -> None:
    """Give the flat synthetic orthophoto some grain, cast shadows and two-sided roofs."""
    import numpy as np
    try:
        import rasterio
        with rasterio.open(path) as ds:
            rgb = ds.read().astype("float32")
    except ImportError:
        from osgeo import gdal
        rgb = gdal.Open(str(path)).ReadAsArray().astype("float32")
    rng = np.random.default_rng(7)
    X, Y = _grid()
    roofs = np.zeros((N, N), bool)
    for b in (HOUSE, ANNEX):
        roofs |= _inside(b, X, Y)
        shadow = _inside(translate(b, 1.2, -1.2), X, Y)  # cast 1.2 m to the south-east
        rgb[:, shadow & ~roofs] *= 0.55
        x0, y0, x1, y1 = b.bounds
        ridge = (Y > (y0 + y1) / 2) & _inside(b, X, Y)
        rgb[:, ridge] *= 1.12
    rgb += rng.normal(0, 9, rgb.shape)
    rgb += rng.normal(0, 6, (1, N, N))
    write_tif(path, np.clip(rgb, 0, 255).astype("uint8"))


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    make_survey(out)
    weather_ortho(out / "ortho.tif")

    import numpy as np
    import pyogrio
    import shapely
    parcels = [box(X0, Y0 - 20, X0 + 20, Y0), box(X0 + 20, Y0 - 20, X0 + 40, Y0), box(X0, Y0 - 40, X0 + 40, Y0 - 20)]
    gpkg = out / "parcels.gpkg"
    gpkg.unlink(missing_ok=True)
    pyogrio.raw.write(str(gpkg), np.array([shapely.to_wkb(p) for p in parcels], dtype=object),
                      [np.array(["HT/101/1", "HT/101/2", "HT/102/1"], dtype=object)], ["PARCELLE"],
                      crs="EPSG:32630", driver="GPKG", geometry_type="Polygon")

    from eade.store import Workspace
    project = out / "demo.eade"
    if not project.exists():
        Workspace.create(project).close()
    print(f"demo written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
