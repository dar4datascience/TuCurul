"""Catálogo de las 32 entidades federativas de México.

Los datos viven en ``data/states.csv`` en la raíz del repositorio:
clave INE, nombre, abreviatura, número de distritos federales
(distritación INE 2023) y número de senadores de mayoría relativa.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class State:
    """Una entidad federativa."""

    clave: str
    nombre: str
    abreviatura: str
    distritos_federales: int
    senadores: int


def load_states(path: Path | None = None) -> list[State]:
    """Carga las entidades desde ``data/states.csv`` (o ``path`` si se indica)."""
    csv_path = path or DATA_DIR / "states.csv"
    with open(csv_path, newline="", encoding="utf-8") as f:
        return [
            State(
                clave=row["clave"],
                nombre=row["nombre"],
                abreviatura=row["abreviatura"],
                distritos_federales=int(row["distritos_federales"]),
                senadores=int(row["senadores"]),
            )
            for row in csv.DictReader(f)
        ]


def get_state(clave_or_abbr: str) -> State:
    """Busca una entidad por clave INE ("01"–"32") o abreviatura ("CDMX").

    Acepta también la clave sin cero inicial ("9" ≡ "09").
    Lanza ``KeyError`` si no existe.
    """
    key = clave_or_abbr.strip()
    if key.isdigit():
        key = key.zfill(2)
    key = key.lower()
    for state in load_states():
        if key in (state.clave.lower(), state.abreviatura.lower()):
            return state
    raise KeyError(f"Entidad no encontrada: {clave_or_abbr!r}")
