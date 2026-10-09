"""EADE algorithms for the QGIS Processing toolbox."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsFields,
                       QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingParameterBoolean,
                       QgsProcessingParameterExtent, QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterField,
                       QgsProcessingParameterFile, QgsProcessingParameterFileDestination,
                       QgsProcessingParameterNumber, QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterString, QgsProject)
from qgis.PyQt.QtGui import QIcon

from ..bootstrap import ensure_eade
from ..compat import (FAST_INSERT, any_vector_source_type, field, file_behavior, multipolygon_type,
                      number_double, polygon_source_type, to_qgs, to_shapely)

ICON = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon.png")

PREDICTION_FIELDS = [("candidate", "string"), ("class", "string"), ("final_cls", "string"), ("decision", "string"),
                     ("score", "double"), ("classic_ok", "int"), ("classic_why", "string"), ("rules", "string"),
                     ("measure", "double"), ("parcel_id", "string"), ("kn_version", "int"),
                     ("fingerprint", "string"), ("explain", "string")]


def _fields(spec) -> QgsFields:
    fs = QgsFields()
    for name, kind in spec:
        fs.append(field(name, kind))
    return fs


def _source_path(layer) -> str:
    """File behind a raster or vector layer (QGIS appends options after '|')."""
    return layer.source().split("|")[0] if layer is not None else None


def _features_in_crs(source, crs, context):
    """(id, shapely geometry) of a feature source, transformed to `crs`."""
    t = QgsCoordinateTransform(source.sourceCrs(), crs, context.transformContext())
    out = []
    for f in source.getFeatures():
        g = f.geometry()
        if g.isNull() or g.isEmpty():
            continue
        g.transform(t)
        out.append((f, to_shapely(g)))
    return out


class _Base(QgsProcessingAlgorithm):
    def group(self):
        return "EADE"

    def groupId(self):
        return "eade"

    def icon(self):
        return QIcon(ICON)

    def createInstance(self):
        return type(self)()

    def _rasters(self, parameters, context, dsm_required=True):
        dsm = self.parameterAsRasterLayer(parameters, "DSM", context)
        dtm = self.parameterAsRasterLayer(parameters, "DTM", context)
        ortho = self.parameterAsRasterLayer(parameters, "ORTHO", context)
        if dsm_required and dsm is None:
            raise QgsProcessingException("Un modèle numérique de surface (MNS) est requis.")
        ref = dsm or ortho
        if ref is None:
            raise QgsProcessingException("Un MNS ou une orthophoto est requis.")
        if not ref.crs().isValid() or ref.crs().isGeographic():
            raise QgsProcessingException("Les rasters doivent être dans une projection métrique (par exemple UTM).")
        eade = ensure_eade()
        from eade.geo import RasterSources
        return RasterSources(_source_path(dsm), _source_path(dtm), _source_path(ortho)), ref.crs(), eade

    def _raster_params(self, dsm_optional=False):
        self.addParameter(QgsProcessingParameterRasterLayer("DSM", "Modèle numérique de surface (MNS)",
                                                            optional=dsm_optional))
        self.addParameter(QgsProcessingParameterRasterLayer(
            "DTM", "Modèle numérique de terrain (MNT, estimé si absent)", optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer("ORTHO", "Orthophoto", optional=True))


def _write_results(sink, results):
    for r in results:
        c = r.candidate
        f = QgsFeature()
        g = to_qgs(c.geometry)
        g.convertToMultiType()
        f.setGeometry(g)
        f.setAttributes([
            c.id, c.target_class, r.final_class, r.decision.value,
            None if r.score is None else round(r.score, 4),
            None if c.classic_accepted is None else int(c.classic_accepted), c.meta.get("classic_reason"),
            ",".join(t.code for t in r.fired), round(c.geometry.area, 3),
            None if c.meta.get("parcel_id") is None else str(c.meta.get("parcel_id")),
            r.version, r.fingerprint, json.dumps(r.explanation(), ensure_ascii=False, default=str)])
        sink.addFeature(f, FAST_INSERT)


# --------------------------------------------------------------------- detect

class DetectAlgorithm(_Base):
    def name(self):
        return "detect"

    def displayName(self):
        return "Détecter les bâtiments (levé drone)"

    def shortHelpString(self):
        return ("Détecte tout ce qui s'élève au-dessus du sol sur le MNS, mesure chaque objet (37 "
                "caractéristiques), puis décide avec une version de connaissance EADE : retenu, en revue ou écarté. "
                "Chaque objet porte son score, les règles déclenchées et l'explication complète. Sans fichier de "
                "connaissance, les verdicts du moteur classique sont conservés.")

    def initAlgorithm(self, config=None):
        self._raster_params()
        self.addParameter(QgsProcessingParameterFeatureSource("PARCELS", "Parcelles", [polygon_source_type()],
                                                              optional=True))
        self.addParameter(QgsProcessingParameterField("PARCEL_ID", "Identifiant de parcelle",
                                                      parentLayerParameterName="PARCELS", optional=True))
        self.addParameter(QgsProcessingParameterFile("KNOWLEDGE", "Version de connaissance (JSON)",
                                                     extension="json", optional=True))
        self.addParameter(QgsProcessingParameterExtent("EXTENT", "Emprise", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink("OUTPUT", "Objets détectés"))

    def processAlgorithm(self, parameters, context, feedback):
        sources, crs, _ = self._rasters(parameters, context)
        from eade.geo import GeoPipeline
        from eade.io import knowledge_json

        kfile = self.parameterAsFile(parameters, "KNOWLEDGE", context)
        version = knowledge_json.load(kfile, keep_status=True) if kfile else None
        bounds = None
        if parameters.get("EXTENT"):
            e = self.parameterAsExtent(parameters, "EXTENT", context, crs)
            if not e.isNull():
                bounds = (e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum())
        parcels = None
        src = self.parameterAsSource(parameters, "PARCELS", context)
        if src is not None:
            id_field = self.parameterAsString(parameters, "PARCEL_ID", context)
            parcels = [(f[id_field] if id_field else f.id(), g) for f, g in _features_in_crs(src, crs, context)]
            feedback.pushInfo(f"{len(parcels)} parcelles chargées")

        def progress(done, total):
            feedback.setProgress(100.0 * done / total)
            return not feedback.isCanceled()

        run = GeoPipeline(version).run(sources, bounds, parcels=parcels, progress=progress)
        sink, dest = self.parameterAsSink(parameters, "OUTPUT", context, _fields(PREDICTION_FIELDS),
                                          multipolygon_type(), crs)
        _write_results(sink, run.results)
        c = run.counts()
        feedback.pushInfo(f"Retenus {c['ACCEPTED']} · en revue {c['REVIEW']} · écartés {c['REJECTED']} "
                          f"(moteur raster : {run.provenance['raster_backend']})")
        return {"OUTPUT": dest, "ACCEPTED": c["ACCEPTED"], "REVIEW": c["REVIEW"], "REJECTED": c["REJECTED"]}


# -------------------------------------------------------------------- measure

class MeasureAlgorithm(_Base):
    def name(self):
        return "measure"

    def displayName(self):
        return "Mesurer des emprises"

    def shortHelpString(self):
        return ("Mesure chaque polygone (tracé à la main, importé…) avec le dictionnaire EADE Geo : géométrie, "
                "hauteurs, couleur, texture, qualité. Les mesures s'ajoutent aux attributs.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource("INPUT", "Emprises", [polygon_source_type()]))
        self._raster_params(dsm_optional=True)
        self.addParameter(QgsProcessingParameterFeatureSink("OUTPUT", "Emprises mesurées"))

    def processAlgorithm(self, parameters, context, feedback):
        sources, crs, _ = self._rasters(parameters, context, dsm_required=False)
        from eade.geo import GeoFeatureExtractor, geo_catalog

        src = self.parameterAsSource(parameters, "INPUT", context)
        keys = [d.key for d in geo_catalog() if d.group != "context"]
        fields = QgsFields(src.fields())
        for k in keys:
            fields.append(field(k, "double"))
        sink, dest = self.parameterAsSink(parameters, "OUTPUT", context, fields, multipolygon_type(), crs)
        items = _features_in_crs(src, crs, context)
        extractor = GeoFeatureExtractor()
        with sources.open() as opened:
            for i, (f, g) in enumerate(items):
                if feedback.isCanceled():
                    break
                m = extractor.measure(g, opened)
                out = QgsFeature(fields)
                qg = to_qgs(g)
                qg.convertToMultiType()
                out.setGeometry(qg)
                out.setAttributes(list(f.attributes()) + [None if m.get(k) is None else float(m[k]) for k in keys])
                sink.addFeature(out, FAST_INSERT)
                feedback.setProgress(100.0 * (i + 1) / max(1, len(items)))
        return {"OUTPUT": dest}


# ------------------------------------------------------------------- evaluate

class EvaluateAlgorithm(_Base):
    def name(self):
        return "evaluate"

    def displayName(self):
        return "Évaluer des détections"

    def shortHelpString(self):
        return ("Compare des détections à des contours de référence validés : IoU moyen par objet, précision, "
                "rappel, faux positifs, oublis et erreur de surface. Seuls les objets dont la décision vaut "
                "ACCEPTED sont comptés comme retenus.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource("PREDICTIONS", "Détections", [any_vector_source_type()]))
        self.addParameter(QgsProcessingParameterField("DECISION_FIELD", "Champ de décision", "decision",
                                                      parentLayerParameterName="PREDICTIONS", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource("REFERENCES", "Références validées",
                                                              [any_vector_source_type()]))
        self.addParameter(QgsProcessingParameterString("CLASS", "Classe évaluée", "BUILDING"))
        self.addParameter(QgsProcessingParameterNumber("MATCH_IOU", "IoU minimal pour un appariement",
                                                       number_double(), 0.5, minValue=0.05, maxValue=1.0))
        self.addParameter(QgsProcessingParameterFileDestination("REPORT", "Rapport", "JSON (*.json)", optional=True))

    def processAlgorithm(self, parameters, context, feedback):
        ensure_eade()
        from eade.core.decision import Decision
        from eade.core.evaluation import Reference, evaluate
        from eade.geo import iou, measure, utm_epsg

        preds = self.parameterAsSource(parameters, "PREDICTIONS", context)
        refs = self.parameterAsSource(parameters, "REFERENCES", context)
        cls = self.parameterAsString(parameters, "CLASS", context)
        dfield = self.parameterAsString(parameters, "DECISION_FIELD", context)
        crs = preds.sourceCrs()
        if crs.isGeographic():
            c = QgsCoordinateTransform(crs, QgsCoordinateReferenceSystem("EPSG:4326"), context.transformContext()) \
                .transformBoundingBox(preds.sourceExtent()).center()
            crs = QgsCoordinateReferenceSystem(f"EPSG:{utm_epsg(c.x(), c.y())}")
        results = []
        for f, g in _features_in_crs(preds, crs, context):
            decision = str(f[dfield]) if dfield else "ACCEPTED"
            if decision not in ("ACCEPTED", "REVIEW", "REJECTED"):
                decision = "ACCEPTED"
            results.append(SimpleNamespace(decision=Decision(decision), final_class=cls,
                                           candidate=SimpleNamespace(geometry=g)))
        references = [Reference(str(f.id()), cls, g) for f, g in _features_in_crs(refs, crs, context)]
        m = evaluate(results, references, iou, measure,
                     self.parameterAsDouble(parameters, "MATCH_IOU", context)).by_class.get(cls)
        if m is None:
            raise QgsProcessingException("Aucun objet à évaluer.")
        report = m.to_dict()
        for k, v in report.items():
            feedback.pushInfo(f"{k}: {v}")
        path = self.parameterAsFileOutput(parameters, "REPORT", context)
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
        return {"REPORT": path, "MEAN_IOU": report["mean_iou"], "PRECISION": report["precision"],
                "RECALL": report["recall"], "FALSE_POSITIVES": report["false_positives"], "MISSES": report["misses"]}


# ------------------------------------------------------------------- campaign

class CampaignAlgorithm(_Base):
    def name(self):
        return "campaign"

    def displayName(self):
        return "Lancer une campagne dans un projet EADE"

    def shortHelpString(self):
        return ("Enregistre et exécute une campagne de détection dans un projet EADE (.eade). La version de "
                "connaissance active est figée au lancement ; les objets peuvent ensuite être revus dans "
                "l'atelier EADE. Le projet est créé s'il n'existe pas.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile("WORKSPACE", "Projet EADE (.eade)", extension="eade",
                                                     behavior=file_behavior()))
        self.addParameter(QgsProcessingParameterString("LABEL", "Libellé", "Campagne"))
        self._raster_params()
        self.addParameter(QgsProcessingParameterFeatureSource("PARCELS", "Parcelles (fichier)",
                                                              [polygon_source_type()], optional=True))
        self.addParameter(QgsProcessingParameterField("PARCEL_ID", "Identifiant de parcelle",
                                                      parentLayerParameterName="PARCELS", optional=True))
        self.addParameter(QgsProcessingParameterBoolean("APPLY", "Appliquer EADE (version active)", True))
        self.addParameter(QgsProcessingParameterFeatureSink("OUTPUT", "Prédictions"))

    def processAlgorithm(self, parameters, context, feedback):
        sources, crs, _ = self._rasters(parameters, context)
        from eade.store import Actor, Workspace

        path = parameters.get("WORKSPACE") or self.parameterAsFile(parameters, "WORKSPACE", context)
        parcels_path = None
        if parameters.get("PARCELS"):
            layer = self.parameterAsVectorLayer(parameters, "PARCELS", context)
            parcels_path = _source_path(layer) if layer is not None else None
            if not parcels_path or not os.path.exists(parcels_path):
                raise QgsProcessingException("Les parcelles doivent provenir d'un fichier (GeoPackage, Shapefile…).")
        actor = Actor(os.environ.get("USERNAME") or os.environ.get("USER") or "qgis")
        ws = Workspace(path)
        try:
            c = ws.create_campaign(actor, self.parameterAsString(parameters, "LABEL", context), sources.describe(),
                                   parcels=parcels_path,
                                   parcel_id_field=self.parameterAsString(parameters, "PARCEL_ID", context) or None,
                                   apply_eade=self.parameterAsBoolean(parameters, "APPLY", context))
            feedback.pushInfo(f"Campagne {c['id']} : EADE {'appliqué (v%s)' % c['version_number'] if c['eade_applied'] else 'non appliqué'}")
            c = ws.run_campaign(actor, c["id"], progress=lambda d, t: feedback.setProgress(100.0 * d / t))
            sink, dest = self.parameterAsSink(parameters, "OUTPUT", context, _fields(PREDICTION_FIELDS),
                                              multipolygon_type(), crs)
            for p in ws.predictions(c["id"], limit=10 ** 9):
                f = QgsFeature()
                g = to_qgs(p["geometry"])
                g.convertToMultiType()
                f.setGeometry(g)
                e = p["explanation"]
                f.setAttributes([p["candidate_id"], p["class"], p["final_class"], p["decision"], p["score"],
                                 None if p["classic_accepted"] is None else int(p["classic_accepted"]),
                                 p["classic_reason"], ",".join(r["code"] for r in e["rules_fired"]),
                                 p["measure"], p["parcel_id"], p["version_number"], p["fingerprint"],
                                 json.dumps(e, ensure_ascii=False)])
                sink.addFeature(f, FAST_INSERT)
        finally:
            ws.close()
        k = c["counts"]
        feedback.pushInfo(f"Retenus {k['ACCEPTED']} · en revue {k['REVIEW']} · écartés {k['REJECTED']}")
        return {"OUTPUT": dest, "CAMPAIGN": c["id"]}


ALGORITHMS = [DetectAlgorithm, MeasureAlgorithm, EvaluateAlgorithm, CampaignAlgorithm]
