"""Pruebas del catálogo INE generado (data/ine/secciones.csv) y de la ingesta."""

import csv
import json
from collections import Counter, defaultdict

import pytest
from expected import EXPECTED_DL, EXPECTED_SECCIONES, make_archive, valid_fixture_rows

from tucurul.geo.ine import INE_DIR, SECCIONES_CSV, build_catalog
from tucurul.geo.seccion import IneMarcoGeograficoLocator
from tucurul.states import load_states


@pytest.fixture(scope="module")
def catalog():
    if not SECCIONES_CSV.exists():
        pytest.skip("data/ine/secciones.csv no generado; corre `tucurul ine-build`")
    with open(SECCIONES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_row_count(catalog):
    assert len(catalog) == 71541


def test_32_entidades(catalog):
    assert {r["entidad"] for r in catalog} == {s.clave for s in load_states()}


def test_unique_entidad_seccion(catalog):
    keys = [(r["entidad"], r["seccion"]) for r in catalog]
    assert len(set(keys)) == len(keys)


def test_no_missing_municipio_nombre(catalog):
    assert all(r["municipio_nombre"] for r in catalog)


def test_distritos_federales_match_states(catalog):
    df = defaultdict(set)
    for r in catalog:
        df[r["entidad"]].add(int(r["distrito_federal"]))
    for s in load_states():
        assert len(df[s.clave]) == s.distritos_federales, s.clave


def test_distritos_locales_per_entidad(catalog):
    dl = defaultdict(set)
    for r in catalog:
        dl[r["entidad"]].add(int(r["distrito_local"]))
    assert {c: len(v) for c, v in dl.items()} == EXPECTED_DL


def test_seccion_counts_per_entidad(catalog):
    counts = Counter(r["entidad"] for r in catalog)
    assert dict(counts) == EXPECTED_SECCIONES


@pytest.fixture(scope="module")
def locator(catalog):
    return IneMarcoGeograficoLocator()


def test_spot_checks(locator):
    key = locator.locate("24", 1)
    assert (key.distrito_federal, key.distrito_local, key.municipio) == (1, 2, 1)
    key = locator.locate("27", 1)
    assert (key.distrito_federal, key.distrito_local) == (1, 21)
    key = locator.locate("03", 1)
    assert (key.distrito_federal, key.distrito_local) == (1, 10)


def test_metadata_json():
    meta = json.loads((INE_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert meta["source_url"].startswith("https://cartografia.ine.mx/")
    assert meta["corte"] == "2025-01-31"
    assert meta["rows"] == 71541
    assert meta["archive_size_bytes"] == 85681402


# --- build_catalog sobre un .7z sintético (requiere el extra `ingest`) ---


def test_build_catalog_end_to_end(tmp_path):
    pytest.importorskip("py7zr")
    secc_rows, muni_rows = valid_fixture_rows()
    archive = make_archive(tmp_path, secc_rows, muni_rows)
    out = tmp_path / "out"
    csv_path = build_catalog(archive, out)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 300  # una sección por distrito federal
    assert rows[0]["entidad"] == "01"
    assert rows[0]["municipio_nombre"] == "MPIÓ 01"
    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert meta["rows"] == 300
    assert meta["corte"] == "2025-01-31"
    assert len(meta["archive_sha256"]) == 64


def test_build_catalog_rejects_missing_entidad(tmp_path):
    pytest.importorskip("py7zr")
    secc_rows, muni_rows = valid_fixture_rows()
    secc_rows = [r for r in secc_rows if r["ENTIDAD"] != 32]
    archive = make_archive(tmp_path, secc_rows, muni_rows)
    with pytest.raises(ValueError, match="32"):
        build_catalog(archive, tmp_path / "out")
