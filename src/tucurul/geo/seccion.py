"""Localización de representantes a partir de la sección electoral INE.

El flujo: entidad + sección (de la credencial INE) → distrito federal,
distrito local y municipio → senadores, diputado federal y diputado local
que representan a la ciudadana o ciudadano.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..states import get_state
from .ine import SECCIONES_CSV


@dataclass(frozen=True)
class RepresentationKey:
    """Identificadores territoriales que determinan la representación.

    ``municipio`` es la clave municipal del INE (consecutiva por entidad),
    no la clave INEGI.
    """

    entidad: str
    seccion: int
    distrito_federal: int
    distrito_local: int
    municipio: int
    municipio_nombre: str


class SeccionNoEncontrada(KeyError):
    """La pareja (entidad, sección) no existe en el catálogo del INE."""


class SeccionLocator(Protocol):
    """Resuelve la geografía electoral de una sección INE."""

    def locate(self, entidad: str, seccion: int) -> RepresentationKey:
        """Devuelve los distritos y municipio de ``entidad`` + ``seccion``."""
        ...


class IneMarcoGeograficoLocator:
    """Localizador sobre ``data/ine/secciones.csv`` (Marco Geográfico INE).

    Genera el catálogo con ``tucurul ine-build`` (fuente: Marco Geográfico
    Seccional del INE / Ubica tu casilla, https://ubicatucasilla.ine.mx/).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else SECCIONES_CSV
        self._index: dict[tuple[str, int], RepresentationKey] | None = None

    def _load(self) -> dict[tuple[str, int], RepresentationKey]:
        if self._index is None:
            index = {}
            with open(self._path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    index[(row["entidad"], int(row["seccion"]))] = (
                        RepresentationKey(
                            entidad=row["entidad"],
                            seccion=int(row["seccion"]),
                            distrito_federal=int(row["distrito_federal"]),
                            distrito_local=int(row["distrito_local"]),
                            municipio=int(row["municipio"]),
                            municipio_nombre=row["municipio_nombre"],
                        )
                    )
            self._index = index
        return self._index

    def locate(self, entidad: str, seccion: int) -> RepresentationKey:
        state = get_state(str(entidad))
        key = (state.clave, int(seccion))
        try:
            return self._load()[key]
        except KeyError:
            raise SeccionNoEncontrada(
                f"Sección {seccion} no existe en {state.nombre} ({state.clave})"
            ) from None
