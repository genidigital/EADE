"""Write a small demo survey to try EADE in QGIS or on the command line.

    python scripts/make_demo.py [folder]      (default: dist/demo)

Creates dsm.tif, dtm.tif, ortho.tif (40 m x 40 m at 10 cm, UTM 30N), a parcel
layer parcels.gpkg and an empty project demo.eade.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from shapely.geometry import box  # noqa: E402

from synthetic import X0, Y0, make_survey  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    make_survey(out)

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
