"""Cobertura de fuentes de información por entidad federativa.

Los datos viven en ``data/coverage.csv``: una fila por entidad y una columna
por dimensión de información, con el estado de consolidación de cada una.
"""

import csv
import html
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .geo.ine import SECCIONES_CSV
from .states import DATA_DIR, State, load_states


class Status(Enum):
    """Estado de consolidación de una dimensión en una entidad."""

    INGESTED = "ingested"
    SOURCE = "source"
    PARTIAL = "partial"
    MISSING = "missing"


STATUS_WEIGHT = {
    Status.INGESTED: 1.0,
    Status.SOURCE: 0.5,
    Status.PARTIAL: 0.25,
    Status.MISSING: 0.0,
}

STATUS_SYMBOL = {
    Status.INGESTED: "✅",
    Status.SOURCE: "🟡",
    Status.PARTIAL: "⚠️",
    Status.MISSING: "❌",
}

# Encabezados cortos para la tabla de Markdown; dimensiones desconocidas
# usan su nombre de columna.
DIMENSION_HEADERS = {
    "seccion_distrito_federal": "Sección→DF",
    "seccion_distrito_local": "Sección→DL",
    "senadores": "Senadores",
    "diputados_federales": "Dip. fed.",
    "votaciones_federales": "Votos fed.",
    "diputados_locales": "Dip. loc.",
    "votaciones_locales": "Votos loc.",
    "buscador_ople": "Buscador OPLE",
}

# Columnas que no son dimensiones.
META_COLUMNS = ("clave", "notas")


@dataclass(frozen=True)
class CoverageRow:
    """Estado de cobertura de una entidad."""

    clave: str
    statuses: dict[str, Status]
    notas: str


def load_coverage(path: Path | None = None) -> list[CoverageRow]:
    """Carga la cobertura desde ``data/coverage.csv`` (o ``path``).

    Las dimensiones son todas las columnas excepto ``clave`` y ``notas``.
    """
    csv_path = path or DATA_DIR / "coverage.csv"
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = []
        for raw in csv.DictReader(f):
            statuses = {
                col: Status(raw[col].strip())
                for col in raw
                if col not in META_COLUMNS
            }
            rows.append(
                CoverageRow(
                    clave=raw["clave"].strip(),
                    statuses=statuses,
                    notas=(raw.get("notas") or "").strip(),
                )
            )
    return rows


def score(row: CoverageRow) -> float:
    """Completitud de una fila: media de pesos por dimensión, en porcentaje."""
    weights = [STATUS_WEIGHT[status] for status in row.statuses.values()]
    return sum(weights) / len(weights) * 100


def _short_header(dimension: str) -> str:
    return DIMENSION_HEADERS.get(dimension, dimension.replace("_", " "))


