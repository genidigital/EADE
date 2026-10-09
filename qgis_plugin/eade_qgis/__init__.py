"""EADE plugin for QGIS."""


def classFactory(iface):  # noqa: N802 - QGIS entry point
    from .plugin import EadePlugin
    return EadePlugin(iface)
