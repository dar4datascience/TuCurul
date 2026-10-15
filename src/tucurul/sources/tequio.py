"""Tequio: votaciones nominales y "Mis Representantes" (sociedad civil)."""

from typing import Any

from .base import Level, Source


class Tequio(Source):
    name = "Tequio"
    url = "https://tequio.app/"
    levels = (Level.FEDERAL,)
    dimensions = (
        "senadores",
        "diputados_federales",
        "votaciones_federales",
        "iniciativas",
    )

    def fetch(self) -> Any:
        raise NotImplementedError("Pendiente: extracción de tequio.app.")
