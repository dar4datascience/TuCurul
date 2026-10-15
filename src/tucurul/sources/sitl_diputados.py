"""SITL / INFOPAL de la Cámara de Diputados: estadística parlamentaria.

Ingesta la LXVI legislatura: directorio de diputados (curricula.php),
votaciones nominales por periodo (estadístico por grupo + listados
nominales). Usa el cliente HTTP compartido y el modelo normalizado.
"""

import csv
import logging
import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..geo.ine import SECCIONES_CSV
from ..states import load_states
from .base import Level, Source
from .http import HttpClient
from .models import (
    Camara,
    Legislador,
    Principio,
    Sentido,
    TotalGrupo,
    Votacion,
    Voto,
    normalize_entidad,
    normalize_partido,
    normalize_sentido,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://sitl.diputados.gob.mx/LXVI_leg/"
SOURCE = "sitl_diputados"
LEGISLATURA = "LXVI"
DIRECTORIO_URL = BASE_URL + "listado_diputados_gpnp.php?tipot=TOTAL"
PERIODOS_URL = BASE_URL + "votaciones_por_periodonplxvi.php"

# Diputados que aparecen votando pero ya no están en el directorio
# (licencias, renuncias o suplentes que cubrieron y salieron).
ESTATUS_NO_EN_DIRECTORIO = "no en directorio"

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_RE_PERT = re.compile(r"votacionesxperiodonplxvi\.php\?pert=(\d+)")
_RE_VOTACIONT = re.compile(r"estadistico_votacionnplxvi\.php\?votaciont=(\d+)")
_RE_LISTADO = re.compile(
    r"listados_votacionesnplxvi\.php\?partidot=(\d+)&votaciont=(\d+)"
)
_RE_DIPT = re.compile(r"curricula\.php\?dipt=(\d+)")
_RE_IDDIPT = re.compile(r"votaciones_por_pernplxvi\.php\?iddipt=(\d+)")
_RE_FECHA = re.compile(r"(\d{1,2})\s+([A-Za-zÁÉÍÓÚáéíóúü]+)\s+(\d{4})")


@dataclass(frozen=True)
class SitlDatos:
    """Resultado completo de la ingesta del SITL."""

    legisladores: tuple[Legislador, ...]
    votaciones: tuple[Votacion, ...]
    totales: tuple[TotalGrupo, ...]
    votos: tuple[Voto, ...]


def _fecha(texto: str) -> date | None:
    """Fechas del SITL tipo ``3 Septiembre 2024`` → date; None si no cuadra."""
    m = _RE_FECHA.search(texto)
    if not m:
        return None
    mes = MESES.get(m.group(2).lower())
    if mes is None:
        return None
    return date(int(m.group(3)), mes, int(m.group(1)))


def parse_periodos(html: str, url: str) -> list[tuple[str, str]]:
    """Índice de periodos → lista de ``(pert, nombre del periodo)``."""
    soup = BeautifulSoup(html, "html.parser")
    periodos: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for a in soup.find_all("a", href=True):
        m = _RE_PERT.search(a["href"])
        if m and m.group(1) not in vistos:
            vistos.add(m.group(1))
            periodos.append((m.group(1), a.get_text(strip=True)))
    return periodos


def parse_votaciones_periodo(html: str, url: str) -> list[tuple[str, date | None, str]]:
    """Votaciones de un periodo → ``(votaciont, fecha, titulo)``.

    La tabla agrupa por día: una celda ``colspan`` con la fecha seguida de
    filas con el enlace al estadístico y el título. Las tablas vienen
    anidadas, así que se recorre el flujo de elementos (no las filas).
    """
    soup = BeautifulSoup(html, "html.parser")
    votaciones: list[tuple[str, date | None, str]] = []
    fecha_actual: date | None = None
    for el in soup.find_all(["td", "a"]):
        if el.name == "td":
            if el.get("colspan"):
                posible = _fecha(el.get_text(" ", strip=True))
                if posible:
                    fecha_actual = posible
            continue
        m = _RE_VOTACIONT.search(el.get("href") or "")
        if not m:
            continue
        tr = el.find_parent("tr")
        tds = tr.find_all("td", recursive=False) if tr else []
        titulo = tds[-1].get_text(" ", strip=True) if tds else ""
        votaciones.append((m.group(1), fecha_actual, titulo))
    return votaciones


def parse_estadistico(html: str, url: str) -> tuple[list[TotalGrupo], dict[str, str]]:
    """Estadístico de una votación → ``(totales por grupo, partidot→partido)``.

    Los códigos ``partidot`` se extraen de los enlaces a los listados
    nominales; nunca se hardcodean.
    """
    votaciont = re.search(r"votaciont=(\d+)", url)
    vid = votaciont.group(1) if votaciont else ""
    soup = BeautifulSoup(html, "html.parser")
    totales: list[TotalGrupo] = []
    partidot_a_partido: dict[str, str] = {}
    for a in soup.find_all("a", href=_RE_LISTADO):
        m = _RE_LISTADO.search(a["href"])
        partidot = m.group(1)
        partido = normalize_partido(a.get_text(strip=True))
        partidot_a_partido[partidot] = partido
        tr = a.find_parent("tr")
        if tr is None:
            continue
        celdas = [
            td.get_text(strip=True)
            for td in tr.find_all("td", recursive=False)
        ]
        numeros = [int(x) for x in celdas[1:] if x.isdigit()]
        if len(numeros) < 5:
            continue
        totales.append(
            TotalGrupo(
                source=SOURCE,
                votacion_id=vid,
                partido=partido,
                a_favor=numeros[0],
                en_contra=numeros[1],
                abstencion=numeros[2],
                solo_asistencia=numeros[3],
                ausente=numeros[4],
                source_url=url,
            )
        )
    return totales, partidot_a_partido


def parse_listado(html: str, url: str, partido: str | None = None) -> list[Voto]:
    """Listado nominal de un partido en una votación → lista de ``Voto``.

    ``legislador_source_id`` es el ``iddipt`` del enlace
    ``votaciones_por_pernplxvi.php``, el mismo id que ``curricula.php?dipt=``.
    ``partido`` lo aporta el estadístico (el listado no repite el nombre).
    """
    votaciont = re.search(r"votaciont=(\d+)", url)
    vid = votaciont.group(1) if votaciont else ""
    soup = BeautifulSoup(html, "html.parser")
    votos: list[Voto] = []
    for a in soup.find_all("a", href=_RE_IDDIPT):
        iddipt = _RE_IDDIPT.search(a["href"]).group(1)
        tr = a.find_parent("tr")
        tds = tr.find_all("td", recursive=False) if tr else []
        sentido_txt = tds[-1].get_text(strip=True) if tds else ""
        votos.append(
            Voto(
                source=SOURCE,
                votacion_id=vid,
                legislador_source_id=iddipt,
                sentido=normalize_sentido(SOURCE, sentido_txt),
                partido=partido,
                source_url=url,
            )
        )
    return votos


def parse_directorio(html: str, url: str) -> list[tuple[str, str, str]]:
    """Directorio TOTAL → ``(dipt, entidad, distrito o circunscripción)``."""
    soup = BeautifulSoup(html, "html.parser")
    filas: list[tuple[str, str, str]] = []
    for a in soup.find_all("a", href=_RE_DIPT):
        dipt = _RE_DIPT.search(a["href"]).group(1)
        tr = a.find_parent("tr")
        tds = tr.find_all("td", recursive=False) if tr else []
        entidad = tds[1].get_text(strip=True) if len(tds) > 1 else ""
        dist_circ = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        filas.append((dipt, entidad, dist_circ))
    return filas


def _campo_curricula(soup: BeautifulSoup, etiqueta: str) -> str | None:
    """Valor en <b> de un ``<p>Etiqueta: <b>valor</b></p>`` del encabezado."""
    for p in soup.select(".header-contact p"):
        texto = p.get_text(" ", strip=True)
        if texto.lower().startswith(etiqueta.lower()):
            b = p.find("b")
            if b is not None:
                return b.get_text(" ", strip=True)
            resto = texto.split(":", 1)
            return resto[1].strip() if len(resto) > 1 else ""
    return None


def parse_curricula(html: str, url: str) -> Legislador:
    """Ficha curricular → ``Legislador`` con nombre canónico y distrito.

    El partido viene de la imagen ``header-gp`` (``images/<siglas>.webp``).
    Las curriculas de RP no traen Entidad; llevan ``Circunscripción``.
    """
    soup = BeautifulSoup(html, "html.parser")
    m = _RE_DIPT.search(url)
    dipt = m.group(1) if m else ""

    h1 = soup.find("h1", class_="header-name")
    nombre = ""
    if h1 is not None:
        nombre = re.sub(r"^Dip\.?\s*", "", h1.get_text(" ", strip=True)).strip()

    h4 = soup.find("h4", class_="header-job")
    principio_txt = h4.get_text().lower() if h4 is not None else ""
    principio = (
        Principio.RP if "proporcional" in principio_txt else Principio.MR
    )

    entidad_txt = _campo_curricula(soup, "Entidad")
    entidad = normalize_entidad(entidad_txt) if entidad_txt else None
    distrito = _campo_curricula(soup, "Distrito")
    circ = _campo_curricula(soup, "Circunscripción") or _campo_curricula(
        soup, "Circunscripcion"
    )
    img = soup.find("img", class_="header-gp")
    partido = None
    if img is not None and img.get("src"):
        partido = normalize_partido(Path(img["src"]).stem)

    return Legislador(
        source=SOURCE,
        source_id=dipt,
        nombre=nombre,
        camara=Camara.DIPUTADOS,
        legislatura=LEGISLATURA,
        entidad=entidad,
        source_url=url,
        distrito_federal=int(distrito) if distrito and distrito.isdigit() else None,
        circunscripcion=int(circ) if circ and circ.isdigit() else None,
        principio=principio,
        partido=partido,
        curul=_campo_curricula(soup, "Curul"),
        suplente=_campo_curricula(soup, "Suplente"),
    )


def _total(grupos: list[TotalGrupo], campo: str) -> int:
    return sum(getattr(g, campo) for g in grupos)


def validar_sitl(datos: SitlDatos, secciones_csv: Path = SECCIONES_CSV) -> dict:
    """Comprobaciones de coherencia de la ingesta.

    a) Los votos nominales por partido y sentido cuadran con el estadístico.
    b) Los MR vigentes cubren exactamente los 300 distritos (entidad,
       distrito_federal) del catálogo INE, con los conteos por entidad de
       ``states.csv``.
    c) Todo ``Voto.legislador_source_id`` resuelve a un ``Legislador``.

    ``ok`` es True solo si (b) y (c) pasan; los desajustes de (a) se
    reportan en ``mismatches`` sin tumbar la ingesta.
    """
    # (a) votos vs totales del estadístico
    conteo = Counter(
        (v.votacion_id, v.partido, v.sentido) for v in datos.votos
    )
    mismatches: list[str] = []
    comparaciones = 0
    for t in datos.totales:
        for sentido, esperado in (
            (Sentido.A_FAVOR, t.a_favor),
            (Sentido.EN_CONTRA, t.en_contra),
            (Sentido.ABSTENCION, t.abstencion),
            (Sentido.SOLO_ASISTENCIA, t.solo_asistencia),
            (Sentido.AUSENTE, t.ausente),
        ):
            comparaciones += 1
            real = conteo.get((t.votacion_id, t.partido, sentido), 0)
            if real != esperado:
                mismatches.append(
                    f"votaciont={t.votacion_id} {t.partido} "
                    f"{sentido.value}: estadístico={esperado} listados={real}"
                )

    # (b) cobertura MR vs estados e INE
    mr = [
        l
        for l in datos.legisladores
        if l.principio == Principio.MR
        and l.estatus != ESTATUS_NO_EN_DIRECTORIO
    ]
    pares = [(l.entidad, l.distrito_federal) for l in mr]
    conteo_pares = Counter(pares)
    duplicados = sorted(
        [p for p, n in conteo_pares.items() if n > 1]
    )
    por_entidad = Counter(p[0] for p in pares)
    estados_mal = {
        s.clave: {"ine": s.distritos_federales, "sitl": por_entidad.get(s.clave, 0)}
        for s in load_states()
        if por_entidad.get(s.clave, 0) != s.distritos_federales
    }
    pares_ine: set[tuple[str, int]] = set()
    if secciones_csv.exists():
        with open(secciones_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pares_ine.add((row["entidad"], int(row["distrito_federal"])))
    invalidos = sorted(set(pares) - pares_ine)
    faltantes_ine = sorted(pares_ine - set(pares))

    # (c) votos que no resuelven a legislador
    ids_legisladores = {l.source_id for l in datos.legisladores}
    sin_legislador = sorted(
        {v.legislador_source_id for v in datos.votos} - ids_legisladores,
        key=lambda x: (0, int(x)) if x.isdigit() else (1, x),
    )

    ok = (
        not duplicados
        and not estados_mal
        and not invalidos
        and not faltantes_ine
        and not sin_legislador
        and len(set(pares)) == 300
    )
    return {
        "ok": ok,
        "votos_vs_totales": {
            "comparaciones": comparaciones,
            "mismatches": mismatches,
        },
        "mr_distritos": {
            "mr_vigentes": len(mr),
            "pares_unicos": len(set(pares)),
            "duplicados": duplicados,
            "entidades_descuadradas": estados_mal,
            "pares_fuera_del_ine": invalidos,
            "distritos_ine_sin_diputado": faltantes_ine,
        },
        "votos_sin_legislador": sin_legislador,
    }


class SitlDiputados(Source):
    name = "SITL — Sistema de Información y Transparencia Legislativa"
    url = "https://sitl.diputados.gob.mx/LXVI_leg/sistema_legislativo_LXVI.html"
    levels = (Level.FEDERAL,)
    dimensions = (
        "diputados_federales",
        "votaciones_federales",
        "iniciativas",
        "asistencias",
        "comisiones",
    )

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        max_votaciones: int | None = None,
    ) -> None:
        self.client = client
        self.max_votaciones = max_votaciones

    def _texto(self, client: HttpClient, url: str) -> tuple[str, str]:
        resp = client.get(url)
        return resp.text, str(resp.url)

    def fetch(self) -> SitlDatos:
        """Descarga y normaliza directorio, votaciones y votos del SITL."""
        client = self.client or HttpClient(SOURCE)
        try:
            return self._fetch(client)
        finally:
            if self.client is None:
                client.close()

    def _fetch(self, client: HttpClient) -> SitlDatos:
        html, url = self._texto(client, DIRECTORIO_URL)
        directorio = parse_directorio(html, url)
        logger.info("Directorio TOTAL: %d diputados", len(directorio))

        legisladores: dict[str, Legislador] = {}
        for i, (dipt, _, _) in enumerate(directorio, 1):
            html, url = self._texto(client, f"{BASE_URL}curricula.php?dipt={dipt}")
            legisladores[dipt] = parse_curricula(html, url)
            if i % 50 == 0:
                logger.info("  curricula %d/%d", i, len(directorio))

        html, url = self._texto(client, PERIODOS_URL)
        periodos = parse_periodos(html, url)
        logger.info(
            "Periodos: %s", ", ".join(pert for pert, _ in periodos)
        )

        votaciones: list[Votacion] = []
        totales: list[TotalGrupo] = []
        votos: list[Voto] = []
        procesadas = 0
        for pert, nombre_periodo in periodos:
            html, url = self._texto(
                client, f"{BASE_URL}votacionesxperiodonplxvi.php?pert={pert}"
            )
            metas = parse_votaciones_periodo(html, url)
            logger.info("Periodo pert=%s (%s): %d votaciones", pert, nombre_periodo, len(metas))
            for votaciont, fecha, titulo in metas:
                if (
                    self.max_votaciones is not None
                    and procesadas >= self.max_votaciones
                ):
                    break
                html, url = self._texto(
                    client,
                    f"{BASE_URL}estadistico_votacionnplxvi.php?votaciont={votaciont}",
                )
                grupos, partidot_a_partido = parse_estadistico(html, url)
                votos_votacion: list[Voto] = []
                for partidot, partido in partidot_a_partido.items():
                    html, url = self._texto(
                        client,
                        f"{BASE_URL}listados_votacionesnplxvi.php"
                        f"?partidot={partidot}&votaciont={votaciont}",
                    )
                    votos_votacion.extend(
                        parse_listado(html, url, partido=partido)
                    )
                totales.extend(grupos)
                votos.extend(votos_votacion)
                votaciones.append(
                    Votacion(
                        source=SOURCE,
                        source_id=votaciont,
                        camara=Camara.DIPUTADOS,
                        legislatura=LEGISLATURA,
                        fecha=fecha,
                        titulo=titulo,
                        a_favor=_total(grupos, "a_favor"),
                        en_contra=_total(grupos, "en_contra"),
                        abstencion=_total(grupos, "abstencion"),
                        solo_asistencia=_total(grupos, "solo_asistencia"),
                        ausente=_total(grupos, "ausente"),
                        source_url=urljoin(
                            BASE_URL,
                            f"estadistico_votacionnplxvi.php?votaciont={votaciont}",
                        ),
                        periodo=pert,
                    )
                )
                procesadas += 1
                if procesadas % 25 == 0:
                    logger.info("  votaciones procesadas: %d", procesadas)
            if (
                self.max_votaciones is not None
                and procesadas >= self.max_votaciones
            ):
                break

        # diputados que votaron pero ya no están en el directorio
        faltantes = sorted(
            {v.legislador_source_id for v in votos} - set(legisladores),
            key=lambda x: int(x) if x.isdigit() else 0,
        )
        if faltantes:
            logger.info(
                "Diputados fuera del directorio: %s", ", ".join(faltantes)
            )
        for dipt in faltantes:
            html, url = self._texto(
                client, f"{BASE_URL}curricula.php?dipt={dipt}"
            )
            legisladores[dipt] = replace(
                parse_curricula(html, url),
                estatus=ESTATUS_NO_EN_DIRECTORIO,
            )

        return SitlDatos(
            legisladores=tuple(
                legisladores[k]
                for k in sorted(legisladores, key=lambda x: int(x))
            ),
            votaciones=tuple(votaciones),
            totales=tuple(totales),
            votos=tuple(votos),
        )
