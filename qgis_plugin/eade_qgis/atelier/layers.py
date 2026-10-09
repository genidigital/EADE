"""Map layers of the workshop: the campaign's predictions and the operator's outlines."""

from __future__ import annotations

from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsFillSymbol, QgsProject, QgsRuleBasedRenderer,
                       QgsVectorLayer)

from ..compat import field, to_qgs

PRED_FIELDS = [("pid", "int"), ("decision", "string"), ("status", "string"), ("final_cls", "string"),
               ("score", "double"), ("parcel_id", "string"), ("measure", "double")]

# outline colours follow the guide: proposed orange, rejected dashed grey, corrected green, removed red
STYLE = [
    ("Corrigé ou validé", "\"status\" IN ('IN_CORRECTION', 'VALIDATED')",
     {"color": "47,158,68,60", "outline_color": "47,158,68,255", "outline_width": "0.6"}),
    ("Retiré", "\"status\" = 'REJECTED'",
     {"color": "224,49,49,40", "outline_color": "224,49,49,255", "outline_width": "0.6"}),
    ("En revue", "\"decision\" = 'REVIEW'",
     {"color": "242,194,48,70", "outline_color": "230,150,0,255", "outline_width": "0.7"}),
    ("Retenu", "\"decision\" = 'ACCEPTED'",
     {"color": "240,124,30,80", "outline_color": "240,124,30,255", "outline_width": "0.5"}),
    ("Écarté", "\"decision\" = 'REJECTED'",
     {"color": "0,0,0,0", "outline_color": "120,130,145,255", "outline_width": "0.4", "outline_style": "dash"}),
]


def predictions_layer(name: str, crs_wkt: str, predictions: list[dict]) -> QgsVectorLayer:
    layer = QgsVectorLayer("MultiPolygon", name, "memory")
    layer.setCrs(QgsCoordinateReferenceSystem.fromWkt(crs_wkt))
    dp = layer.dataProvider()
    dp.addAttributes([field(n, k) for n, k in PRED_FIELDS])
    layer.updateFields()
    feats = []
    for p in predictions:
        f = QgsFeature(layer.fields())
        g = to_qgs(p["geometry"])
        g.convertToMultiType()
        f.setGeometry(g)
        f.setAttributes([p["id"], p["decision"], p["status"], p["final_class"], p["score"],
                         p["parcel_id"], p["measure"]])
        feats.append(f)
    dp.addFeatures(feats)
    layer.updateExtents()
    root = QgsRuleBasedRenderer.Rule(None)
    for label, expr, props in STYLE:
        root.appendChild(QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple(props), 0, 0, expr, label))
    # first matching rule only, so a corrected object is not also drawn as proposed
    _first_match_only(root)
    layer.setRenderer(QgsRuleBasedRenderer(root))
    return layer


def _first_match_only(root) -> None:
    """Make every rule exclusive of the previous ones (ELSE chaining)."""
    previous = []
    for child in root.children():
        expr = child.filterExpression()
        if previous:
            child.setFilterExpression(f"({expr}) AND NOT ({' OR '.join(previous)})")
        previous.append(f"({expr})")


def outlines_layer(crs_wkt: str) -> QgsVectorLayer:
    layer = QgsVectorLayer("Polygon", "EADE – tracés", "memory")
    layer.setCrs(QgsCoordinateReferenceSystem.fromWkt(crs_wkt))
    layer.renderer().setSymbol(QgsFillSymbol.createSimple({"color": "18,182,216,60",
                                                           "outline_color": "18,182,216,255",
                                                           "outline_width": "0.8"}))
    return layer


def set_status(layer: QgsVectorLayer, prediction_ids: set[int], status: str) -> None:
    idx = layer.fields().indexOf("status")
    changes = {f.id(): {idx: status} for f in layer.getFeatures() if f["pid"] in prediction_ids}
    if changes:
        layer.dataProvider().changeAttributeValues(changes)
        layer.triggerRepaint()


def add_to_project(layer: QgsVectorLayer) -> None:
    QgsProject.instance().addMapLayer(layer)
