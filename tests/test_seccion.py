"""Pruebas del localizador de secciones sobre un catálogo fixture."""

import pytest

from tucurul.geo.seccion import (
    IneMarcoGeograficoLocator,
    RepresentationKey,
    SeccionNoEncontrada,
)

CATALOG = """entidad,seccion,distrito_federal,distrito_local,municipio,municipio_nombre,tipo
24,1,1,2,1,AHUALULCO,2
24,2,1,2,1,AHUALULCO,2
09,1,3,5,2,AZCAPOTZALCO,2
"""


@pytest.fixture()
def locator(tmp_path):
    path = tmp_path / "secciones.csv"
    path.write_text(CATALOG, encoding="utf-8")
    return IneMarcoGeograficoLocator(path)


def test_locate_returns_key(locator):
    key = locator.locate("24", 1)
    assert key == RepresentationKey(
        entidad="24",
        seccion=1,
        distrito_federal=1,
        distrito_local=2,
        municipio=1,
        municipio_nombre="AHUALULCO",
    )


def test_locate_accepts_abbreviation(locator):
    assert locator.locate("SLP", 2) == locator.locate("24", 2)


def test_locate_accepts_unpadded_clave(locator):
    assert locator.locate("9", 1).municipio_nombre == "AZCAPOTZALCO"
    assert locator.locate("CDMX", 1).distrito_local == 5


def test_unknown_seccion_raises(locator):
    with pytest.raises(SeccionNoEncontrada):
        locator.locate("24", 99)
    # SeccionNoEncontrada es una KeyError.
    with pytest.raises(KeyError):
        locator.locate("24", 99)


def test_unknown_entidad_raises(locator):
    with pytest.raises(KeyError):
        locator.locate("XX", 1)
