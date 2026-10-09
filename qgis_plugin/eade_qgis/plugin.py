"""Plugin entry: Processing provider, workshop dock and menu."""

from __future__ import annotations

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon

try:  # Qt6 moved QAction to QtGui
    from qgis.PyQt.QtGui import QAction
except ImportError:  # pragma: no cover - Qt5
    from qgis.PyQt.QtWidgets import QAction

ICON = os.path.join(os.path.dirname(__file__), "icon.png")
MENU = "&EADE"


class EadePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.dock = None
        self.actions = []

    def initProcessing(self):  # noqa: N802 - QGIS hook, also called headless
        from .processing_provider.provider import EadeProvider
        self.provider = EadeProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802
        self.initProcessing()
        atelier = QAction(QIcon(ICON), "Atelier de correction", self.iface.mainWindow())
        atelier.setCheckable(True)
        atelier.toggled.connect(self.toggle_dock)
        self.iface.addToolBarIcon(atelier)
        self.iface.addPluginToMenu(MENU, atelier)
        detect = QAction(QIcon(ICON), "Détecter les bâtiments…", self.iface.mainWindow())
        detect.triggered.connect(lambda: self._open_algorithm("eade:detect"))
        self.iface.addPluginToMenu(MENU, detect)
        campaign = QAction(QIcon(ICON), "Lancer une campagne…", self.iface.mainWindow())
        campaign.triggered.connect(lambda: self._open_algorithm("eade:campaign"))
        self.iface.addPluginToMenu(MENU, campaign)
        self.actions = [atelier, detect, campaign]

    def _open_algorithm(self, alg_id: str) -> None:
        import processing
        processing.execAlgorithmDialog(alg_id)

    def toggle_dock(self, visible: bool) -> None:
        if self.dock is None:
            from .atelier.dock import AtelierDock
            self.dock = AtelierDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self.dock.visibilityChanged.connect(lambda v: self.actions[0].setChecked(v))
        self.dock.setVisible(visible)

    def unload(self):
        for a in self.actions:
            self.iface.removePluginMenu(MENU, a)
            self.iface.removeToolBarIcon(a)
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.close()
            self.dock.deleteLater()
            self.dock = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
