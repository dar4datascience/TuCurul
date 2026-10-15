"""SITL / INFOPAL de la Cámara de Diputados: estadística parlamentaria."""

from typing import Any

from .base import Level, Source


class SitlDiputados(Source):
    name = "SITL — Sistema de Información y Transparencia Legislativa"
    url = "https://sitl.diputados.gob.mx/LXVI_leg/sistema_legislativo_LXVI.html"
    levels = (Level.FEDERAL,)
    dimensions = (
        "diputados_federales",
        "votaciones_federales",
        "iniciativas",
        "asistencias",
        "comisiones",
    )

    def fetch(self) -> Any:
        raise NotImplementedError("Pendiente: extracción del SITL.")
