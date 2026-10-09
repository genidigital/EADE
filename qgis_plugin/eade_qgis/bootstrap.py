"""Make the EADE engine importable inside QGIS.

The released plugin carries a copy of the `eade` package in `ext/`, so nothing
has to be installed in QGIS's Python. During development the engine can come
from a source tree (EADE_SRC) or from an installed package.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def ensure_eade():
    candidates = [os.path.join(HERE, "ext"), os.environ.get("EADE_SRC", "")]
    for path in candidates:
        if path and os.path.isdir(os.path.join(path, "eade")) and path not in sys.path:
            sys.path.insert(0, path)
            break
    import eade
    return eade
