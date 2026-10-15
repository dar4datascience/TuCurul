"""Pruebas de los límites de tamaño (GitHub / política del proyecto)."""

import pytest
from expected import make_archive, valid_fixture_rows

from tucurul.geo import ine
from tucurul.limits import (
    GITHUB_HARD_LIMIT_BYTES,
    GITHUB_WARN_BYTES,
    MAX_SITE_FILE_BYTES,
    MAX_TRACKED_DATA_BYTES,
    human_size,
    oversized_files,
)
from tucurul.states import DATA_DIR


def test_constants():
    assert GITHUB_WARN_BYTES == 50 * 1024 * 1024
    assert GITHUB_HARD_LIMIT_BYTES == 100 * 1024 * 1024
    assert MAX_TRACKED_DATA_BYTES == 25 * 1024 * 1024
    assert MAX_SITE_FILE_BYTES == 5 * 1024 * 1024
    # La política propia debe ser más estricta que la de GitHub.
    assert MAX_TRACKED_DATA_BYTES < GITHUB_WARN_BYTES < GITHUB_HARD_LIMIT_BYTES


def test_oversized_files(tmp_path):
    (tmp_path / "chico.txt").write_bytes(b"x" * 10)
    (tmp_path / "grande.bin").write_bytes(b"x" * 2000)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "gigante.bin").write_bytes(b"x" * 5000)

    found = oversized_files(tmp_path, limit=1000)
    assert [rel.name for rel, _ in found] == ["grande.bin"]
    assert found[0][1] == 2000
    # "raw" se excluye por defecto; sin exclusión sí aparece.
    found_all = oversized_files(tmp_path, limit=1000, exclude=())
    assert {rel.name for rel, _ in found_all} == {"grande.bin", "gigante.bin"}


def test_repo_data_within_limits():
    oversized = oversized_files(DATA_DIR, MAX_TRACKED_DATA_BYTES)
    assert oversized == []


def test_human_size():
    assert human_size(500) == "500 B"
    assert human_size(2048) == "2.0 KiB"
    assert human_size(3 * 1024 * 1024) == "3.0 MiB"


def test_build_catalog_refuses_oversized(tmp_path, monkeypatch):
    pytest.importorskip("py7zr")
    secc_rows, muni_rows = valid_fixture_rows()
    archive = make_archive(tmp_path, secc_rows, muni_rows)
    out = tmp_path / "out"
    monkeypatch.setattr(ine, "MAX_TRACKED_DATA_BYTES", 100)
    with pytest.raises(ValueError, match="límite"):
        ine.build_catalog(archive, out)
    # No debe quedar nada escrito tras el rechazo.
    assert not (out / "secciones.csv").exists()
