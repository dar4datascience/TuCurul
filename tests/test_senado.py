"""Parsers e ingesta del Senado LXVI contra fixtures en bytes reales."""

import re
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
import pytest

from tucurul.cli import build_parser
from tucurul.sources.http import HttpClient, decode
from tucurul.sources.models import (
    Camara,
    Legislador,
    Principio,
    Sentido,
    Votacion,
    Voto,
)
from tucurul.sources.senado import (
    BASE_URL,
    DATOS_ABIERTOS_URL,
    ESTATUS_EN_FUNCIONES,
    ESTATUS_NO_EN_DATOS_ABIERTOS,
    VOTACIONES_URL,
    Senado,
    SenadoDatos,
    es_bloqueo_incapsula,
    parse_anios,
    parse_datos_abiertos_index,
    parse_perfil,
    parse_senadores,
    parse_tabla_votos,
    parse_totales,
    parse_votaciones_anio,
    validar_senado,
)
from tucurul.states import load_states

FIXTURES = Path(__file__).parent / "fixtures" / "senado"
JSON_URL = (
    "https://www.senado.gob.mx/66/datosAbiertos/"
    "senadoresDatosAb_28092026.json"
)


def fixture_text(nombre: str) -> tuple[str, str]:
    """(texto, codificación) del fixture, decodificado como el cliente."""
    return decode((FIXTURES / nombre).read_bytes())


def _senadores() -> list[Legislador]:
    texto, _ = fixture_text("senadoresDatosAb_28092026.json")
    return parse_senadores(texto, JSON_URL)


def test_parse_datos_abiertos_index():
    texto, _ = fixture_text("datos_abiertos_index.html")
    json_url, corte = parse_datos_abiertos_index(texto, DATOS_ABIERTOS_URL)
    assert json_url == JSON_URL
    assert corte == date(2026, 9, 28)


def test_parse_datos_abiertos_index_sin_json():
    with pytest.raises(ValueError):
        parse_datos_abiertos_index("<html><body></body></html>", "u")


def test_parse_senadores():
    legisladores = _senadores()
    assert len(legisladores) == 128
    assert all(l.camara is Camara.SENADO for l in legisladores)
    assert all(l.legislatura == "LXVI" for l in legisladores)
    assert all(l.source_url == JSON_URL for l in legisladores)
    assert all(l.estatus == ESTATUS_EN_FUNCIONES for l in legisladores)

    principios = Counter(l.principio for l in legisladores)
    assert principios[Principio.MR] == 64
    assert principios[Principio.PRIMERA_MINORIA] == 32
    assert principios[Principio.RP] == 32

    # los 32 de representación proporcional no traen entidad
    rp = [l for l in legisladores if l.principio is Principio.RP]
    assert all(l.entidad is None for l in rp)

    # 3 senadores por entidad (2 MR + 1 primera minoría)
    por_entidad = Counter(l.entidad for l in legisladores if l.entidad)
    assert len(por_entidad) == 32
    assert set(por_entidad.values()) == {3}
    assert por_entidad == Counter(
        {s.clave: 3 for s in load_states()}
    )

    partidos = Counter(l.partido for l in legisladores)
    assert partidos["MORENA"] == 66  # "morena" en minúsculas en el JSON
    assert partidos["MC"] == 6  # "Movimiento Ciudadano"
    assert partidos["IND"] == 2  # "SG" (sin grupo)


def test_parse_senadores_registro_conocido():
    por_id = {l.source_id: l for l in _senadores()}
    leg = por_id["1503"]
    assert leg.nombre == "Juan Antonio Martín del Campo Martín del Campo"
    assert leg.entidad == "01"  # Aguascalientes
    assert leg.partido == "PAN"
    assert leg.principio is Principio.MR
    assert leg.suplente == "Francisco Javier Luévano Núñez"
    assert leg.sexo == "Hombre"
    assert leg.correo == "martindelcampo@senado.gob.mx"
    assert leg.telefono == "55 5345 3000 ext. 3179 y 5857"
    coahuila = next(l for l in por_id.values() if l.entidad == "05")
    assert coahuila.nombre  # 'Coahuila de Zaragoza' → '05'


def test_parse_anios():
    texto, _ = fixture_text("votaciones.html")
    anios = parse_anios(texto, VOTACIONES_URL)
    assert [a.rsplit("/", 1)[-1] for a in anios] == ["1", "2", "3"]
    assert all(a.startswith(BASE_URL) for a in anios)


