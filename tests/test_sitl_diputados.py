"""Parsers e ingesta del SITL LXVI contra fixtures en bytes reales."""

import csv
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
import pytest

from tucurul.sources.http import HttpClient, decode
from tucurul.sources.models import (
    Camara,
    Legislador,
    Principio,
    Sentido,
    TotalGrupo,
    Voto,
)
from tucurul.sources.sitl_diputados import (
    BASE_URL,
    DIRECTORIO_URL,
    ESTATUS_NO_EN_DIRECTORIO,
    PERIODOS_URL,
    SitlDatos,
    SitlDiputados,
    parse_curricula,
    parse_directorio,
    parse_estadistico,
    parse_listado,
    parse_periodos,
    parse_votaciones_periodo,
    validar_sitl,
)
from tucurul.states import DATA_DIR, load_states

FIXTURES = Path(__file__).parent / "fixtures" / "sitl_diputados"


def fixture_text(nombre: str) -> tuple[str, str]:
    """(texto, codificación) del fixture, decodificado como el cliente."""
    return decode((FIXTURES / nombre).read_bytes())


def test_parse_periodos():
    texto, _ = fixture_text("periodos.html")
    periodos = parse_periodos(texto, PERIODOS_URL)
    perts = [pert for pert, _ in periodos]
    assert perts == ["1", "3", "5", "6", "8", "10", "11"]
    assert "Sesiones Ordinarias" in periodos[0][1]


def test_parse_votaciones_periodo():
    texto, _ = fixture_text("periodo_pert1.html")
    metas = parse_votaciones_periodo(
        texto, f"{BASE_URL}votacionesxperiodonplxvi.php?pert=1"
    )
    assert len(metas) == 52
    vid, fecha, titulo = metas[0]
    assert vid == "2"
    assert fecha == date(2024, 9, 3)
    assert "REFORMA DEL PODER JUDICIAL" in titulo
    # fechas distintas a lo largo del periodo
    assert metas[-1][1] == date(2024, 12, 11)


def test_parse_estadistico():
    texto, _ = fixture_text("estadistico_votaciont2.html")
    url = f"{BASE_URL}estadistico_votacionnplxvi.php?votaciont=2"
    totales, partidot_a_partido = parse_estadistico(texto, url)
    # códigos partidot extraídos de los enlaces, no hardcodeados
    assert partidot_a_partido == {
        "14": "MORENA",
        "3": "PAN",
        "5": "PVEM",
        "4": "PT",
        "1": "PRI",
        "6": "MC",
        "2": "PRD",
        "9": "IND",
    }
    assert len(totales) == 8
    morena = next(t for t in totales if t.partido == "MORENA")
    assert (morena.a_favor, morena.en_contra, morena.abstencion) == (250, 0, 0)
    assert (morena.solo_asistencia, morena.ausente) == (0, 5)
    assert morena.votacion_id == "2"
    assert morena.source_url == url


def test_parse_listado_acentos_y_sentidos():
    """El listado mezcla UTF-8: decode no debe producir mojibake."""
    texto, _ = decode(
        (FIXTURES / "listado_votaciont2_partidot14.html").read_bytes()
    )
    assert "Ã" not in texto
    assert "Gómez Urrutia Napoleón" in texto
    url = f"{BASE_URL}listados_votacionesnplxvi.php?partidot=14&votaciont=2"
    votos = parse_listado(texto, url, partido="MORENA")
    assert len(votos) == 255
    sentidos = Counter(v.sentido for v in votos)
    assert sentidos[Sentido.A_FAVOR] == 250
    assert sentidos[Sentido.AUSENTE] == 5
    assert all(v.votacion_id == "2" for v in votos)
    assert all(v.partido == "MORENA" for v in votos)
    assert all(v.source_url == url for v in votos)


def test_votos_cuadran_con_estadistico():
    """Suma de votos nominales por partido = totales del estadístico."""
    texto, _ = fixture_text("estadistico_votaciont2.html")
    url = f"{BASE_URL}estadistico_votacionnplxvi.php?votaciont=2"
    totales, partidot_a_partido = parse_estadistico(texto, url)
    votos: list[Voto] = []
    for partidot, partido in partidot_a_partido.items():
        ltexto, _ = fixture_text(f"listado_votaciont2_partidot{partidot}.html")
        lurl = (
            f"{BASE_URL}listados_votacionesnplxvi.php"
            f"?partidot={partidot}&votaciont=2"
        )
        votos.extend(parse_listado(ltexto, lurl, partido=partido))
    conteo = Counter((v.partido, v.sentido) for v in votos)
    for t in totales:
        esperado = {
            Sentido.A_FAVOR: t.a_favor,
            Sentido.EN_CONTRA: t.en_contra,
            Sentido.ABSTENCION: t.abstencion,
            Sentido.SOLO_ASISTENCIA: t.solo_asistencia,
            Sentido.AUSENTE: t.ausente,
        }
        for sentido, n in esperado.items():
            assert conteo.get((t.partido, sentido), 0) == n, (
                f"{t.partido} {sentido}"
            )


