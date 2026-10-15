"""Registro de fuentes disponibles."""

from .base import Source
from .gaceta_parlamentaria import GacetaParlamentaria
from .onc_observatorio import OncObservatorio
from .quienesquien_wiki import QuienesQuienWiki
from .quienmerepresenta import QuienMeRepresenta
from .senado import Senado
from .sil import Sil
from .sitl_diputados import SitlDiputados
from .tequio import Tequio

SOURCES: list[type[Source]] = [
    Sil,
    SitlDiputados,
    Senado,
    GacetaParlamentaria,
    Tequio,
    QuienMeRepresenta,
    QuienesQuienWiki,
    OncObservatorio,
]


def all_sources() -> list[Source]:
    """Instancia todas las fuentes registradas."""
    return [cls() for cls in SOURCES]
