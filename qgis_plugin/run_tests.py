"""Run the plugin tests inside QGIS's own Python.

    <QGIS>/bin/python-qgis.bat qgis_plugin/run_tests.py [pytest args]

pytest only has to be importable (for example installed with
`pip install --target <dir> pytest` and that directory passed in EADE_TEST_SITE).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["EADE_SRC"] = os.path.join(ROOT, "src")

paths = [HERE, os.path.join(ROOT, "src"), os.path.join(ROOT, "tests"), os.environ.get("EADE_TEST_SITE", "")]
prefix = os.environ.get("QGIS_PREFIX_PATH") or os.path.join(os.path.dirname(os.path.dirname(sys.executable)),
                                                            "apps", "qgis")
paths.append(os.path.join(prefix, "python", "plugins"))
sys.path[:0] = [p for p in paths if p]
sys.dont_write_bytecode = True

import pytest  # noqa: E402

sys.exit(pytest.main([os.path.join(HERE, "tests"), "-q", "-p", "no:cacheprovider", "-p", "no:warnings",
                      *sys.argv[1:]]))
