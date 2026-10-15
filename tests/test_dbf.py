"""Pruebas del lector DBF (dBase III) sobre fixtures sintéticos."""

import io

import pytest
from dbfutil import write_dbf

from tucurul.geo.dbf import read_dbf, read_fields

FIELDS = [
    ("ID", "N", 8, 0),
    ("PESO", "N", 8, 2),
    ("NOMBRE", "C", 30, 0),
    ("ACTIVO", "L", 1, 0),
]

ROWS = [
    {"ID": 1, "PESO": 1.5, "NOMBRE": "AGUASCALIENTES", "ACTIVO": "T"},
    {"ID": 2, "PESO": 2.25, "NOMBRE": "CAÑADA MORELOS", "ACTIVO": "F"},
]


def _fixture(tmp_path):
    path = tmp_path / "test.dbf"
    path.write_bytes(write_dbf(FIELDS, ROWS))
    return path


def test_reads_fields(tmp_path):
    fields = read_fields(_fixture(tmp_path))
    assert [f.name for f in fields] == ["ID", "PESO", "NOMBRE", "ACTIVO"]
    assert fields[1].decimals == 2


def test_reads_rows_with_types(tmp_path):
    rows = list(read_dbf(_fixture(tmp_path)))
    assert rows[0] == {
        "ID": 1,
        "PESO": 1.5,
        "NOMBRE": "AGUASCALIENTES",
        "ACTIVO": True,
    }
    assert rows[1]["ID"] == 2
    assert rows[1]["ACTIVO"] is False


def test_cp1252_encoding(tmp_path):
    rows = list(read_dbf(_fixture(tmp_path)))
    assert rows[1]["NOMBRE"] == "CAÑADA MORELOS"


def test_skips_deleted_rows(tmp_path):
    path = tmp_path / "del.dbf"
    path.write_bytes(write_dbf(FIELDS, ROWS, deleted={1}))
    rows = list(read_dbf(path))
    assert len(rows) == 1
    assert rows[0]["ID"] == 1


def test_reads_from_file_object(tmp_path):
    path = _fixture(tmp_path)
    with open(path, "rb") as f:
        assert len(list(read_dbf(f))) == 2
    assert len(list(read_dbf(io.BytesIO(path.read_bytes())))) == 2


def test_rejects_non_dbf(tmp_path):
    path = tmp_path / "basura.dbf"
    path.write_bytes(b"esto no es dbf" * 10)
    with pytest.raises(ValueError):
        list(read_dbf(path))