def test_iddipt_es_dipt():
    """El iddipt de los listados es el mismo id que curricula.php?dipt."""
    texto, _ = fixture_text("listado_votaciont2_partidot1.html")
    votos = parse_listado(
        texto,
        f"{BASE_URL}listados_votacionesnplxvi.php?partidot=1&votaciont=2",
        partido="PRI",
    )
    ids = {v.legislador_source_id for v in votos}
    assert "1" in ids  # dipt=1 (Ambriz Delgadillo, PRI) votó en la votaciont=2
    texto_dir, _ = fixture_text("directorio_total.html")
    filas = {
        dipt: (entidad, circ)
        for dipt, entidad, circ in parse_directorio(texto_dir, DIRECTORIO_URL)
    }
    assert "1" in filas


def test_parse_directorio_fixture_recortado():
    texto, _ = fixture_text("directorio_total.html")
    filas = parse_directorio(texto, DIRECTORIO_URL)
    assert len(filas) == 10
    por_dipt = {dipt: (ent, dc) for dipt, ent, dc in filas}
    assert por_dipt["1"] == ("Aguascalientes", "Dtto.  1")
    assert por_dipt["391"] == ("Campeche", "Circ.  3")


def test_parse_curricula_mr_con_bom():
    """curricula.php llega en UTF-8 con BOM; decode lo maneja."""
    raw = (FIXTURES / "curricula_dipt1.html").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    texto, enc = decode(raw)
    assert enc == "utf-8"
    leg = parse_curricula(texto, f"{BASE_URL}curricula.php?dipt=1")
    assert leg.source == "sitl_diputados"
    assert leg.source_id == "1"
    assert leg.nombre == "Humberto Ambriz Delgadillo"
    assert leg.camara is Camara.DIPUTADOS
    assert leg.legislatura == "LXVI"
    assert leg.principio is Principio.MR
    assert leg.entidad == "01"  # Aguascalientes
    assert leg.distrito_federal == 1
    assert leg.circunscripcion is None
    assert leg.curul == "C-063"
    assert leg.suplente == "Juan Manuel Méndez Noriega"
    assert leg.partido == "PRI"
    assert leg.source_url.endswith("curricula.php?dipt=1")


def test_parse_curricula_rp():
    texto, _ = fixture_text("curricula_dipt391.html")
    leg = parse_curricula(texto, f"{BASE_URL}curricula.php?dipt=391")
    assert leg.nombre == "Rocío Adriana Abreu Artiñano"
    assert leg.principio is Principio.RP
    assert leg.circunscripcion == 3
    assert leg.distrito_federal is None
    assert leg.entidad is None  # las curriculas de RP no traen Entidad
    assert leg.curul == "H-265"
    assert leg.partido == "MORENA"


def _fixture_transport() -> httpx.MockTransport:
    """Sirve los fixtures por URL; curricula desconocidas → dipt=1."""
    mapa = {
        DIRECTORIO_URL: "directorio_total.html",
        PERIODOS_URL: "periodos.html",
        f"{BASE_URL}votacionesxperiodonplxvi.php?pert=1": "periodo_pert1.html",
        f"{BASE_URL}estadistico_votacionnplxvi.php?votaciont=2": (
            "estadistico_votaciont2.html"
        ),
        f"{BASE_URL}curricula.php?dipt=1": "curricula_dipt1.html",
        f"{BASE_URL}curricula.php?dipt=391": "curricula_dipt391.html",
    }
    for p in ["14", "3", "5", "4", "1", "6", "2", "9"]:
        mapa[
            f"{BASE_URL}listados_votacionesnplxvi.php?partidot={p}&votaciont=2"
        ] = f"listado_votaciont2_partidot{p}.html"
    curricula_mr = (FIXTURES / "curricula_dipt1.html").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        nombre = mapa.get(url)
        if nombre is not None:
            return httpx.Response(200, content=(FIXTURES / nombre).read_bytes())
        if "curricula.php?dipt=" in url:
            return httpx.Response(200, content=curricula_mr)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_fetch_end_to_end(tmp_path):
    client = HttpClient(
        "sitl_diputados",
        cache_dir=tmp_path,
        min_interval=0,
        transport=_fixture_transport(),
        sleep=lambda s: None,
    )
    datos = SitlDiputados(client=client, max_votaciones=1).fetch()

    ids_dir = {"391", "804", "12", "390", "315", "493", "513", "329", "14", "1"}
    faltantes = {v.legislador_source_id for v in datos.votos} - ids_dir
    # directorio (10) + curriculas de quienes solo aparecen en votos
    assert len(datos.legisladores) == 10 + len(faltantes)
    por_id = {l.source_id: l for l in datos.legisladores}
    assert all(
        por_id[i].estatus == ESTATUS_NO_EN_DIRECTORIO for i in faltantes
    )
    assert len(datos.votaciones) == 1
    vot = datos.votaciones[0]
    assert vot.source_id == "2"
    assert vot.fecha == date(2024, 9, 3)
    assert vot.periodo == "1"
    assert vot.instancia == "pleno"
    assert vot.a_favor == sum(t.a_favor for t in datos.totales)
    assert len(datos.totales) == 8
    assert len(datos.votos) == sum(
        t.a_favor + t.en_contra + t.abstencion + t.solo_asistencia + t.ausente
        for t in datos.totales
    )
    ids = {l.source_id for l in datos.legisladores}
    assert {v.legislador_source_id for v in datos.votos} - ids == set()
    leg1 = next(l for l in datos.legisladores if l.source_id == "1")
    assert leg1.nombre == "Humberto Ambriz Delgadillo"