def test_parse_votaciones_anio():
    texto, _ = fixture_text("por_anio_3.html")
    url = f"{VOTACIONES_URL}/por_anio/LXVI/3"
    metas = parse_votaciones_anio(texto, url)
    assert len(metas) == 34
    ids = [vid for vid, _, _, _ in metas]
    assert len(ids) == len(set(ids))
    assert "5150" in ids
    meta_5150 = next(m for m in metas if m[0] == "5150")
    assert meta_5150[1] == date(2026, 10, 7)
    assert "Ley Federal de Protección al Consumidor" in meta_5150[2]
    assert all("\n" not in titulo for _, _, titulo, _ in metas)
    assert all(fecha is not None for _, fecha, _, _ in metas)
    assert all(periodo.startswith("3: ") for _, _, _, periodo in metas)
    assert meta_5150[3] == (
        "3: Primer Periodo Ordinario Tercer Año de Ejercicio"
    )


def test_parse_totales():
    texto, _ = fixture_text("votacion5150.html")
    url = f"{BASE_URL}votacion/5150"
    assert parse_totales(texto, url) == (98, 0, 0)


def test_parse_totales_sin_tabla():
    with pytest.raises(ValueError):
        parse_totales("<html><body></body></html>", "u")


def test_parse_tabla_votos_5150():
    texto, _ = fixture_text("viewTableVot_5150.html")
    url = f"{BASE_URL}app/votaciones/functions/viewTableVot.php?votacion=5150"
    votos = parse_tabla_votos(texto, url, "5150")
    assert len(votos) == 98
    assert all(v.sentido is Sentido.A_FAVOR for v, _ in votos)
    assert all(v.votacion_id == "5150" for v, _ in votos)
    assert all(v.source_url == url for v, _ in votos)
    por_id = {v.legislador_source_id: nombre for v, nombre in votos}
    # "Sen. Zapata Bello, Rolando Rodrigo" → "Rolando Rodrigo Zapata Bello"
    zapata = next(
        sid for sid, n in por_id.items() if "Zapata Bello" in n
    )
    assert por_id[zapata] == "Rolando Rodrigo Zapata Bello"
    assert all(not n.startswith("Sen.") for n in por_id.values())
    # "SG" en la tabla → IND
    sg = next(v for v, n in votos if "Beltrones Rivera" in n)
    assert sg.partido == "IND"


def test_parse_tabla_votos_4915():
    texto, _ = fixture_text("viewTableVot_4915.html")
    url = f"{BASE_URL}app/votaciones/functions/viewTableVot.php?votacion=4915"
    votos = parse_tabla_votos(texto, url, "4915")
    sentidos = Counter(v.sentido for v, _ in votos)
    assert sentidos[Sentido.A_FAVOR] == 89
    assert sentidos[Sentido.EN_CONTRA] == 16
    assert sentidos[Sentido.OTRO] == 0


def test_ids_de_la_tabla_cruzan_con_datos_abiertos():
    """Cada id del fragmento es idSenador del JSON o baja conocida."""
    texto, _ = fixture_text("viewTableVot_5150.html")
    votos = parse_tabla_votos(texto, "u", "5150")
    ids_json = {l.source_id for l in _senadores()}
    ids_tabla = {v.legislador_source_id for v, _ in votos}
    assert ids_tabla - ids_json == {"1555", "1558", "1619"}
    # 1579 es "Aguilar Castillo, Heriberto Marcelo" en ambas fuentes
    nombres = {v.legislador_source_id: n for v, n in votos}
    leg = next(l for l in _senadores() if l.source_id == "1579")
    assert leg.nombre == "Heriberto Marcelo Aguilar Castillo"
    assert nombres["1579"] == leg.nombre


def test_parse_perfil():
    texto, _ = fixture_text("senador_1555.html")
    url = f"{BASE_URL}senador/1555"
    leg = parse_perfil(texto, url)
    assert leg.source == "senado"
    assert leg.source_id == "1555"
    assert leg.nombre == "Miguel Pavel Jarero Velázquez"
    assert leg.camara is Camara.SENADO
    assert leg.entidad == "18"  # Nayarit
    assert leg.partido == "MORENA"  # iconos_partidos/MORENA_.png
    assert leg.principio is Principio.MR
    assert leg.suplente == "Alejandro García Monroy"
    assert leg.estatus == ESTATUS_NO_EN_DATOS_ABIERTOS
    assert leg.source_url == url


