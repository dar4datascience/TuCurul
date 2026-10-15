"""ONC Observatorio Legislativo: votos en comisión y asistencias."""

from typing import Any

from .base import Level, Source


class OncObservatorio(Source):
    name = "ONC — Observatorio Legislativo"
    url = "https://seguimientolegislativo.onc.org.mx/"
    levels = (Level.FEDERAL, Level.ESTATAL)
    dimensions = (
        "votaciones_federales",
        "votaciones_locales",
        "comisiones",
        "asistencias",
    )

    def fetch(self) -> Any:
        raise NotImplementedError("Pendiente: extracción del Observatorio ONC.")
