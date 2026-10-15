"""QuiénEsQuién.Wiki: trayectoria administrativa, instituciones y contratos."""

from typing import Any

from .base import Level, Source


class QuienesQuienWiki(Source):
    name = "QuiénEsQuién.Wiki"
    url = "https://www.quienesquien.wiki/"
    levels = (Level.FEDERAL, Level.ESTATAL, Level.MUNICIPAL)
    dimensions = ("trayectoria", "instituciones", "contratos")

    def fetch(self) -> Any:
        raise NotImplementedError(
            "Pendiente: extracción de quienesquien.wiki / sociedad.info."
        )
