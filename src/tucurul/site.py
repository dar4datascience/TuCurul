"""Generación del sitio estático para GitHub Pages.

Produce un directorio desplegable tal cual: HTML/CSS/JS sin herramientas de
construcción y JSON compactos por entidad. Todas las URLs de recursos y
datos son relativas, para funcionar bajo un subpath (p. ej.
``https://dar4datascience.github.io/TuCurul/``).
"""

import csv
import html
import json
import shutil
from pathlib import Path

from .coverage import render_html_table
from .geo.ine import INE_DIR, SECCIONES_CSV, SOURCE_URL
from .limits import MAX_SITE_FILE_BYTES
from .states import load_states

ASSETS_DIR = Path(__file__).resolve().parent / "site_assets"
_STATIC_FILES = ("app.js", "lookup.js", "style.css")
_JSON_SEPARATORS = (",", ":")


def _load_catalog(catalog: Path) -> dict[str, dict]:
    """Lee secciones.csv y la agrupa por entidad."""
    entidades: dict[str, dict] = {}
    with open(catalog, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ent = entidades.setdefault(row["entidad"], {"rows": [], "municipios": {}})
            municipio = int(row["municipio"])
            ent["rows"].append(
                [
                    int(row["seccion"]),
                    int(row["distrito_federal"]),
                    int(row["distrito_local"]),
                    municipio,
                ]
            )
            ent["municipios"][str(municipio)] = row["municipio_nombre"]
    return entidades


def build_site(
    out_dir: Path,
    *,
    catalog: Path = SECCIONES_CSV,
    max_file_bytes: int = MAX_SITE_FILE_BYTES,
) -> Path:
    """Genera el sitio estático en ``out_dir`` (borra y recrea ese directorio).

    Lanza ``ValueError`` si algún archivo generado excede ``max_file_bytes``.
    """
    catalog = Path(catalog)
    out_dir = Path(out_dir)
    if not catalog.exists():
        raise FileNotFoundError(
            f"No existe {catalog}; ejecuta `tucurul ine-build` primero."
        )

    if out_dir.exists():
        shutil.rmtree(out_dir)
    secciones_dir = out_dir / "data" / "secciones"
    secciones_dir.mkdir(parents=True)

    # Datos JSON por entidad y resumen de entidades.
    entidades = _load_catalog(catalog)
    states_payload = []
    for state in load_states():
        data = entidades.get(state.clave, {"rows": [], "municipios": {}})
        rows = data["rows"]
        dls = {r[2] for r in rows}
        states_payload.append(
            {
                "clave": state.clave,
                "nombre": state.nombre,
                "abreviatura": state.abreviatura,
                "distritos_federales": state.distritos_federales,
                "secciones": len(rows),
                "distritos_locales": len(dls),
            }
        )
        payload = {
            "entidad": state.clave,
            "columns": [
                "seccion",
                "distrito_federal",
                "distrito_local",
                "municipio",
            ],
            "municipios": data["municipios"],
            "rows": rows,
        }
        (secciones_dir / f"{state.clave}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=_JSON_SEPARATORS),
            encoding="utf-8",
        )
    (out_dir / "data" / "states.json").write_text(
        json.dumps(states_payload, ensure_ascii=False, separators=_JSON_SEPARATORS),
        encoding="utf-8",
    )

    # Metadatos de procedencia del catálogo.
    meta_path = INE_DIR / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = {"corte": "desconocido", "source_url": SOURCE_URL}
    (out_dir / "data" / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Assets estáticos; index.html es una plantilla con marcadores {{X}}.
    index = (ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    index = (
        index.replace("{{COBERTURA}}", render_html_table())
        .replace("{{CORTE}}", html.escape(str(meta.get("corte", "desconocido"))))
        .replace("{{FUENTE_URL}}", html.escape(str(meta.get("source_url", SOURCE_URL))))
    )
    (out_dir / "index.html").write_text(index, encoding="utf-8")
    for name in _STATIC_FILES:
        shutil.copy2(ASSETS_DIR / name, out_dir / name)
    (out_dir / ".nojekyll").write_bytes(b"")

    oversized = [
        (p.relative_to(out_dir), p.stat().st_size)
        for p in sorted(out_dir.rglob("*"))
        if p.is_file() and p.stat().st_size > max_file_bytes
    ]
    if oversized:
        detalle = ", ".join(f"{rel} ({size} B)" for rel, size in oversized)
        raise ValueError(
            f"Archivos del sitio exceden {max_file_bytes} bytes: {detalle}"
        )
    return out_dir
