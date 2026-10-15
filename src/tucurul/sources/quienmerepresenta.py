"""QuiénMeRepresenta: fichas de representantes por municipio/mapa."""

from typing import Any

from .base import Level, Source


class QuienMeRepresenta(Source):
    name = "QuiénMeRepresenta"
    url = "https://www.quienmerepresenta.com.mx/"
    levels = (Level.FEDERAL, Level.ESTATAL)
    dimensions = (
        "seccion_distrito_federal",
        "seccion_distrito_local",
        "senadores",
        "diputados_federales",
        "diputados_locales",
    )

    def fetch(self) -> Any:
        raise NotImplementedError("Pendiente: extracción de quienmerepresenta.com.mx.")