def _load_geo_stats(path: Path) -> dict[str, tuple[int, int]] | None:
    """Cuenta secciones y distritos locales por entidad desde el catálogo INE.

    Devuelve ``None`` si ``data/ine/secciones.csv`` no existe aún.
    """
    if not path.exists():
        return None
    secciones: dict[str, int] = {}
    distritos: dict[str, set[int]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            clave = row["entidad"]
            secciones[clave] = secciones.get(clave, 0) + 1
            distritos.setdefault(clave, set()).add(int(row["distrito_local"]))
    return {
        clave: (secciones[clave], len(distritos[clave])) for clave in secciones
    }


def render_markdown_table(
    rows: list[CoverageRow] | None = None,
    states: list[State] | None = None,
    geo_path: Path | None = None,
) -> str:
    """Genera la tabla de cobertura en Markdown, lista para el README."""
    rows = rows if rows is not None else load_coverage()
    states = states if states is not None else load_states()
    geo = _load_geo_stats(geo_path or SECCIONES_CSV)
    by_clave = {s.clave: s for s in states}
    dimensions = list(rows[0].statuses) if rows else []

    header = (
        "| Clave | Estado | Dist. fed. | Secciones | Dist. loc. | "
        + " | ".join(_short_header(d) for d in dimensions)
        + " | Completitud | Notas |"
    )
    separator = "|" + "---|" * (5 + len(dimensions) + 2)

    lines = [header, separator]
    for row in rows:
        state = by_clave[row.clave]
        if geo and row.clave in geo:
            n_secciones, n_dl = geo[row.clave]
            geo_cells = [str(n_secciones), str(n_dl)]
        else:
            geo_cells = ["—", "—"]
        cells = [STATUS_SYMBOL[row.statuses[d]] for d in dimensions]
        lines.append(
            f"| {row.clave} | {state.nombre} | {state.distritos_federales} | "
            + " | ".join(geo_cells)
            + " | "
            + " | ".join(cells)
            + f" | {score(row):.1f}% | {row.notas} |"
        )

    total_distritos = sum(s.distritos_federales for s in states)
    total_senadores = sum(s.senadores for s in states)
    if geo:
        geo_totals = [
            f"**{sum(n for n, _ in geo.values())}**",
            f"**{sum(d for _, d in geo.values())}**",
        ]
    else:
        geo_totals = ["—", "—"]
    lines.append(
        f"| **Σ** | **{len(states)} entidades** | **{total_distritos}** | "
        + " | ".join(geo_totals)
        + " | "
        + " | ".join("—" for _ in dimensions)
        + " | | |"
    )
    lines.append("")
    lines.append(
        f"**Senadores por entidad:** {total_senadores} "
        "(2 de mayoría relativa + 1 de primera minoría por entidad) "
        "+ 32 de representación proporcional = **128 curules**."
    )
    lines.append("")
    lines.append(
        "**Leyenda:** ✅ datos ingeridos · 🟡 fuente identificada · "
        "⚠️ cobertura parcial · ❌ sin fuente"
    )
    return "\n".join(lines)


def render_html_table(
    rows: list[CoverageRow] | None = None,
    states: list[State] | None = None,
    geo_path: Path | None = None,
) -> str:
    """Genera la tabla de cobertura en HTML (escapada) para el sitio estático."""
    rows = rows if rows is not None else load_coverage()
    states = states if states is not None else load_states()
    geo = _load_geo_stats(geo_path or SECCIONES_CSV)
    by_clave = {s.clave: s for s in states}
    dimensions = list(rows[0].statuses) if rows else []

    headers = (
        ["Clave", "Entidad", "Dist. fed.", "Secciones", "Dist. loc."]
        + [_short_header(d) for d in dimensions]
        + ["Completitud", "Notas"]
    )
    lines = ['<table class="cobertura">', "<thead>", "<tr>"]
    lines += [f"<th>{html.escape(h)}</th>" for h in headers]
    lines += ["</tr>", "</thead>", "<tbody>"]

    for row in rows:
        state = by_clave[row.clave]
        if geo and row.clave in geo:
            n_secciones, n_dl = geo[row.clave]
            geo_cells = [str(n_secciones), str(n_dl)]
        else:
            geo_cells = ["—", "—"]
        cells = (
            [
                row.clave,
                state.nombre,
                str(state.distritos_federales),
            ]
            + geo_cells
            + [STATUS_SYMBOL[row.statuses[d]] for d in dimensions]
            + [f"{score(row):.1f}%", row.notas]
        )
        lines.append('<tr class="fila-estado">')
        lines += [f"<td>{html.escape(cell)}</td>" for cell in cells]
        lines.append("</tr>")
    lines.append("</tbody>")

    total_distritos = sum(s.distritos_federales for s in states)
    if geo:
        geo_totals = [
            str(sum(n for n, _ in geo.values())),
            str(sum(d for _, d in geo.values())),
        ]
    else:
        geo_totals = ["—", "—"]
    lines += ["<tfoot>", '<tr class="fila-total">']
    lines += [
        f"<td>{html.escape(c)}</td>"
        for c in ["Σ", f"{len(states)} entidades", str(total_distritos)]
        + geo_totals
        + ["—"] * len(dimensions)
        + ["", ""]
    ]
    lines += ["</tr>", "</tfoot>", "</table>"]
    return "\n".join(lines)
