"""Lector mínimo de archivos DBF (dBase III) con la biblioteca estándar.

Formato (véase dBASE III File Structure):
- 32 bytes de encabezado: versión, fecha, número de registros (LE uint32),
  longitud del encabezado (LE uint16), longitud del registro (LE uint16) y
  el byte 29 con el identificador de página de códigos (LDID).
- Descriptores de campo de 32 bytes, terminados por 0x0D: nombre (11),
  tipo (1), longitud (1 en offset 16) y decimales (1 en offset 17).
- Registros consecutivos precedidos por la bandera de borrado (0x20 activo,
  0x2A eliminado); los eliminados se omiten.
"""

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

# LDID 0x57 = Windows ANSI Latin 1; el INE publica sus DBF en cp1252.
DEFAULT_ENCODING = "cp1252"

_HEADER_LEN = 32
_FIELD_DESC_LEN = 32
_FIELD_TERMINATOR = 0x0D
_DELETED_FLAG = 0x2A


@dataclass(frozen=True)
class DbfField:
    """Descriptor de una columna DBF."""

    name: str
    type: str
    length: int
    decimals: int


def _parse_value(field: DbfField, raw: bytes, encoding: str) -> Any:
    text = raw.decode(encoding).strip()
    if field.type == "N":
        if not text or text in ("*",):
            return None
        if field.decimals == 0:
            try:
                return int(text)
            except ValueError:
                return float(text)
        return float(text)
    if field.type == "F":
        if not text:
            return None
        return float(text)
    if field.type == "L":
        return {"T": True, "Y": True, "F": False, "N": False}.get(
            text.upper()[:1] or "?"
        )
    # C (texto), D (fecha AAAAMMDD, se deja como cadena), M/G/etc. sin decodificar.
    return text


def _open(source: str | Path | IO[bytes]) -> tuple[IO[bytes], bool]:
    if isinstance(source, (str, Path)):
        return open(source, "rb"), True
    return source, False


def read_dbf(
    source: str | Path | IO[bytes], encoding: str = DEFAULT_ENCODING
) -> Iterator[dict[str, Any]]:
    """Itera los registros activos de un DBF como dicts nombre_campo → valor."""
    f, should_close = _open(source)
    try:
        header = f.read(_HEADER_LEN)
        if len(header) < _HEADER_LEN or header[0] not in (0x02, 0x03, 0x30, 0x31, 0x83):
            raise ValueError("No es un archivo dBase III DBF válido")
        num_records = struct.unpack("<I", header[4:8])[0]
        header_len = struct.unpack("<H", header[8:10])[0]
        record_len = struct.unpack("<H", header[10:12])[0]

        fields: list[DbfField] = []
        while True:
            desc = f.read(_FIELD_DESC_LEN)
            if len(desc) < _FIELD_DESC_LEN:
                raise ValueError("Encabezado DBF truncado")
            if desc[0] == _FIELD_TERMINATOR:
                break
            fields.append(
                DbfField(
                    name=desc[0:11].split(b"\x00")[0].decode("ascii").strip(),
                    type=chr(desc[11]),
                    length=desc[16],
                    decimals=desc[17],
                )
            )

        f.seek(header_len)
        expected_len = 1 + sum(field.length for field in fields)
        for _ in range(num_records):
            record = f.read(record_len)
            if len(record) < record_len:
                raise ValueError("Registro DBF truncado")
            if len(record) < expected_len:
                raise ValueError("Longitud de registro incoherente con los campos")
            if record[0] == _DELETED_FLAG:
                continue
            offset = 1
            row: dict[str, Any] = {}
            for field in fields:
                raw = record[offset : offset + field.length]
                offset += field.length
                row[field.name] = _parse_value(field, raw, encoding)
            yield row
    finally:
        if should_close:
            f.close()


def read_fields(source: str | Path | IO[bytes]) -> list[DbfField]:
    """Devuelve los descriptores de campo de un DBF."""
    f, should_close = _open(source)
    try:
        f.seek(_HEADER_LEN)
        fields = []
        while True:
            desc = f.read(_FIELD_DESC_LEN)
            if len(desc) < _FIELD_DESC_LEN:
                raise ValueError("Encabezado DBF truncado")
            if desc[0] == _FIELD_TERMINATOR:
                break
            fields.append(
                DbfField(
                    name=desc[0:11].split(b"\x00")[0].decode("ascii").strip(),
                    type=chr(desc[11]),
                    length=desc[16],
                    decimals=desc[17],
                )
            )
        return fields
    finally:
        if should_close:
            f.close()
