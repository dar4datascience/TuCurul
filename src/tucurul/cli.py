"""Línea de comandos ``tucurul``."""

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from .coverage import load_coverage, render_markdown_table
from .geo.ine import (
    DEFAULT_CORTE,
    INE_DIR,
    RAW_DIR,
    build_catalog,
    download_archive,
)
from .geo.seccion import IneMarcoGeograficoLocator
from .limits import MAX_TRACKED_DATA_BYTES, human_size, oversized_files
from .site import build_site
from .sources.http import CacheMode, FetchError, HttpClient
from .sources.models import write_csv
from .sources.sitl_diputados import (
    BASE_URL as SITL_BASE_URL,
)
from .sources.sitl_diputados import (
    DIRECTORIO_URL,
    PERIODOS_URL,
    SitlDiputados,
    validar_sitl,
)
from .sources.sitl_diputados import (
    LEGISLATURA as SITL_LEGISLATURA,
)
from .states import DATA_DIR, get_state, load_states

COVERAGE_START = "<!-- coverage:start -->"
COVERAGE_END = "<!-- coverage:end -->"
README_PATH = DATA_DIR.parent / "README.md"


def update_readme(path: Path) -> bool:
    """Reescribe la sección de cobertura del README entre los marcadores.

    Devuelve ``True`` si el archivo cambió; es idempotente.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if COVERAGE_START not in text or COVERAGE_END not in text:
        raise ValueError(
            f"{path} no contiene los marcadores {COVERAGE_START} / {COVERAGE_END}"
        )
    before, _, rest = text.partition(COVERAGE_START)
    _, _, after = rest.partition(COVERAGE_END)
    section = f"{COVERAGE_START}\n\n{render_markdown_table()}\n\n{COVERAGE_END}"
    new_text = before + section + after
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tucurul",
        description="¿Quién me representa y cómo vota?",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("states", help="Lista las 32 entidades federativas")
    sub.add_parser(
        "coverage", help="Imprime la tabla de cobertura por estado en Markdown"
    )
    upd = sub.add_parser(
        "update-readme",
        help="Actualiza la tabla de cobertura del README (entre marcadores)",
    )
    upd.add_argument(
        "--path",
        type=Path,
        default=README_PATH,
        help="Ruta del README (por defecto, la del repositorio)",
    )
    ine = sub.add_parser(
        "ine-build",
        help="Genera data/ine/secciones.csv desde el Marco Geográfico INE",
    )
    ine.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Ruta a SHAPEFILE.7z ya descargado "
        f"(si se omite se descarga a {RAW_DIR})",
    )
    ine.add_argument(
        "--out",
        type=Path,
        default=INE_DIR,
        help="Directorio de salida (por defecto data/ine/)",
    )
    ine.add_argument(
        "--corte",
        default=None,
        help=f"Fecha de corte ISO (por defecto {DEFAULT_CORTE}; al descargar "
        "se usa el Last-Modified del servidor)",
    )
    loc = sub.add_parser(
        "locate",
        help="Resuelve entidad + sección INE a distritos y municipio",
    )
    loc.add_argument("entidad", help="Clave INE ('09') o abreviatura ('CDMX')")
    loc.add_argument("seccion", type=int, help="Número de sección electoral")
    site = sub.add_parser(
        "build-site",
        help="Genera el sitio estático para GitHub Pages",
    )
    site.add_argument(
        "--out",
        type=Path,
        default=DATA_DIR.parent / "site",
        help="Directorio de salida (por defecto ./site)",
    )
    sub.add_parser(
        "check-sizes",
        help="Verifica que data/ no exceda los límites de tamaño de GitHub",
    )
    sitl = sub.add_parser(
        "sitl-ingest",
        help="Ingesta el SITL LXVI: directorio de diputados y votaciones",
    )
    sitl.add_argument(
        "--out",
        type=Path,
        default=DATA_DIR / "sitl_diputados",
        help="Directorio de salida (por defecto data/sitl_diputados/)",
    )
    sitl.add_argument(
        "--offline",
        action="store_true",
        help="Solo caché en data/raw/, sin red",
    )
    sitl.add_argument(
        "--refresh",
        action="store_true",
        help="Ignora la caché y vuelve a descargar todo",
    )
    sitl.add_argument(
        "--max-votaciones",
        type=int,
        default=None,
        help="Procesa como máximo N votaciones (para pruebas)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "states":
        for state in load_states():
            print(
                f"{state.clave}  {state.abreviatura:<5} {state.nombre:<22} "
                f"distritos fed.: {state.distritos_federales:>2}  "
                f"senadores: {state.senadores}"
            )
    elif args.command == "coverage":
        print(render_markdown_table(load_coverage()))
    elif args.command == "update-readme":
        changed = update_readme(args.path)
        print(f"{args.path}: {'actualizado' if changed else 'sin cambios'}")
    elif args.command == "ine-build":
        corte = args.corte
        if args.archive is not None:
            archive = args.archive
        else:
            archive, last_modified = download_archive(RAW_DIR / "SHAPEFILE.7z")
            print(f"Descargado: {archive}")
            corte = corte or last_modified
        csv_path = build_catalog(
            archive, args.out, corte=corte or DEFAULT_CORTE
        )
        print(f"Catálogo escrito en {csv_path}")
    elif args.command == "locate":
        try:
            key = IneMarcoGeograficoLocator().locate(args.entidad, args.seccion)
        except FileNotFoundError:
            print(
                "No existe el catálogo data/ine/secciones.csv; "
                "ejecuta `tucurul ine-build` primero.",
                file=sys.stderr,
            )
            raise SystemExit(2) from None
        except KeyError as e:  # incluye SeccionNoEncontrada y entidad inválida
            print(f"Error: {e.args[0]}", file=sys.stderr)
            raise SystemExit(2) from None
        state = get_state(key.entidad)
        print(f"Entidad:          {key.entidad} — {state.nombre}")
        print(f"Sección:          {key.seccion}")
        print(f"Distrito federal: {key.distrito_federal}")
        print(f"Distrito local:   {key.distrito_local}")
        print(f"Municipio:        {key.municipio} — {key.municipio_nombre}")
    elif args.command == "build-site":
        out = build_site(args.out)
        print(f"Sitio generado en {out}")
    elif args.command == "check-sizes":
        oversized = oversized_files(DATA_DIR, MAX_TRACKED_DATA_BYTES)
        if oversized:
            print(
                f"Archivos de data/ sobre {human_size(MAX_TRACKED_DATA_BYTES)}:",
                file=sys.stderr,
            )
            for rel, size in oversized:
                print(f"  {rel}: {human_size(size)}", file=sys.stderr)
            raise SystemExit(1)
        print(
            f"OK: ningún archivo de data/ excede "
            f"{human_size(MAX_TRACKED_DATA_BYTES)}."
        )
    elif args.command == "sitl-ingest":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        mode = (
            CacheMode.OFFLINE
            if args.offline
            else CacheMode.REFRESH
            if args.refresh
            else CacheMode.NORMAL
        )
        client = HttpClient("sitl_diputados", mode=mode)
        fuente = SitlDiputados(
            client=client, max_votaciones=args.max_votaciones
        )
        # La conectividad con diputados.gob.mx es intermitente; la caché
        # hace que cada reintento retome donde quedó.
        datos = None
        for intento in range(1, 4):
            try:
                datos = fuente.fetch()
                break
            except FetchError as e:
                if intento == 3:
                    raise
                print(
                    f"Intento {intento} falló ({e}); reintentando "
                    "desde la caché…",
                    file=sys.stderr,
                )
                time.sleep(30)
        client.close()

        args.out.mkdir(parents=True, exist_ok=True)
        write_csv(args.out / "legisladores.csv", datos.legisladores)
        write_csv(args.out / "votaciones.csv", datos.votaciones)
        write_csv(args.out / "totales_grupo.csv", datos.totales)
        write_csv(args.out / "votos.csv", datos.votos)

        validacion = validar_sitl(datos)
        metadata = {
            "source": "sitl_diputados",
            "legislatura": SITL_LEGISLATURA,
            "base_url": SITL_BASE_URL,
            "source_urls": [DIRECTORIO_URL, PERIODOS_URL],
            "fetched_at": datetime.now(UTC).isoformat(),
            "counts": {
                "legisladores": len(datos.legisladores),
                "votaciones": len(datos.votaciones),
                "totales_grupo": len(datos.totales),
                "votos": len(datos.votos),
            },
            "validacion": validacion,
        }
        (args.out / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"SITL {SITL_LEGISLATURA}: {len(datos.legisladores)} legisladores, "
            f"{len(datos.votaciones)} votaciones, "
            f"{len(datos.totales)} totales por grupo, "
            f"{len(datos.votos)} votos → {args.out}"
        )
        mismatches = validacion["votos_vs_totales"]["mismatches"]
        if mismatches:
            print(
                f"Desajustes votos vs estadístico ({len(mismatches)}):",
                file=sys.stderr,
            )
            for m in mismatches[:50]:
                print(f"  {m}", file=sys.stderr)
            if len(mismatches) > 50:
                print(f"  ... y {len(mismatches) - 50} más", file=sys.stderr)
        if not validacion["ok"]:
            print(
                "Validación estructural fallida; ver metadata.json",
                file=sys.stderr,
            )
            raise SystemExit(1)


if __name__ == "__main__":
    main()
