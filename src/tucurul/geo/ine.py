"""Ingesta del Marco Geográfico Seccional (MGS) del INE.

El MGS publica la cartografía electoral nacional; sus tablas DBF relacionan
entidad + sección con distrito federal, distrito local y municipio. De ellas
se genera ``data/ine/secciones.csv``, el catálogo que usa
:class:`tucurul.geo.seccion.IneMarcoGeograficoLocator`.

Nota: la columna ``municipio`` usa la **clave municipal del INE**
(consecutiva por entidad), no la clave INEGI de dos dígitos.
"""

import csv
import hashlib
import io
import json
import tempfile
import urllib.request
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from ..limits import MAX_TRACKED_DATA_BYTES
from ..states import DATA_DIR, load_states
from .dbf import read_dbf

SOURCE_URL = "https://cartografia.ine.mx/mapoteca/MGS_CCL/SHAPEFILE.7z"
DEFAULT_CORTE = "2025-01-31"
RAW_DIR = DATA_DIR / "raw"
INE_DIR = DATA_DIR / "ine"
SECCIONES_CSV = INE_DIR / "secciones.csv"

_ARCHIVE_MEMBERS = ("SECCION.dbf", "MUNICIPIO.dbf")
_CHUNK_SIZE = 1 << 20
CSV_FIELDS = (
    "entidad",
    "seccion",
    "distrito_federal",
    "distrito_local",
    "municipio",
    "municipio_nombre",
    "tipo",
)


def download_archive(dest: Path, url: str = SOURCE_URL) -> tuple[Path, str | None]:
    """Descarga el archivo MGS a ``dest`` en streaming.

    Devuelve ``(ruta, corte)`` donde ``corte`` es la fecha ISO del encabezado
    HTTP ``Last-Modified`` (o ``None`` si el servidor no lo envía).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "tucurul/0.1"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as out:
        last_modified = resp.headers.get("Last-Modified")
        while chunk := resp.read(_CHUNK_SIZE):
            out.write(chunk)
    corte = None
    if last_modified:
        corte = parsedate_to_datetime(last_modified).date().isoformat()
    return dest, corte


def _join(secciones: list[dict], municipios: list[dict]) -> list[dict]:
    nombres = {
        (int(m["ENTIDAD"]), int(m["MUNICIPIO"])): str(m["NOMBRE"])
        for m in municipios
    }
    rows = []
    for s in secciones:
        entidad = int(s["ENTIDAD"])
        municipio = int(s["MUNICIPIO"])
        rows.append(
            {
                "entidad": f"{entidad:02d}",
                "seccion": int(s["SECCION"]),
                "distrito_federal": int(s["DISTRITO_F"]),
                "distrito_local": int(s["DISTRITO_L"]),
                "municipio": municipio,
                "municipio_nombre": nombres.get((entidad, municipio), ""),
                "tipo": int(s["TIPO"]),
            }
        )
    rows.sort(key=lambda r: (r["entidad"], r["seccion"]))
    return rows


def validate_rows(rows: list[dict]) -> None:
    """Valida el catálogo contra invariantes conocidas; lanza ``ValueError``."""
    if not rows:
        raise ValueError("Catálogo vacío")

    claves = {s.clave for s in load_states()}
    entidades = {r["entidad"] for r in rows}
    if len(entidades) != 32 or entidades != claves:
        raise ValueError(
            f"Entidades en el catálogo ({sorted(entidades)}) no coinciden "
            "con las 32 de states.csv"
        )

    keys = [(r["entidad"], r["seccion"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Pares (entidad, sección) duplicados en el catálogo")

    sin_nombre = [k for k, r in zip(keys, rows) if not r["municipio_nombre"]]
    if sin_nombre:
        raise ValueError(
            f"Secciones sin nombre de municipio: {sin_nombre[:5]}…"
        )

    df_esperado = {s.clave: s.distritos_federales for s in load_states()}
    df_real: dict[str, set[int]] = {}
    for r in rows:
        df_real.setdefault(r["entidad"], set()).add(r["distrito_federal"])
    mal = {
        c: (len(df_real.get(c, set())), n)
        for c, n in df_esperado.items()
        if len(df_real.get(c, set())) != n
    }
    if mal:
        raise ValueError(
            "Distritos federales distintos por entidad != states.csv: " f"{mal}"
        )


def build_catalog(
    archive: Path, out_dir: Path, *, corte: str = DEFAULT_CORTE
) -> Path:
    """Extrae SECCION/MUNICIPIO del MGS y escribe ``secciones.csv`` + metadatos.

    Requiere el extra ``ingest`` (``uv sync --extra ingest``). Rechaza escribir
    un ``secciones.csv`` por encima de ``MAX_TRACKED_DATA_BYTES``.
    """
    archive = Path(archive)
    out_dir = Path(out_dir)
    try:
        import py7zr
    except ImportError as e:
        raise ImportError(
            "Se requiere py7zr para leer el .7z del INE: "
            "`uv sync --extra ingest`"
        ) from e

    with tempfile.TemporaryDirectory() as tmp:
        with py7zr.SevenZipFile(archive) as z:
            z.extract(tmp, targets=list(_ARCHIVE_MEMBERS))
        secciones = list(read_dbf(Path(tmp) / "SECCION.dbf"))
        municipios = list(read_dbf(Path(tmp) / "MUNICIPIO.dbf"))

    rows = _join(secciones, municipios)
    validate_rows(rows)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    payload = buffer.getvalue().encode("utf-8")
    if len(payload) > MAX_TRACKED_DATA_BYTES:
        raise ValueError(
            f"secciones.csv pesaría {len(payload)} bytes, más que el límite "
            f"de datos versionados ({MAX_TRACKED_DATA_BYTES} bytes); "
            "no se escribe nada"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "secciones.csv"
    csv_path.write_bytes(payload)

    sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    metadata = {
        "source_url": SOURCE_URL,
        "archive_sha256": sha256,
        "archive_size_bytes": archive.stat().st_size,
        "corte": corte,
        "rows": len(rows),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return csv_path
