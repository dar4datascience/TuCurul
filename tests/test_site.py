"""Pruebas del sitio estático generado por build_site."""

import json
import re
import shutil
import subprocess

import pytest
from expected import EXPECTED_DL, EXPECTED_SECCIONES

from tucurul.coverage import CoverageRow, Status, render_html_table
from tucurul.geo.ine import SECCIONES_CSV
from tucurul.geo.seccion import IneMarcoGeograficoLocator
from tucurul.limits import MAX_SITE_FILE_BYTES
from tucurul.site import build_site
from tucurul.states import load_states


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not SECCIONES_CSV.exists():
        pytest.skip("data/ine/secciones.csv no generado; corre `tucurul ine-build`")
    out = tmp_path_factory.mktemp("site") / "site"
    return build_site(out)


def test_states_json(site):
    states = json.loads((site / "data" / "states.json").read_text("utf-8"))
    assert len(states) == 32
    for entry in states:
        clave = entry["clave"]
        assert entry["secciones"] == EXPECTED_SECCIONES[clave]
        assert entry["distritos_locales"] == EXPECTED_DL[clave]


def test_per_state_files_and_total_rows(site):
    files = sorted((site / "data" / "secciones").glob("*.json"))
    assert len(files) == 32
    total = sum(len(json.loads(f.read_text("utf-8"))["rows"]) for f in files)
    assert total == 71541


def test_round_trip_matches_locator(site):
    """Cada fila JSON decodificada equivale a locate() del catálogo."""
    locator = IneMarcoGeograficoLocator()
    n = 0
    for json_path in (site / "data" / "secciones").glob("*.json"):
        data = json.loads(json_path.read_text("utf-8"))
        assert data["columns"] == [
            "seccion", "distrito_federal", "distrito_local", "municipio",
        ]
        for seccion, df, dl, mun in data["rows"]:
            key = locator.locate(data["entidad"], seccion)
            assert (
                key.distrito_federal,
                key.distrito_local,
                key.municipio,
            ) == (df, dl, mun)
            assert key.municipio_nombre == data["municipios"][str(mun)]
            n += 1
    assert n == 71541


def _lookup(site, clave, seccion):
    data = json.loads(
        (site / "data" / "secciones" / f"{clave}.json").read_text("utf-8")
    )
    i = {c: data["columns"].index(c) for c in data["columns"]}
    for row in data["rows"]:
        if row[i["seccion"]] == seccion:
            return {
                "distrito_federal": row[i["distrito_federal"]],
                "distrito_local": row[i["distrito_local"]],
                "municipio": row[i["municipio"]],
                "municipio_nombre": data["municipios"][str(row[i["municipio"]])],
            }
    return None


def test_spot_checks_via_json(site):
    cdmx = _lookup(site, "09", 1)
    assert (cdmx["distrito_federal"], cdmx["distrito_local"]) == (3, 5)
    assert cdmx["municipio"] == 2 and cdmx["municipio_nombre"] == "AZCAPOTZALCO"
    nl = _lookup(site, "19", 1000)
    assert (nl["distrito_federal"], nl["distrito_local"]) == (6, 6)
    assert nl["municipio"] == 40 and nl["municipio_nombre"] == "MONTERREY"
    slp = _lookup(site, "24", 1)
    assert (slp["distrito_federal"], slp["distrito_local"], slp["municipio"]) == (
        1,
        2,
        1,
    )


def test_index_html_contents(site):
    html = (site / "index.html").read_text("utf-8")
    assert html.count('<tr class="fila-estado">') == 32
    assert "Ciudad de México" in html
    assert "{{" not in html  # todos los marcadores sustituidos
    # Sin rutas absolutas: el sitio vive bajo un subpath en GitHub Pages.
    assert not re.search(r'(?:src|href)="/', html)
    assert not re.search(r'fetch\(["\']/', html)


def test_nojekyll_and_metadata(site):
    assert (site / ".nojekyll").exists()
    meta = json.loads((site / "data" / "metadata.json").read_text("utf-8"))
    assert meta["corte"] == "2025-01-31"
    assert meta["rows"] == 71541


def test_js_has_no_absolute_fetch(site):
    for js in ("app.js", "lookup.js"):
        text = (site / js).read_text("utf-8")
        assert not re.search(r'fetch\(["\']/', text)
        assert 'from "/' not in text


def test_all_files_under_site_limit(site):
    for path in site.rglob("*"):
        if path.is_file():
            assert path.stat().st_size < MAX_SITE_FILE_BYTES, path


def test_max_file_bytes_guard(tmp_path):
    if not SECCIONES_CSV.exists():
        pytest.skip("catálogo INE no generado")
    with pytest.raises(ValueError, match="exceden"):
        build_site(tmp_path / "mini", max_file_bytes=1000)


def test_html_table_escapes_notes():
    row = CoverageRow(
        clave="01",
        statuses={d: Status.MISSING for d in ("a", "b")},
        notas="<script>alert(1)</script>",
    )
    html = render_html_table(
        rows=[row], states=[s for s in load_states() if s.clave == "01"]
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_lookup_js_with_node(site, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en PATH")
    script = tmp_path / "check.mjs"
    script.write_text(
        f"""
import {{ readFileSync }} from "node:fs";
import {{ findSeccion }} from "file://{site / 'lookup.js'}";

const nl = JSON.parse(readFileSync("{site}/data/secciones/19.json", "utf8"));
const cdmx = JSON.parse(readFileSync("{site}/data/secciones/09.json", "utf8"));
const slp = JSON.parse(readFileSync("{site}/data/secciones/24.json", "utf8"));

const checks = [
  [findSeccion(nl, 1000), [6, 6, 40, "MONTERREY"]],
  [findSeccion(cdmx, 1), [3, 5, 2, "AZCAPOTZALCO"]],
  [findSeccion(slp, 1), [1, 2, 1, "AHUALULCO"]],
];
for (const [r, [df, dl, mun, nom]] of checks) {{
  if (!r) throw new Error("findSeccion devolvió null");
  if (r.distrito_federal !== df || r.distrito_local !== dl ||
      r.municipio !== mun || r.municipio_nombre !== nom)
    throw new Error("Resultado incorrecto: " + JSON.stringify(r));
}}
if (findSeccion(nl, 999999) !== null) throw new Error("esperaba null");
console.log("findSeccion OK");
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [node, str(script)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "findSeccion OK" in proc.stdout


def test_cli_build_site_and_check_sizes(tmp_path, capsys):
    from tucurul.cli import main

    out = tmp_path / "sitio"
    main(["build-site", "--out", str(out)])
    assert (out / "index.html").exists()
    assert "Sitio generado" in capsys.readouterr().out

    main(["check-sizes"])
    assert "OK" in capsys.readouterr().out
