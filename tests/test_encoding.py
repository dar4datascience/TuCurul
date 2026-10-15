"""Detección de codificación: UTF-8, BOM y la familia latin-1/cp1252."""

from tucurul.sources.http import decode, detect_encoding

NOMBRE = "Gómez Núñez Peña"
PAGINA = f"<html><body><p>{NOMBRE}</p></body></html>"


def test_utf8():
    texto, enc = decode(PAGINA.encode("utf-8"))
    assert enc == "utf-8"
    assert NOMBRE in texto


def test_utf8_bom():
    texto, enc = decode(PAGINA.encode("utf-8-sig"))
    assert enc == "utf-8"
    assert texto.startswith("<")  # BOM quitado
    assert NOMBRE in texto


def test_utf16_bom():
    texto, enc = decode(PAGINA.encode("utf-16"))
    assert enc == "utf-16"
    assert NOMBRE in texto


def test_cp1252_con_meta_charset():
    raw = (
        '<html><head><meta charset="iso-8859-1"></head>'
        f"<body><p>{NOMBRE}</p></body></html>"
    )
    texto, enc = decode(raw.encode("cp1252"))
    assert enc == "cp1252"
    assert NOMBRE in texto


def test_cp1252_con_meta_http_equiv():
    raw = (
        '<html><head><meta http-equiv="Content-Type" '
        'content="text/html; charset=iso-8859-1"></head>'
        f"<body><p>{NOMBRE}</p></body></html>"
    )
    texto, enc = decode(raw.encode("cp1252"))
    assert enc == "cp1252"
    assert NOMBRE in texto


def test_cp1252_con_header():
    texto, enc = decode(
        PAGINA.encode("cp1252"), "text/html; charset=ISO-8859-1"
    )
    assert enc == "cp1252"
    assert NOMBRE in texto


def test_cp1252_sin_declarar():
    assert detect_encoding(PAGINA.encode("cp1252")) == "cp1252"
    texto, _ = decode(PAGINA.encode("cp1252"))
    assert NOMBRE in texto


def test_utf8_en_pagina_que_declara_latin1():
    """Los listados del SITL dicen iso-8859-1 pero traen UTF-8 real."""
    raw = (
        '<html><head><meta charset="iso-8859-1"></head>'
        f"<body><p>{NOMBRE}</p></body></html>"
    )
    texto, enc = decode(
        raw.encode("utf-8"), "text/html; charset=iso-8859-1"
    )
    assert enc == "utf-8"
    assert NOMBRE in texto
    assert "Ã³" not in texto
