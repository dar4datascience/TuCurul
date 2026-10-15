"""Sistema de Información Legislativa (SEGOB): fuente canónica federal."""

from typing import Any

from .base import Level, Source


class Sil(Source):
    name = "SIL — Sistema de Información Legislativa (SEGOB)"
    url = "https://sil.gobernacion.gob.mx/"
    levels = (Level.FEDERAL,)
    dimensions = (
        "senadores",
        "diputados_federales",
        "votaciones_federales",
        "iniciativas",
        "perfiles_curriculares",
    )

    def fetch(self) -> Any:
        raise NotImplementedError("Pendiente: extracción del SIL.")
