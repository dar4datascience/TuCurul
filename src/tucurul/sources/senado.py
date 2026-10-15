"""Portal del Senado: votaciones plenarias y directorio."""

from typing import Any

from .base import Level, Source


class Senado(Source):
    name = "Senado de la República — Votaciones"
    url = "https://senado.gob.mx/66/votaciones"
    levels = (Level.FEDERAL,)
    dimensions = ("senadores", "votaciones_federales", "comisiones")

    def fetch(self) -> Any:
        raise NotImplementedError("Pendiente: extracción de senado.gob.mx.")
