"""Build the installable QGIS plugin zip, with the EADE engine embedded.

    python scripts/build_qgis_plugin.py            -> dist/eade_qgis-<version>.zip
    python scripts/build_qgis_plugin.py --install  -> also copy it into the QGIS profile

The zip installs from QGIS > Plugins > Manage and Install Plugins > Install from ZIP.
"""

from __future__ import annotations

import argparse
import configparser
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "qgis_plugin" / "eade_qgis"
ENGINE = ROOT / "src" / "eade"
SKIP = {"__pycache__", ".pytest_cache"}


def files(base: Path):
    for p in sorted(base.rglob("*")):
        if p.is_file() and not SKIP.intersection(p.parts) and p.suffix not in (".pyc", ".pyo"):
            yield p


def version() -> str:
    cfg = configparser.ConfigParser()
    cfg.read(PLUGIN / "metadata.txt", encoding="utf-8")
    return cfg["general"]["version"]


def build(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"eade_qgis-{version()}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files(PLUGIN):
            z.write(p, Path("eade_qgis") / p.relative_to(PLUGIN))
        for p in files(ENGINE):
            z.write(p, Path("eade_qgis") / "ext" / "eade" / p.relative_to(ENGINE))
        z.write(ROOT / "README.md", "eade_qgis/README.md")
    return target


def profile_plugins_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / ".local" / "share")) / "QGIS"
    for qgis in ("QGIS4", "QGIS3"):
        d = base / qgis / "profiles" / "default"
        if d.is_dir():
            return d / "python" / "plugins"
    raise SystemExit("no QGIS profile found")


def install(zip_path: Path) -> Path:
    dest = profile_plugins_dir()
    dest.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(dest / "eade_qgis", ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)
    return dest / "eade_qgis"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--install", action="store_true", help="install into the default QGIS profile")
    args = ap.parse_args(argv)
    z = build(Path(args.out))
    print(f"built {z} ({z.stat().st_size // 1024} KB)")
    if args.install:
        print(f"installed in {install(z)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
