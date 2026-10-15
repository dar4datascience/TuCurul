"""Escritor mínimo de DBF dBase III para fixtures de prueba."""

import struct
from collections.abc import Iterable
from typing import Any

# fields: iterable de (nombre, tipo, longitud, decimales)
FieldSpec = tuple[str, str, int, int]


def _format(value: Any, type_: str, length: int, encoding: str) -> bytes:
    if type_ in ("N", "F"):
        text = "" if value is None else str(value)
        return text.rjust(length).encode("ascii")
    if type_ == "L":
        return str(value or "?")[:1].encode("ascii").ljust(length, b" ")
    text = "" if value is None else str(value)
    return text.encode(encoding)[:length].ljust(length, b" ")


def write_dbf(
    fields: Iterable[FieldSpec],
    rows: list[dict],
    deleted: Iterable[int] = (),
    encoding: str = "cp1252",
) -> bytes:
    """Genera los bytes de un DBF; ``deleted`` marca índices borrados."""
    fields = list(fields)
    deleted = set(deleted)
    record_len = 1 + sum(length for _, _, length, _ in fields)
    header_len = 32 + 32 * len(fields) + 1

    buf = bytearray(32)
    buf[0] = 0x03
    buf[1:4] = bytes([126, 10, 14])  # fecha yy-mm-dd
    struct.pack_into("<I", buf, 4, len(rows))
    struct.pack_into("<H", buf, 8, header_len)
    struct.pack_into("<H", buf, 10, record_len)
    buf[29] = 0x57  # LDID: Windows ANSI (cp1252)

    out = bytearray(buf)
    for name, type_, length, decimals in fields:
        desc = bytearray(32)
        desc[0 : len(name)] = name.encode("ascii")[:11]
        desc[11] = ord(type_)
        desc[16] = length
        desc[17] = decimals
        out += desc
    out.append(0x0D)

    for i, row in enumerate(rows):
        out.append(0x2A if i in deleted else 0x20)
        for name, type_, length, _ in fields:
            out += _format(row.get(name), type_, length, encoding)
    out.append(0x1A)  # EOF
    return bytes(out)
