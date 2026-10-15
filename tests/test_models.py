"""Normalización de sentido, partido y entidad, y escritura CSV."""

import csv
from datetime import date

import pytest

from tucurul.sources.models import (
    Camara,
    Iniciativa,
    Sentido,
    Votacion,
    normalize_entidad,
    normalize_partido,
    normalize_sentido,
    write_csv,
)


@pytest.mark.parametrize(
    "raw,esperado",
    [
        ("A favor", Sentido.A_FAVOR),
        ("a favor", Sentido.A_FAVOR),
        ("EN CONTRA", Sentido.EN_CONTRA),
        ("Abstención", Sentido.ABSTENCION),
        ("abstencion", Sentido.ABSTENCION),
        ("Solo asistencia", Sentido.SOLO_ASISTENCIA),
        ("ausente", Sentido.AUSENTE),
    ],
)
def test_sentido_sitl(raw, esperado):
    assert normalize_sentido("sitl_diputados", raw) is esperado


@pytest.mark.parametrize(
    "raw,esperado",
    [
        ("PRO", Sentido.A_FAVOR),
        ("pro", Sentido.A_FAVOR),
        ("CONTRA", Sentido.EN_CONTRA),
        ("Abstención", Sentido.ABSTENCION),
        ("ausente", Sentido.AUSENTE),
    ],
)
def test_sentido_senado(raw, esperado):
    assert normalize_sentido("senado", raw) is esperado


def test_sentido_desconocido_es_otro():
    assert normalize_sentido("sitl_diputados", "presente") is Sentido.OTRO
    assert normalize_sentido("fuente_nueva", "a favor") is Sentido.OTRO


@pytest.mark.parametrize(
    "raw,esperado",
    [
        ("Morena", "MORENA"),
        ("MORENA", "MORENA"),
        ("Movimiento Ciudadano", "MC"),
        ("mc", "MC"),
        ("Verde", "PVEM"),
        ("Partido Verde Ecologista de México", "PVEM"),
        ("Partido Acción Nacional", "PAN"),
        ("Partido Revolucionario Institucional", "PRI"),
        ("Partido de la Revolución Democrática", "PRD"),
        ("Partido del Trabajo", "PT"),
        ("Sin Partido", "IND"),
        ("Independiente", "IND"),
        ("independiente", "IND"),
        ("Fuerza por México", "FUERZA POR MÉXICO"),
    ],
)
def test_normalize_partido(raw, esperado):
    assert normalize_partido(raw) == esperado


@pytest.mark.parametrize(
    "raw,esperado",
    [
        ("Ciudad de México", "09"),
        ("ciudad de mexico", "09"),
        ("ciudad-de-mexico", "09"),
        ("CDMX", "09"),
        ("cdmx", "09"),
        ("Distrito Federal", "09"),
        ("9", "09"),
        ("09", "09"),
        ("México", "15"),
        ("mexico", "15"),
        ("Estado de México", "15"),
        ("Edo. de México", "15"),
        ("MEX", "15"),
        ("Jalisco", "14"),
        ("jalisco", "14"),
        ("Nuevo León", "19"),
        ("nuevo leon", "19"),
        ("Coahuila de Zaragoza", "05"),
        ("Michoacán de Ocampo", "16"),
        ("Veracruz de Ignacio de la Llave", "30"),
    ],
)
def test_normalize_entidad(raw, esperado):
    assert normalize_entidad(raw) == esperado


def test_normalize_entidad_desconocida():
    with pytest.raises(KeyError):
        normalize_entidad("Atlántida")


def test_write_csv(tmp_path):
    votacion = Votacion(
        source="sitl_diputados",
        source_id="v1",
        camara=Camara.DIPUTADOS,
        legislatura="LXVI",
        fecha=date(2026, 3, 5),
        titulo="Punto de acuerdo",
        a_favor=300,
        en_contra=150,
        abstencion=10,
        solo_asistencia=5,
        ausente=None,
        source_url="https://e.test/v1",
    )
    iniciativa = Iniciativa(
        source="gaceta",
        source_id="i1",
        legislatura="LXVI",
        fecha=date(2026, 4, 1),
        titulo="Iniciativa de prueba",
        presentadores=("Ana Pérez", "Luis Ruiz"),
        turno="Comisión de Hacienda",
        estatus=None,
        source_url="https://e.test/i1",
    )
    ruta = tmp_path / "salida" / "registros.csv"
    write_csv(ruta, [votacion])
    with open(ruta, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    header_v = [
        "source", "source_id", "camara", "legislatura", "fecha", "titulo",
        "a_favor", "en_contra", "abstencion", "solo_asistencia", "ausente",
        "source_url", "instancia", "periodo",
    ]
    assert rows[0] == header_v
    assert rows[1] == [
        "sitl_diputados", "v1", "diputados", "LXVI", "2026-03-05",
        "Punto de acuerdo", "300", "150", "10", "5", "",
        "https://e.test/v1", "pleno", "",
    ]

    ruta2 = tmp_path / "salida" / "iniciativas.csv"
    write_csv(ruta2, [iniciativa])
    with open(ruta2, newline="", encoding="utf-8") as f:
        rows2 = list(csv.DictReader(f))
    assert rows2[0]["presentadores"] == "Ana Pérez|Luis Ruiz"
    assert rows2[0]["fecha"] == "2026-04-01"
    assert rows2[0]["estatus"] == ""
