"""The EADE workshop inside QGIS: review, correct and validate a campaign's objects.

It works directly on a project file (.eade). The QGIS map is the drawing board:
the campaign's objects are loaded as a styled layer, outlines are drawn on a
scratch layer with QGIS's own digitizing tools, and every action is written to
the project with its author.
"""

from __future__ import annotations

import getpass
import json

from qgis.core import QgsProject, QgsRectangle
from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (QAbstractItemView, QComboBox, QDockWidget, QFormLayout, QHBoxLayout, QLabel,
                                 QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                                 QSplitter, QTabWidget, QVBoxLayout, QWidget)

try:  # Qt6 moved QShortcut to QtGui
    from qgis.PyQt.QtGui import QShortcut
except ImportError:  # pragma: no cover - Qt5
    from qgis.PyQt.QtWidgets import QShortcut

from ..bootstrap import ensure_eade
from ..compat import to_shapely
from . import layers

REASONS = [("1", "Cour ou dalle au sol"), ("2", "Végétation"), ("3", "Ombre"), ("4", "Véhicule ou objet mobile"),
           ("5", "Appartient au voisin"), ("6", "Doublon"), ("7", "Chantier ou ruine"), ("8", "Autre")]
CLASSES = ["BUILDING", "COURTYARD", "VEGETATION", "FENCE", "ROAD", "POOL", "OTHER"]
DECISION_FR = {"ACCEPTED": "retenu", "REVIEW": "en revue", "REJECTED": "écarté"}
USER = Qt.ItemDataRole.UserRole


class AtelierDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("EADE – Atelier", parent)
        self.setObjectName("EadeAtelierDock")
        self.iface = iface
        ensure_eade()
        from eade.store import Actor
        self.actor = Actor(getpass.getuser() or "qgis")
        self.ws = None
        self.campaign = None
        self.pred_layer = None
        self.draw_layer = None
        self._build()

    # ------------------------------------------------------------------ ui

    def _build(self) -> None:
        root = QWidget()
        v = QVBoxLayout(root)

        form = QFormLayout()
        self.file = QgsFileWidget()
        self.file.setFilter("Projet EADE (*.eade)")
        self.file.fileChanged.connect(self.open_workspace)
        form.addRow("Projet", self.file)
        self.campaigns = QComboBox()
        self.campaigns.currentIndexChanged.connect(self.load_campaign)
        form.addRow("Campagne", self.campaigns)
        self.order = QComboBox()
        for key, label in (("uncertainty", "Incertitude"), ("random", "Aléatoire"), ("order", "Ordre")):
            self.order.addItem(label, key)
        self.order.currentIndexChanged.connect(self.refresh_queue)
        form.addRow("File", self.order)
        v.addLayout(form)
        self.status = QLabel("Ouvrez un projet EADE (.eade).")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._correction_tab(), "Correction")
        self.tabs.addTab(self._validation_tab(), "Validation")
        self.tabs.currentChanged.connect(lambda _: self.refresh_validation())
        v.addWidget(self.tabs, 1)
        self.setWidget(root)
        self._shortcuts()

    def _correction_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        split = QSplitter(Qt.Orientation.Vertical)
        self.queue = QListWidget()
        self.queue.currentItemChanged.connect(self.open_unit)
        split.addWidget(self.queue)
        self.objects = QListWidget()
        self.objects.currentItemChanged.connect(self.select_object)
        split.addWidget(self.objects)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        split.addWidget(self.detail)
        v.addWidget(split, 1)

        row = QHBoxLayout()
        self.btn_accept = QPushButton("Accepter [A]")
        self.btn_accept.clicked.connect(lambda: self.act("ACCEPT"))
        row.addWidget(self.btn_accept)
        self.reason = QComboBox()
        for k, label in REASONS:
            self.reason.addItem(f"{k}. {label}", k)
        row.addWidget(self.reason)
        self.btn_reject = QPushButton("Rejeter [R]")
        self.btn_reject.clicked.connect(lambda: self.act("REJECT"))
        row.addWidget(self.btn_reject)
        v.addLayout(row)

        row = QHBoxLayout()
        self.cls = QComboBox()
        self.cls.addItems(CLASSES)
        row.addWidget(self.cls)
        b = QPushButton("Reclasser")
        b.clicked.connect(lambda: self.act("RECLASSIFY"))
        row.addWidget(b)
        v.addLayout(row)

        row = QHBoxLayout()
        b = QPushButton("Tracer")
        b.setToolTip("Dessine un contour sur la couche « EADE – tracés »")
        b.clicked.connect(self.start_drawing)
        row.addWidget(b)
        b = QPushButton("Redessiner [D]")
        b.clicked.connect(lambda: self.act("REDRAW"))
        row.addWidget(b)
        b = QPushButton("Manquant [B]")
        b.clicked.connect(lambda: self.act("ADD"))
        row.addWidget(b)
        v.addLayout(row)

        self.btn_submit = QPushButton("Soumettre la parcelle [Ctrl+Entrée]")
        self.btn_submit.clicked.connect(self.submit)
        v.addWidget(self.btn_submit)
        return w

    def _validation_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.pending = QListWidget()
        self.pending.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.pending.currentItemChanged.connect(self.show_correction)
        v.addWidget(self.pending, 1)
        self.justification = QLineEdit()
        self.justification.setPlaceholderText("Justification (obligatoire)")
        v.addWidget(self.justification)
        row = QHBoxLayout()
        b = QPushButton("Valider la sélection")
        b.clicked.connect(lambda: self.review(True))
        row.addWidget(b)
        b = QPushButton("Rejeter la sélection")
        b.clicked.connect(lambda: self.review(False))
        row.addWidget(b)
        v.addLayout(row)
        return w

    def _shortcuts(self) -> None:
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for keys, fn in (("A", lambda: self.act("ACCEPT")), ("R", lambda: self.act("REJECT")),
                         ("D", lambda: self.act("REDRAW")), ("B", lambda: self.act("ADD")),
                         ("N", lambda: self.step(1)), ("P", lambda: self.step(-1)),
                         ("Ctrl+Return", self.submit)):
            s = QShortcut(QKeySequence(keys), self)
            s.setContext(ctx)
            s.activated.connect(fn)
        for k, _ in REASONS:
            s = QShortcut(QKeySequence(k), self)
            s.setContext(ctx)
            s.activated.connect(lambda k=k: self.reason.setCurrentIndex(int(k) - 1))

    # ------------------------------------------------------------- loading

    def _guard(self, fn, *args):
        """Run an action and show EADE's own message when it refuses."""
        from eade.store import EadeError
        try:
            return fn(*args)
        except EadeError as e:
            QMessageBox.warning(self, "EADE", str(e))
        except Exception as e:  # noqa: BLE001 - surface anything unexpected to the operator
            QMessageBox.critical(self, "EADE", f"{type(e).__name__}: {e}")
        return None

    def open_workspace(self, path: str) -> None:
        from eade.store import Workspace
        if self.ws is not None:
            self.ws.close()
        self.ws = Workspace(path) if path else None
        self.campaigns.blockSignals(True)
        self.campaigns.clear()
        if self.ws is not None:
            for c in self.ws.campaigns():
                if c["status"] in ("DONE", "CANCELLED", "INTERRUPTED") and c["counts"]["total"]:
                    self.campaigns.addItem(f"#{c['id']} {c['label']} — {c['counts']['total']} objets", c["id"])
        self.campaigns.blockSignals(False)
        s = self.ws.settings() if self.ws else None
        self.status.setText("Aucun projet." if s is None else
                            f"EADE {'actif' if s['enabled'] else 'désactivé'} · mode {s['mode'].lower()} · "
                            f"version active {s['active_version'] or '—'} · utilisateur {self.actor.name}")
        self.load_campaign()

    def load_campaign(self) -> None:
        if self.ws is None or self.campaigns.currentData() is None:
            return
        cid = self.campaigns.currentData()
        self.campaign = self.ws.campaign(cid)
        crs = self.ws._crs(cid)
        project = QgsProject.instance()
        for lyr in (self.pred_layer, self.draw_layer):
            if lyr is not None and project.mapLayer(lyr.id()) is not None:
                project.removeMapLayer(lyr.id())
        self.pred_layer = layers.predictions_layer(f"EADE – campagne {cid}", crs,
                                                   self.ws.predictions(cid, limit=10 ** 9))
        self.draw_layer = layers.outlines_layer(crs)
        layers.add_to_project(self.pred_layer)
        layers.add_to_project(self.draw_layer)
        self.refresh_queue()
        self.refresh_validation()

    def refresh_queue(self) -> None:
        self.queue.clear()
        if self.ws is None or self.campaign is None:
            return
        for u in self.ws.review_queue(self.campaign["id"], self.order.currentData() or "uncertainty"):
            text = f"{u['unit']}   {u['to_review']} à revoir"
            if u["undecided"]:
                text += f" · {u['undecided']} en revue"
            if u["submitted"]:
                text += f" · {u['submitted']} soumise(s)"
            item = QListWidgetItem(text)
            item.setData(USER, u["unit"])
            self.queue.addItem(item)
        if self.queue.count():
            self.queue.setCurrentRow(0)

    def _unit_predictions(self, unit: str) -> list[dict]:
        cid = self.campaign["id"]
        if unit.startswith("object:"):
            return [self.ws.prediction(int(unit[7:]))]
        return self.ws.predictions(cid, parcel_id=unit, limit=10 ** 6)

    def open_unit(self, item, _previous=None) -> None:
        self.objects.clear()
        if item is None:
            return
        preds = self._unit_predictions(item.data(USER))
        for p in sorted(preds, key=lambda p: (p["decision"] != "REVIEW", -(p["measure"] or 0))):
            score = "—" if p["score"] is None else f"{p['score']:.2f}"
            it = QListWidgetItem(f"{p['final_class']} {p['measure']:.1f} m² · {DECISION_FR[p['decision']]} "
                                 f"({score}) · {p['status'].lower()}")
            it.setData(USER, p["id"])
            self.objects.addItem(it)
        self._zoom([p["geometry"] for p in preds])
        if self.objects.count():
            self.objects.setCurrentRow(0)

    def _zoom(self, geoms) -> None:
        if not geoms:
            return
        x0 = min(g.bounds[0] for g in geoms)
        y0 = min(g.bounds[1] for g in geoms)
        x1 = max(g.bounds[2] for g in geoms)
        y1 = max(g.bounds[3] for g in geoms)
        r = QgsRectangle(x0, y0, x1, y1)
        r.scale(1.6)
        canvas = self.iface.mapCanvas()
        from qgis.core import QgsCoordinateTransform
        t = QgsCoordinateTransform(self.pred_layer.crs(), canvas.mapSettings().destinationCrs(), QgsProject.instance())
        canvas.setExtent(t.transformBoundingBox(r))
        canvas.refresh()

    def select_object(self, item, _previous=None) -> None:
        if item is None or self.pred_layer is None:
            return
        pid = item.data(USER)
        p = self.ws.prediction(pid)
        ids = [f.id() for f in self.pred_layer.getFeatures() if f["pid"] == pid]
        self.pred_layer.selectByIds(ids)
        e = p["explanation"]
        lines = [f"Prédiction #{pid} · parcelle {p['parcel_id'] or '—'}",
                 f"Décision {DECISION_FR[p['decision']]} · score {e['score']} · classe {e['class']['final']}",
                 f"Moteur classique : {'retenu' if p['classic_accepted'] else 'rejeté'}"
                 + (f" ({p['classic_reason']})" if p["classic_reason"] else "")]
        for r in e["rules_fired"]:
            reads = ", ".join(f"{k}={_fmt(v)}" for k, v in r["reads"].items())
            lines.append(f"Règle {r['code']} [{r['effect']}] : {reads}")
        for r in e["rules_unknown"]:
            lines.append(f"Règle {r['code']} non évaluable (manque {', '.join(r['missing'])})")
        if e["guardrails"]:
            lines.append("Garde-fous : " + ", ".join(e["guardrails"]))
        lines.append("")
        for k in ("height_median_m", "area_m2", "rectangularity", "green_share", "shadow_share", "parcel_share"):
            if k in p["features"]:
                lines.append(f"{k} = {_fmt(p['features'][k])}")
        self.detail.setPlainText("\n".join(lines))

    def step(self, delta: int) -> None:
        row = self.queue.currentRow() + delta
        if 0 <= row < self.queue.count():
            self.queue.setCurrentRow(row)

    # ------------------------------------------------------------ actions

    def start_drawing(self) -> None:
        if self.draw_layer is None:
            return
        self.iface.setActiveLayer(self.draw_layer)
        if not self.draw_layer.isEditable():
            self.draw_layer.startEditing()
        self.iface.actionAddFeature().trigger()

    def _drawn_geometry(self):
        """The selected outline on the drawing layer, else the last one drawn."""
        lyr = self.draw_layer
        if lyr is None:
            return None, None
        feats = lyr.selectedFeatures() or list(lyr.getFeatures())
        if not feats:
            return None, None
        f = feats[-1]
        return to_shapely(f.geometry()), f.id()

    def _consume(self, fid) -> None:
        lyr = self.draw_layer
        if not lyr.isEditable():
            lyr.startEditing()
        lyr.deleteFeature(fid)
        lyr.commitChanges()

    def act(self, action: str) -> None:
        if self.ws is None or self.campaign is None:
            return
        item = self.objects.currentItem()
        pid = item.data(USER) if item is not None else None
        kwargs = {}
        fid = None
        if action in ("REDRAW", "ADD"):
            geom, fid = self._drawn_geometry()
            if geom is None:
                QMessageBox.information(self, "EADE", "Tracez d'abord le contour avec « Tracer ».")
                return
            kwargs["geometry"] = geom
            kwargs["features"] = self._guard(self.ws.measure, self.campaign["id"], geom)
        if action == "ADD":
            unit = self.queue.currentItem().data(USER) if self.queue.currentItem() else None
            kwargs.update(campaign_id=self.campaign["id"], class_after=self.cls.currentText(),
                          parcel_id=None if unit is None or unit.startswith("object:") else unit)
            pid = None
        elif pid is None:
            return
        if action == "REJECT":
            kwargs["reason"] = self.reason.currentData()
        if action == "RECLASSIFY":
            kwargs["class_after"] = self.cls.currentText()
        done = self._guard(lambda: self.ws.correct(self.actor, action, prediction_id=pid, **kwargs))
        if done is None:
            return
        if fid is not None:
            self._consume(fid)
        if pid is not None:
            layers.set_status(self.pred_layer, {pid}, "IN_CORRECTION")
        self.iface.messageBar().pushSuccess("EADE", f"{action.lower()} enregistré")
        row = self.objects.currentRow()
        self.open_unit(self.queue.currentItem())
        self.objects.setCurrentRow(min(row + 1, self.objects.count() - 1))

    def submit(self) -> None:
        if self.ws is None or self.campaign is None or self.queue.currentItem() is None:
            return
        unit = self.queue.currentItem().data(USER)
        n = self._guard(self.ws.submit, self.actor, self.campaign["id"], None if unit.startswith("object:") else unit)
        if n is None:
            return
        self.iface.messageBar().pushSuccess("EADE", f"{n} correction(s) envoyée(s) à l'expert")
        row = self.queue.currentRow()
        self.refresh_queue()
        if self.queue.count():
            self.queue.setCurrentRow(min(row, self.queue.count() - 1))

    # --------------------------------------------------------- validation

    def refresh_validation(self) -> None:
        self.pending.clear()
        if self.ws is None or self.campaign is None:
            return
        for c in self.ws.corrections(self.campaign["id"], "SUBMITTED"):
            before = f"{c['measure_before']:.1f}" if c["measure_before"] else "—"
            after = f"{c['measure_after']:.1f}" if c["measure_after"] else "—"
            text = (f"{c['action'].lower()} · {c['class_before'] or ''} → {c['class_after'] or ''} · "
                    f"{before} → {after} m² · {c['reason'] or ''} · par {c['author']}")
            it = QListWidgetItem(text)
            it.setData(USER, c["id"])
            self.pending.addItem(it)

    def show_correction(self, item, _previous=None) -> None:
        if item is None:
            return
        c = next((c for c in self.ws.corrections(self.campaign["id"], "SUBMITTED") if c["id"] == item.data(USER)), None)
        if c is not None:
            self._zoom([g for g in (c["geom_before"], c["geom_after"]) if g is not None])
            if c["prediction_id"] is not None:
                self.pred_layer.selectByIds([f.id() for f in self.pred_layer.getFeatures()
                                             if f["pid"] == c["prediction_id"]])

    def review(self, approve: bool) -> None:
        ids = [it.data(USER) for it in self.pending.selectedItems()]
        if not ids:
            return
        out = self._guard(self.ws.review, self.actor, ids, approve, self.justification.text())
        if out is None:
            return
        self.justification.clear()
        msg = f"{out['corrections']} correction(s) {'validée(s)' if approve else 'rejetée(s)'}"
        if out["learning"]:
            msg += f", {out['examples']} exemple(s) d'apprentissage"
        self.iface.messageBar().pushSuccess("EADE", msg)
        self.load_campaign()

    def closeEvent(self, event) -> None:
        if self.ws is not None:
            self.ws.close()
            self.ws = None
        super().closeEvent(event)


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.3g}"
    return json.dumps(v) if isinstance(v, (bool, type(None))) else str(v)
