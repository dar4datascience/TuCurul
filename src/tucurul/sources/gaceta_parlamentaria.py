"""Gaceta Parlamentaria: base de iniciativas de la Cámara de Diputados."""

from typing import Any

from .base import Level, Source


class GacetaParlamentaria(Source):
    name = "Gaceta Parlamentaria — Iniciativas"
    url = "https://gaceta.diputados.gob.mx/gp_inis.html"
    levels = (Level.FEDERAL,)
    dimensions = ("iniciativas", "diputados_federales")

    def fetch(self) -> Any:
        raise NotImplementedError("Pendiente: extracción de la Gaceta Parlamentaria.")