def _fixture_transport(sin_totales: bool = False) -> httpx.MockTransport:
    """Sirve los fixtures por URL; URLs desconocidas → 404.

    Los años 1 y 2 devuelven una página mínima sin votaciones y el
    año 3 una sola votación (5150), igual que la estructura real.
    Con ``sin_totales`` la página de 5150 pierde su
    ``table.resultado-votacion``, como pasa en la 4716 real.
    """
    por_anio = "https://senado.gob.mx/66/votaciones/por_anio/LXVI"
    anio_vacio = (
        b"<html><body><h4 class='text-center'>Sin votaciones</h4>"
        b"</body></html>"
    )
    anio_3 = (
        b"<html><body>"
        b"<h4 class='text-center'>Primer Periodo Ordinario<br>"
        b"Tercer A&ntilde;o de Ejercicio</h4>"
        b"<div><a href='/66/votacion/5150'>Dictamen de prueba</a>"
        b"<br /><br /><strong>Mi&eacute;rcoles 07 de octubre de 2026"
        b"</strong></div></body></html>"
    )
    mapa = {
        DATOS_ABIERTOS_URL: "datos_abiertos_index.html",
        JSON_URL: "senadoresDatosAb_28092026.json",
        VOTACIONES_URL: "votaciones.html",
        f"{BASE_URL}votacion/5150": "votacion5150.html",
        f"{BASE_URL}senador/1555": "senador_1555.html",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        nombre = mapa.get(url)
        if nombre is not None:
            body = (FIXTURES / nombre).read_bytes()
            if sin_totales and "/66/votacion/" in url:
                body = re.sub(
                    rb'<table class="table resultado-votacion".*?</table>',
                    b"",
                    body,
                    flags=re.DOTALL,
                )
            return httpx.Response(200, content=body)
        if url in (f"{por_anio}/1", f"{por_anio}/2"):
            return httpx.Response(200, content=anio_vacio)
        if url == f"{por_anio}/3":
            return httpx.Response(200, content=anio_3)
        if "viewTableVot.php" in url and "votacion=5150" in url:
            return httpx.Response(
                200, content=(FIXTURES / "viewTableVot_5150.html").read_bytes()
            )
        # perfiles de 1558 y 1619 (y cualquier otra URL) → 404
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_fetch_end_to_end(tmp_path):
    client = HttpClient(
        "senado",
        cache_dir=tmp_path,
        min_interval=0,
        transport=_fixture_transport(),
        sleep=lambda s: None,
    )
    datos = Senado(client=client).fetch()

    assert len(datos.legisladores) == 128 + 3
    assert all(l.source_url for l in datos.legisladores)
    assert all(v.source_url for v in datos.votaciones)
    assert all(v.source_url for v in datos.votos)
    assert datos.corte_datos_abiertos == date(2026, 9, 28)
    assert datos.datos_abiertos_url == JSON_URL

    assert len(datos.votaciones) == 1
    vot = datos.votaciones[0]
    assert vot.source_id == "5150"
    assert vot.camara is Camara.SENADO
    assert vot.fecha == date(2026, 10, 7)
    assert (vot.a_favor, vot.en_contra, vot.abstencion) == (98, 0, 0)
    assert vot.solo_asistencia == 0
    assert vot.ausente is None
    assert vot.periodo.startswith("3: ")

    assert len(datos.votos) == 98
    por_id = {l.source_id: l for l in datos.legisladores}
    # 1555 sale de su perfil (Nayarit, MORENA)
    assert por_id["1555"].nombre == "Miguel Pavel Jarero Velázquez"
    assert por_id["1555"].entidad == "18"
    assert por_id["1555"].estatus == ESTATUS_NO_EN_DATOS_ABIERTOS
    # 1558 y 1619 no tienen perfil → datos mínimos de la tabla
    assert por_id["1558"].nombre == "Blanca Judith Díaz Delgado"
    assert por_id["1558"].partido == "MORENA"
    assert por_id["1558"].entidad is None
    assert por_id["1558"].source_url == f"{BASE_URL}senador/1558"
    assert por_id["1619"].nombre == "Wendy Balcázar Pérez"

    validacion = validar_senado(datos)
    assert validacion["ok"]
    assert validacion["votos_vs_totales"]["mismatches"] == []
    assert validacion["votos_sin_legislador"] == []
    assert validacion["votos_sentido_otro"] == 0
    assert validacion["senadores"]["entidades_descuadradas"] == {}
    assert validacion["senadores"]["rp_en_funciones"] == 32


def test_validar_detecta_desajustes():
    """La validación reporta voto sin legislador y senado incompleto."""
    leg = Legislador(
        source="senado",
        source_id="1",
        nombre="X",
        camara=Camara.SENADO,
        legislatura="LXVI",
        entidad="01",
        source_url="u",
        principio=Principio.MR,
        estatus=ESTATUS_EN_FUNCIONES,
    )
    datos = SenadoDatos(
        legisladores=(leg,),
        votaciones=(
            Votacion(
                source="senado",
                source_id="v1",
                camara=Camara.SENADO,
                legislatura="LXVI",
                fecha=None,
                titulo="t",
                a_favor=2,
                en_contra=0,
                abstencion=0,
                solo_asistencia=0,
                ausente=None,
                source_url="u",
            ),
        ),
        votos=(
            Voto(
                source="senado",
                votacion_id="v1",
                legislador_source_id="1",
                sentido=Sentido.A_FAVOR,
                partido="PAN",
                source_url="u",
            ),
            Voto(
                source="senado",
                votacion_id="v1",
                legislador_source_id="999",
                sentido=Sentido.A_FAVOR,
                partido="PAN",
                source_url="u",
            ),
        ),
        corte_datos_abiertos=date(2026, 9, 28),
        datos_abiertos_url="u",
    )
    res = validar_senado(datos)
    # (a) 2 votos a favor cuadran con la página → sin mismatch
    assert res["votos_vs_totales"]["mismatches"] == []
    # (b) faltan senadores en todas las entidades y los 32 RP
    assert res["senadores"]["entidades_descuadradas"]
    assert res["senadores"]["rp_en_funciones"] == 0
    # (c) el voto de id=999 no resuelve a legislador
    assert res["votos_sin_legislador"] == ["999"]
    assert not res["ok"]


def test_validar_mismatch_de_conteo():
    """Si la tabla no cuadra con la página, queda en mismatches."""
    datos = SenadoDatos(
        legisladores=(),
        votaciones=(
            Votacion(
                source="senado",
                source_id="v1",
                camara=Camara.SENADO,
                legislatura="LXVI",
                fecha=None,
                titulo="t",
                a_favor=5,
                en_contra=0,
                abstencion=0,
                solo_asistencia=0,
                ausente=None,
                source_url="u",
            ),
        ),
        votos=(
            Voto(
                source="senado",
                votacion_id="v1",
                legislador_source_id="1",
                sentido=Sentido.EN_CONTRA,
                partido="PAN",
                source_url="u",
            ),
        ),
        corte_datos_abiertos=date(2026, 9, 28),
        datos_abiertos_url="u",
    )
    res = validar_senado(datos)
    mismatches = res["votos_vs_totales"]["mismatches"]
    assert any("a_favor" in m for m in mismatches)
    assert any("en_contra" in m for m in mismatches)


def test_cli_acepta_senado_ingest():
    parser = build_parser()
    args = parser.parse_args(
        ["senado-ingest", "--offline", "--max-votaciones", "1"]
    )
    assert args.command == "senado-ingest"
    assert args.offline is True
    assert args.max_votaciones == 1


def test_es_bloqueo_incapsula():
    bloqueo = (
        b'<html><body><iframe id="main-iframe">'
        b"Request unsuccessful. Incapsula incident ID: 123-456"
        b"</iframe></body></html>"
    )
    assert es_bloqueo_incapsula(bloqueo)
    texto, _ = fixture_text("votacion5150.html")
    assert not es_bloqueo_incapsula(texto.encode())


def test_fetch_totales_derivados(tmp_path):
    """Página de votación sin tabla de totales (como la 4716 real):
    los totales se derivan del fragmento de votos."""
    client = HttpClient(
        "senado",
        cache_dir=tmp_path,
        min_interval=0,
        transport=_fixture_transport(sin_totales=True),
        sleep=lambda s: None,
    )
    datos = Senado(client=client).fetch()

    assert datos.totales_derivados == ("5150",)
    vot = datos.votaciones[0]
    assert (vot.a_favor, vot.en_contra, vot.abstencion) == (98, 0, 0)
    res = validar_senado(datos)
    assert res["totales_derivados"] == ["5150"]
    # no tiene sentido comparar totales derivados consigo mismos
    assert res["votos_vs_totales"]["comparaciones"] == 0
    assert res["votos_vs_totales"]["mismatches"] == []
    assert res["ok"]


def test_validar_legislador_sin_nombre():
    """Un legislador con nombre vacío (p. ej. perfil bloqueado) tumba ok."""
    leg = Legislador(
        source="senado",
        source_id="1",
        nombre="",
        camara=Camara.SENADO,
        legislatura="LXVI",
        entidad="01",
        source_url="u",
        principio=Principio.MR,
        estatus=ESTATUS_EN_FUNCIONES,
    )
    datos = SenadoDatos(
        legisladores=(leg,),
        votaciones=(),
        votos=(),
        corte_datos_abiertos=date(2026, 9, 28),
        datos_abiertos_url="u",
    )
    res = validar_senado(datos)
    assert res["legisladores_sin_nombre"] == ["1"]
    assert not res["ok"]


@pytest.mark.network
def test_datos_abiertos_en_vivo(tmp_path):
    """Índice y JSON de datos abiertos a través del HttpClient real."""
    with HttpClient("senado", cache_dir=tmp_path, min_interval=0) as client:
        resp = client.get(DATOS_ABIERTOS_URL)
        json_url, corte = parse_datos_abiertos_index(
            resp.text, str(resp.url)
        )
        assert corte >= date(2026, 9, 1)
        resp = client.get(json_url)
        legisladores = parse_senadores(resp.text, str(resp.url))
        assert len(legisladores) == 128