def test_validar_detecta_desajustes():
    """La validación reporta mismatch de totales y distrito faltante."""
    leg = Legislador(
        source="sitl_diputados",
        source_id="1",
        nombre="X",
        camara=Camara.DIPUTADOS,
        legislatura="LXVI",
        entidad="01",
        source_url="u",
        distrito_federal=1,
        principio=Principio.MR,
    )
    datos = SitlDatos(
        legisladores=(leg,),
        votaciones=(),
        totales=(
            TotalGrupo(
                source="sitl_diputados",
                votacion_id="v1",
                partido="PAN",
                a_favor=2,
                en_contra=0,
                abstencion=0,
                solo_asistencia=0,
                ausente=0,
                source_url="u",
            ),
        ),
        votos=(
            Voto(
                source="sitl_diputados",
                votacion_id="v1",
                legislador_source_id="1",
                sentido=Sentido.A_FAVOR,
                partido="PAN",
                source_url="u",
            ),
            Voto(
                source="sitl_diputados",
                votacion_id="v1",
                legislador_source_id="999",
                sentido=Sentido.A_FAVOR,
                partido="PAN",
                source_url="u",
            ),
        ),
    )
    res = validar_sitl(datos)
    # (a) 2 votos a favor de PAN cuadran con el estadístico → sin mismatch
    assert res["votos_vs_totales"]["mismatches"] == []
    # (b) faltan 299 distritos → estados_descuadrados y distritos sin diputado
    assert res["mr_distritos"]["pares_unicos"] == 1
    assert res["mr_distritos"]["entidades_descuadradas"]
    assert res["mr_distritos"]["distritos_ine_sin_diputado"]
    # (c) el voto de iddipt=999 no resuelve a legislador
    assert res["votos_sin_legislador"] == ["999"]
    assert not res["ok"]


def test_validar_mismatch_de_conteo():
    """Si el listado no cuadra con el estadístico, queda en mismatches."""
    datos = SitlDatos(
        legisladores=(),
        votaciones=(),
        totales=(
            TotalGrupo(
                source="sitl_diputados",
                votacion_id="v1",
                partido="PAN",
                a_favor=5,
                en_contra=0,
                abstencion=0,
                solo_asistencia=0,
                ausente=0,
                source_url="u",
            ),
        ),
        votos=(
            Voto(
                source="sitl_diputados",
                votacion_id="v1",
                legislador_source_id="1",
                sentido=Sentido.EN_CONTRA,
                partido="PAN",
                source_url="u",
            ),
        ),
    )
    res = validar_sitl(datos)
    mismatches = res["votos_vs_totales"]["mismatches"]
    assert any("PAN" in m and "a_favor" in m for m in mismatches)


def test_legisladores_ingeridos_cubren_300_mr():
    """Si existe el CSV ingerido, los 300 MR cruzan con el INE."""
    ruta = DATA_DIR / "sitl_diputados" / "legisladores.csv"
    if not ruta.exists():
        pytest.skip("aún no hay ingest en data/sitl_diputados/")
    pares_ine = set()
    with open(DATA_DIR / "ine" / "secciones.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pares_ine.add((row["entidad"], int(row["distrito_federal"])))
    mr = []
    with open(ruta, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["principio"] == "MR" and row["estatus"] != ESTATUS_NO_EN_DIRECTORIO:
                mr.append((row["entidad"], int(row["distrito_federal"])))
    assert len(set(mr)) == 300
    assert set(mr) == pares_ine
    por_entidad = Counter(p[0] for p in mr)
    for state in load_states():
        assert por_entidad[state.clave] == state.distritos_federales
