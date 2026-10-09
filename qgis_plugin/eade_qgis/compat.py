"""Small shims so the same code runs on QGIS 3.34+ (Qt5) and QGIS 4 (Qt6)."""

from __future__ import annotations

import shapely
from qgis.core import Qgis, QgsFeatureSink, QgsField, QgsGeometry, QgsProcessing

try:  # QGIS >= 3.38 types fields with QMetaType
    from qgis.PyQt.QtCore import QMetaType
    _T = {"int": QMetaType.Type.Int, "double": QMetaType.Type.Double, "string": QMetaType.Type.QString,
          "long": QMetaType.Type.LongLong}

    def field(name: str, kind: str) -> QgsField:
        return QgsField(name, _T[kind])
except (ImportError, AttributeError):  # pragma: no cover - older QGIS
    from qgis.PyQt.QtCore import QVariant
    _V = {"int": QVariant.Int, "double": QVariant.Double, "string": QVariant.String, "long": QVariant.LongLong}

    def field(name: str, kind: str) -> QgsField:
        return QgsField(name, _V[kind])


def polygon_source_type():
    pst = getattr(Qgis, "ProcessingSourceType", None)
    return pst.VectorPolygon if pst is not None else QgsProcessing.TypeVectorPolygon


def any_vector_source_type():
    pst = getattr(Qgis, "ProcessingSourceType", None)
    return pst.VectorAnyGeometry if pst is not None else QgsProcessing.TypeVectorAnyGeometry


def multipolygon_type():
    wt = getattr(Qgis, "WkbType", None)
    if wt is not None:
        return wt.MultiPolygon
    from qgis.core import QgsWkbTypes  # pragma: no cover
    return QgsWkbTypes.MultiPolygon


def number_double():
    t = getattr(Qgis, "ProcessingNumberParameterType", None)
    if t is not None:
        return t.Double
    from qgis.core import QgsProcessingParameterNumber  # pragma: no cover
    return QgsProcessingParameterNumber.Double


def file_behavior():
    b = getattr(Qgis, "ProcessingFileParameterBehavior", None)
    if b is not None:
        return b.File
    from qgis.core import QgsProcessingParameterFile  # pragma: no cover
    return QgsProcessingParameterFile.File


FAST_INSERT = getattr(getattr(QgsFeatureSink, "Flag", QgsFeatureSink), "FastInsert")


def to_shapely(g: QgsGeometry):
    return shapely.from_wkb(bytes(g.asWkb()))


def to_qgs(geom) -> QgsGeometry:
    q = QgsGeometry()
    q.fromWkb(shapely.to_wkb(geom))
    return q
