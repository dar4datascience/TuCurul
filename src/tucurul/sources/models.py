"""Modelo normalizado de registros legislativos (issue #10).

Dataclasses ``frozen`` que devuelven los conectores de fuentes, más los
mapeos compartidos de sentido del voto, partido y entidad federativa.
"""

import csv
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date
from enum import Enum
from pathlib import Path

from ..states import load_states


class Camara(str, Enum):
    """Cámara u órgano legislativo."""

    DIPUTADOS = "diputados"
    SENADO = "senado"
    CONGRESO_LOCAL = "congreso_local"


class Principio(str, Enum):
    """Principio de elección del cargo."""

    MR = "MR"
    RP = "RP"
    PRIMERA_MINORIA = "primera_minoria"


class Sentido(str, Enum):
    """Sentido normalizado del voto de un legislador."""

    A_FAVOR = "a_favor"
    EN_CONTRA = "en_contra"
    ABSTENCION = "abstencion"
    AUSENTE = "ausente"
    SOLO_ASISTENCIA = "solo_asistencia"
    OTRO = "otro"


@dataclass(frozen=True)
class Legislador:
    """Persona con cargo legislativo en una fuente."""

    source: str
    source_id: str
    nombre: str
    camara: Camara
    legislatura: str
    entidad: str | None
    source_url: str
    distrito_federal: int | None = None
    distrito_local: int | None = None
    circunscripcion: int | None = None
    principio: Principio | None = None
    partido: str | None = None
    estatus: str | None = None
    suplente: str | None = None
    curul: str | None = None


@dataclass(frozen=True)
class Votacion:
    """Una votación nominal con sus totales reportados."""

    source: str
    source_id: str
    camara: Camara
    legislatura: str
    fecha: date | None
    titulo: str
    a_favor: int
    en_contra: int
    abstencion: int
    solo_asistencia: int
    ausente: int | None
    source_url: str
    instancia: str = "pleno"
    periodo: str | None = None


@dataclass(frozen=True)
class TotalGrupo:
    """Totales de una votación desagregados por grupo parlamentario."""

    source: str
    votacion_id: str
    partido: str
    a_favor: int
    en_contra: int
    abstencion: int
    solo_asistencia: int
    ausente: int
    source_url: str


@dataclass(frozen=True)
class Voto:
    """Voto individual de un legislador en una votación."""

    source: str
    votacion_id: str
    legislador_source_id: str
    sentido: Sentido
    partido: str | None
    source_url: str


@dataclass(frozen=True)
class Iniciativa:
    """Iniciativa o punto de acuerdo presentado."""

    source: str
    source_id: str
    legislatura: str
    fecha: date | None
    titulo: str
    presentadores: tuple[str, ...]
    turno: str | None
    estatus: str | None
    source_url: str


def _fold(texto: str) -> str:
    """Minúsculas sin acentos ni puntuación: solo letras y dígitos."""
    decomposed = unicodedata.normalize("NFKD", texto.strip().lower())
    return "".join(c for c in decomposed if c.isalnum())


# Texto de voto tal como lo publica cada fuente → Sentido.
SENTIDO_POR_FUENTE: dict[str, dict[str, Sentido]] = {
    "sitl_diputados": {
        "a favor": Sentido.A_FAVOR,
        "en contra": Sentido.EN_CONTRA,
        "abstención": Sentido.ABSTENCION,
        "abstencion": Sentido.ABSTENCION,
        "solo asistencia": Sentido.SOLO_ASISTENCIA,
        "sólo asistencia": Sentido.SOLO_ASISTENCIA,
        "ausente": Sentido.AUSENTE,
    },
    "senado": {
        "pro": Sentido.A_FAVOR,
        "contra": Sentido.EN_CONTRA,
        "abstención": Sentido.ABSTENCION,
        "abstencion": Sentido.ABSTENCION,
        "ausente": Sentido.AUSENTE,
    },
}

_SENTIDO_INDEX = {
    fuente: {_fold(texto): sentido for texto, sentido in mapa.items()}
    for fuente, mapa in SENTIDO_POR_FUENTE.items()
}

# Alias → código canónico de partido.
PARTIDO_ALIAS: dict[str, str] = {
    "MORENA": "MORENA",
    "Movimiento Regeneración Nacional": "MORENA",
    "PAN": "PAN",
    "Partido Acción Nacional": "PAN",
    "PRI": "PRI",
    "Partido Revolucionario Institucional": "PRI",
    "PRD": "PRD",
    "Partido de la Revolución Democrática": "PRD",
    "PT": "PT",
    "Partido del Trabajo": "PT",
    "PVEM": "PVEM",
    "Verde": "PVEM",
    "Partido Verde": "PVEM",
    "Partido Verde Ecologista de México": "PVEM",
    "MC": "MC",
    "Movimiento Ciudadano": "MC",
    "IND": "IND",
    "Independiente": "IND",
    "Sin Partido": "IND",
    "SP": "IND",
}

_PARTIDO_INDEX = {_fold(alias): codigo for alias, codigo in PARTIDO_ALIAS.items()}

# Nombres históricos/oficiales alternativos → clave INEGI.
_ENTIDAD_ALIAS = {
    "Distrito Federal": "09",
    "Estado de México": "15",
    "Edo. de México": "15",
    "Coahuila de Zaragoza": "05",
    "Michoacán de Ocampo": "16",
    "Veracruz de Ignacio de la Llave": "30",
}


def _entidad_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for state in load_states():
        index[_fold(state.clave)] = state.clave
        index[_fold(state.abreviatura)] = state.clave
        index[_fold(state.nombre)] = state.clave
    for alias, clave in _ENTIDAD_ALIAS.items():
        index[_fold(alias)] = clave
    return index


_ENTIDADES = _entidad_index()


def normalize_sentido(source: str, raw: str) -> Sentido:
    """Traduce el texto del voto de una fuente; desconocido → ``OTRO``."""
    return _SENTIDO_INDEX.get(source, {}).get(_fold(raw), Sentido.OTRO)


def normalize_partido(raw: str) -> str:
    """Código corto canónico; desconocido → el texto en mayúsculas."""
    return _PARTIDO_INDEX.get(_fold(raw), raw.strip().upper())


def normalize_entidad(raw: str) -> str:
    """Clave INEGI de 2 dígitos; ``KeyError`` si no se reconoce.

    Acepta clave ("15", "9"), abreviatura ("CDMX"), nombre con o sin
    acentos ("México", "ciudad de mexico"), slug ("ciudad-de-mexico")
    y alias oficiales ("Distrito Federal", "Estado de México").
    """
    key = _fold(raw)
    if key.isdigit():
        key = key.zfill(2)
    try:
        return _ENTIDADES[key]
    except KeyError:
        raise KeyError(f"Entidad no reconocida: {raw!r}") from None


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return "|".join(str(v) for v in value)
    return value


def write_csv(path: Path, records: Sequence) -> None:
    """Escribe registros dataclass a CSV UTF-8 con encabezado.

    Enums a ``.value``, fechas a ISO, ``None`` a "" y tuplas unidas con "|".
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        if not records:
            return
        writer = csv.writer(f)
        campos = [campo.name for campo in fields(records[0])]
        writer.writerow(campos)
        for record in records:
            writer.writerow([_csv_value(getattr(record, c)) for c in campos])
