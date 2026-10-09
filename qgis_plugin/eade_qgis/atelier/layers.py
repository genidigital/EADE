"""Map layers of the workshop: the campaign's objects, the corrections and the operator's outlines."""

from __future__ import annotations

from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsFillSymbol, QgsProject, QgsRuleBasedRenderer,
                       QgsVectorLayer)

from ..compat import field, to_qgs

PRED_FIELDS = [("pid", "int"), ("decision", "string"), ("status", "string"), ("correction", "string"),
               ("final_cls", "string"), ("score", "double"), ("parcel_id", "string"), ("measure", "double")]

# Colours follow the user guide: proposed orange, undecided yellow, dismissed dashed grey,
# corrected green, rejected or reclassified by the operator red. First matching rule wins.
# Expressions avoid NULL: with QGIS's three-valued logic one NULL would make the ELSE chain false.
STYLE = [
    ("Rejeté ou reclassé par l'opérateur", "coalesce(\"correction\", '') IN ('REJECT', 'RECLASSIFY')",
     {"color": "224,49,49,45", "outline_color": "224,49,49,255", "outline_width": "0.7"}),
    ("Corrigé ou accepté", "coalesce(\"correction\", '') <> ''",
     {"color": "47,158,68,55", "outline_color": "47,158,68,255", "outline_width": "0.7"}),
    ("En revue", "\"decision\" = 'REVIEW'",
     {"color": "242,194,48,80", "outline_color": "230,150,0,255", "outline_width": "0.8"}),
    ("Retenu", "\"decision\" = 'ACCEPTED'",
     {"color": "240,124,30,80", "outline_color": "240,124,30,255", "outline_width": "0.6"}),
    ("Écarté par le moteur", "\"decision\" = 'REJECTED'",
     {"color": "0,0,0,0", "outline_color": "200,205,215,255", "outline_width": "0.5", "outline_style": "dash"}),
]


def _memory(kind: str, name: str, crs_wkt: str, fields) -> QgsVectorLayer:
    layer = QgsVectorLayer(kind, name, "memory")
    layer.setCrs(QgsCoordinateReferenceSystem.fromWkt(crs_wkt))
    layer.dataProvider().addAttributes([field(n, k) for n, k in fields])
    layer.updateFields()
    return layer


def predictions_layer(name: str, crs_wkt: str, predictions: list[dict],
                      corrections: dict[int, str] | None = None) -> QgsVectorLayer:
    """The campaign's objects; `corrections` maps a prediction id to its current correction action."""
    corrections = corrections or {}
    layer = _memory("MultiPolygon", name, crs_wkt, PRED_FIELDS)
    feats = []
    for p in predictions:
        f = QgsFeature(layer.fields())
        g = to_qgs(p["geometry"])
        g.convertToMultiType()
        f.setGeometry(g)
        f.setAttributes([p["id"], p["decision"], p["status"], corrections.get(p["id"]), p["final_class"],
                         p["score"], p["parcel_id"], p["measure"]])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    layer.updateExtents()
    layer.setRenderer(decision_renderer())
    return layer


def decision_renderer(with_corrections: bool = True) -> QgsRuleBasedRenderer:
    """The workshop style; without corrections it also styles a plain detection output."""
    root = QgsRuleBasedRenderer.Rule(None)
    for label, expr, props in (STYLE if with_corrections else STYLE[2:]):
        root.appendChild(QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple(props), 0, 0, expr, label))
    _first_match_only(root)
    return QgsRuleBasedRenderer(root)


def corrections_layer(crs_wkt: str, corrections: list[dict]) -> QgsVectorLayer:
    """New outlines drawn by operators: added, redrawn, split or merged objects."""
    layer = _memory("MultiPolygon", "EADE – contours corrigés", crs_wkt,
                    [("cid", "int"), ("action", "string"), ("class", "string"), ("status", "string"),
                     ("author", "string")])
    feats = []
    for c in corrections:
        if c["geom_after"] is None or c["status"] == "REJECTED":
            continue
        f = QgsFeature(layer.fields())
        g = to_qgs(c["geom_after"])
        g.convertToMultiType()
        f.setGeometry(g)
        f.setAttributes([c["id"], c["action"], c["class_after"], c["status"], c["author"]])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    layer.updateExtents()
    layer.renderer().setSymbol(QgsFillSymbol.createSimple({"color": "47,158,68,90", "outline_color": "30,120,50,255",
                                                           "outline_width": "0.9"}))
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


def set_correction(layer: QgsVectorLayer, prediction_ids: set[int], status: str, action: str | None) -> None:
    fields = layer.fields()
    i_status, i_action = fields.indexOf("status"), fields.indexOf("correction")
    changes = {f.id(): {i_status: status, i_action: action} for f in layer.getFeatures() if f["pid"] in prediction_ids}
    if changes:
        layer.dataProvider().changeAttributeValues(changes)
        layer.triggerRepaint()


def add_to_project(layer: QgsVectorLayer) -> None:
    QgsProject.instance().addMapLayer(layer)
