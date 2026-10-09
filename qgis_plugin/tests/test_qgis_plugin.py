"""The plugin inside a real, headless QGIS. Run with qgis_plugin/run_tests.py."""


import pytest

from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.testing import start_app

APP = start_app()

import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402

Processing.initialize()

from eade_qgis.plugin import EadePlugin  # noqa: E402
from synthetic import ANNEX, HOUSE, X0, Y0, make_survey  # noqa: E402

PLUGIN = EadePlugin(None)
PLUGIN.initProcessing()


@pytest.fixture(scope="module")
def survey(tmp_path_factory):
    return make_survey(tmp_path_factory.mktemp("survey"))


def polygons(name, geoms):
    lyr = QgsVectorLayer("Polygon?crs=EPSG:32630&field=name:string", name, "memory")
    feats = []
    for i, g in enumerate(geoms):
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromWkt(g.wkt))
        f.setAttributes([f"{name}{i}"])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


def test_provider_lists_the_algorithms():
    ids = {a.id() for a in QgsApplication.processingRegistry().providerById("eade").algorithms()}
    assert ids == {"eade:detect", "eade:measure", "eade:evaluate", "eade:campaign"}


def test_detect_with_parcels(survey):
    parcels = polygons("P", [HOUSE.buffer(3), ANNEX.buffer(3)])
    out = processing.run("eade:detect", {"DSM": str(survey["dsm"]), "DTM": str(survey["dtm"]),
                                         "ORTHO": str(survey["ortho"]), "PARCELS": parcels, "PARCEL_ID": "name",
                                         "OUTPUT": "memory:"})
    layer = out["OUTPUT"]
    assert layer.featureCount() == 4 and (out["ACCEPTED"], out["REJECTED"]) == (2, 2)
    by_parcel = {f["parcel_id"]: f for f in layer.getFeatures() if f["parcel_id"]}
    assert by_parcel["P0"]["decision"] == "ACCEPTED" and abs(by_parcel["P0"]["measure"] - 48) < 3


def test_measure_and_evaluate(survey):
    drawn = polygons("D", [HOUSE])
    out = processing.run("eade:measure", {"INPUT": drawn, "DSM": str(survey["dsm"]), "DTM": str(survey["dtm"]),
                                          "ORTHO": str(survey["ortho"]), "OUTPUT": "memory:"})
    f = next(out["OUTPUT"].getFeatures())
    assert abs(f["height_median_m"] - 4.0) < 0.15 and f["name"] == "D0"

    det = processing.run("eade:detect", {"DSM": str(survey["dsm"]), "DTM": str(survey["dtm"]),
                                         "ORTHO": str(survey["ortho"]), "OUTPUT": "memory:"})["OUTPUT"]
    ev = processing.run("eade:evaluate", {"PREDICTIONS": det, "DECISION_FIELD": "decision",
                                          "REFERENCES": polygons("R", [HOUSE, ANNEX]), "CLASS": "BUILDING",
                                          "MATCH_IOU": 0.5})
    assert ev["PRECISION"] == 1.0 and ev["RECALL"] == 1.0 and ev["MEAN_IOU"] > 0.85


def test_campaign_then_workshop(survey, tmp_path):
    from qgis.testing.mocked import get_iface
    from eade.store import Workspace

    path = str(tmp_path / "songon.eade")
    Workspace.create(path).close()
    out = processing.run("eade:campaign", {"WORKSPACE": path, "LABEL": "Lot 1", "DSM": str(survey["dsm"]),
                                           "DTM": str(survey["dtm"]), "ORTHO": str(survey["ortho"]),
                                           "OUTPUT": "memory:"})
    assert out["CAMPAIGN"] == 1 and out["OUTPUT"].featureCount() == 4

    from eade_qgis.atelier.dock import AtelierDock
    iface = get_iface()
    dock = AtelierDock(iface)
    dock.file.setFilePath(path)
    assert dock.campaigns.count() == 1 and dock.pred_layer.featureCount() == 4
    assert dock.queue.count() == 2  # the two accepted objects; rejected ones are not queued
    dock.queue.setCurrentRow(0)
    assert dock.objects.count() == 1 and "Prédiction" in dock.detail.toPlainText()
    dock.act("ACCEPT")
    dock.queue.setCurrentRow(1)
    dock.reason.setCurrentIndex(0)
    dock.act("REJECT")
    dock.submit()
    dock.queue.setCurrentRow(0)
    dock.submit()
    dock.refresh_validation()
    assert dock.pending.count() == 2
    dock.pending.selectAll()
    dock.justification.setText("vérifié sur l'orthophoto")
    dock.review(True)
    ws = Workspace(path)
    assert len(ws.corrections(1, "VALIDATED")) == 2
    ws.close()
    dock.close()
    for lid in list(QgsProject.instance().mapLayers()):
        QgsProject.instance().removeMapLayer(lid)


def test_campaign_cancel_stops_between_tiles(survey, tmp_path):
    from qgis.core import QgsProcessingContext, QgsProcessingFeedback
    from eade.store import Workspace

    class CancelAfterFirstTile(QgsProcessingFeedback):
        def setProgress(self, value):
            super().setProgress(value)
            if value > 0:
                self.cancel()

    path = str(tmp_path / "cancel.eade")
    alg = QgsApplication.processingRegistry().createAlgorithmById("eade:campaign")
    params = {"WORKSPACE": path, "LABEL": "x", "DSM": str(survey["dsm"]), "DTM": str(survey["dtm"]),
              "OUTPUT": "memory:"}
    # 10 m tiles: the 40 m survey makes 16 tiles, so cancelling after the first one leaves most undone
    from eade.geo.detect import DetectorParams, HeightDetector
    defaults = HeightDetector.__init__.__defaults__
    HeightDetector.__init__.__defaults__ = (DetectorParams(tile_m=10.0, overlap_m=8.0), None)
    try:
        processing.run(alg, params, feedback=CancelAfterFirstTile(), context=QgsProcessingContext())
    finally:
        HeightDetector.__init__.__defaults__ = defaults
    ws = Workspace(path)
    c = ws.campaign(1)
    ws.close()
    assert c["status"] == "CANCELLED" and c["tiles_done"] < c["tiles_total"]
