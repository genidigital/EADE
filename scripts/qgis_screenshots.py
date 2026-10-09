"""Capture the plugin's screens for the QGIS operations guide.

    <QGIS>/bin/python-qgis.bat scripts/qgis_screenshots.py OUT_DIR

Runs a real QGIS without a visible window on the demo survey (scripts/make_demo.py),
runs a campaign, opens the workshop and records each step as a PNG.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "build" / "qgis_shots")
OUT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":  # the offscreen platform finds no font by itself
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
os.environ["EADE_SRC"] = str(ROOT / "src")
prefix = Path(sys.executable).parent.parent / "apps" / "qgis"
sys.path[:0] = [str(ROOT / "qgis_plugin"), str(ROOT / "src"), str(ROOT / "tests"), str(prefix / "python" / "plugins")]
sys.dont_write_bytecode = True

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsFillSymbol, QgsMapRendererParallelJob,  # noqa: E402
                       QgsMapSettings, QgsPalLayerSettings, QgsProject, QgsRasterLayer, QgsRectangle, QgsTextFormat,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFont  # noqa: E402
from qgis.testing import start_app  # noqa: E402

start_app()
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402

Processing.initialize()
from eade_qgis.plugin import EadePlugin  # noqa: E402

plugin = EadePlugin(None)
plugin.initProcessing()

from eade.store import Workspace  # noqa: E402
from shapely.geometry import box  # noqa: E402
from synthetic import X0, Y0  # noqa: E402

demo = Path(tempfile.mkdtemp()) / "demo"
shutil.copytree(ROOT / "dist" / "demo", demo)
for f in demo.glob("*.eade*"):
    f.unlink()
project_file = str(demo / "songon.eade")
Workspace.create(project_file).close()
ws = Workspace(project_file)
ws.update_settings(__import__("eade.store", fromlist=["LOCAL"]).LOCAL, "Démonstration", enabled=True, mode="COLLECT")
ws.close()

ortho = QgsRasterLayer(str(demo / "ortho.tif"), "Orthophoto")
parcels = QgsVectorLayer(str(demo / "parcels.gpkg"), "Parcelles", "ogr")
parcels.renderer().setSymbol(QgsFillSymbol.createSimple(
    {"color": "0,0,0,0", "outline_color": "242,194,48,255", "outline_width": "0.7"}))
pal = QgsPalLayerSettings()
pal.fieldName = "PARCELLE"
fmt = QgsTextFormat()
fmt.setFont(QFont("Segoe UI", 9))
fmt.setColor(QColor("#fff7d6"))
fmt.setSize(9)
pal.setFormat(fmt)
parcels.setLabeling(QgsVectorLayerSimpleLabeling(pal))
parcels.setLabelsEnabled(True)
QgsProject.instance().addMapLayers([ortho, parcels])


def render(name, layers, extent=None, size=(900, 900)):
    for lyr in layers:
        if hasattr(lyr, "removeSelection"):
            lyr.removeSelection()
    ms = QgsMapSettings()
    ms.setLayers(layers)
    ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:32630"))
    ms.setOutputSize(QSize(*size))
    ms.setBackgroundColor(QColor("#e7ddc9"))
    ms.setExtent(extent or ortho.extent())
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    job.renderedImage().save(str(OUT / f"{name}.png"))


# 1. data loaded in QGIS
render("01_donnees", [parcels, ortho])

# 2. quick detection
det = processing.run("eade:detect", {"DSM": str(demo / "dsm.tif"), "DTM": str(demo / "dtm.tif"),
                                     "ORTHO": str(demo / "ortho.tif"), "PARCELS": parcels, "PARCEL_ID": "PARCELLE",
                                     "OUTPUT": "memory:"})["OUTPUT"]
from eade_qgis.atelier import layers as L  # noqa: E402
det.setRenderer(L.decision_renderer(with_corrections=False))
render("02_detection", [det, parcels, ortho])

# 3. campaign, then the workshop
out = processing.run("eade:campaign", {"WORKSPACE": project_file, "LABEL": "Section HT - lot 1",
                                       "DSM": str(demo / "dsm.tif"), "DTM": str(demo / "dtm.tif"),
                                       "ORTHO": str(demo / "ortho.tif"), "PARCELS": str(demo / "parcels.gpkg"),
                                       "PARCEL_ID": "PARCELLE", "OUTPUT": "memory:"})

from qgis.testing.mocked import get_iface  # noqa: E402
from eade_qgis.atelier.dock import AtelierDock  # noqa: E402

iface = get_iface()
import qgis.utils  # noqa: E402

from qgis.gui import QgsBrowserGuiModel  # noqa: E402

_browser = QgsBrowserGuiModel()
iface.browserModel = lambda: _browser
iface.activeLayer = lambda: None
qgis.utils.iface = iface  # processing dialogs look for the QGIS interface here
for _name, _mod in list(sys.modules.items()):  # ...and some modules copied it at import time
    if _name.startswith("processing") and getattr(_mod, "iface", 0) is None:
        _mod.iface = iface
dock = AtelierDock(iface)
dock.resize(430, 860)
dock.file.setFilePath(project_file)
dock.queue.setCurrentRow(0)
dock.show()
QgsApplication.processEvents()
dock.grab().save(str(OUT / "03_atelier_correction.png"))
render("04_carte_campagne", [dock.pred_layer, parcels, ortho])
dock.queue.setCurrentRow(0)

# 4. corrections: accept the first parcel's object, reject the second, add a missed building
dock.act("ACCEPT")
dock.queue.setCurrentRow(1)
dock.reason.setCurrentIndex(0)
dock.act("REJECT")
missed = box(X0 + 32, Y0 - 38, X0 + 37, Y0 - 34)
dock.start_drawing = lambda: None
from qgis.core import QgsFeature, QgsGeometry  # noqa: E402
f = QgsFeature(dock.draw_layer.fields())
f.setGeometry(QgsGeometry.fromWkt(missed.wkt))
dock.draw_layer.dataProvider().addFeatures([f])
render("05_trace_manquant", [dock.draw_layer, dock.pred_layer, parcels, ortho])
dock.cls.setCurrentIndex(0)
dock.act("ADD")
render("06_apres_corrections", [dock.corr_layer, dock.pred_layer, parcels, ortho])
QgsApplication.processEvents()
dock.grab().save(str(OUT / "07_atelier_apres.png"))

# 5. submit both parcels, then the expert's validation tab
while dock.queue.count():  # a submitted parcel leaves the queue
    dock.queue.setCurrentRow(0)
    dock.submit()
dock.tabs.setCurrentIndex(1)
dock.refresh_validation()
dock.pending.selectAll()
dock.justification.setText("Vérifié sur l'orthophoto")
QgsApplication.processEvents()
dock.grab().save(str(OUT / "08_atelier_validation.png"))

# 6. algorithm dialogs
try:
    for alg_id, name in (("eade:detect", "09_dialogue_detect"), ("eade:campaign", "10_dialogue_campagne"),
                         ("eade:evaluate", "11_dialogue_evaluer")):
        dlg = processing.createAlgorithmDialog(alg_id)
        dlg.resize(980, 700)
        dlg.show()
        QgsApplication.processEvents()
        dlg.grab().save(str(OUT / f"{name}.png"))
        dlg.close()
except Exception as e:  # noqa: BLE001
    print("dialogs skipped:", type(e).__name__, e)

dock.close()
print("screenshots in", OUT)
