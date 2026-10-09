from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms import ALGORITHMS, ICON


class EadeProvider(QgsProcessingProvider):
    def id(self):
        return "eade"

    def name(self):
        return "EADE"

    def longName(self):
        return "EADE – moteur de détection adaptatif"

    def icon(self):
        return QIcon(ICON)

    def loadAlgorithms(self):
        for cls in ALGORITHMS:
            self.addAlgorithm(cls())
