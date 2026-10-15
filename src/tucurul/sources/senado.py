"""Portal del Senado de la República: senadores y votaciones plenarias.

Ingesta la LXVI legislatura: el directorio de senadores sale de datos
abiertos (``micrositios.senado.gob.mx`` → ``senadoresDatosAb_*.json``)
y las votaciones nominales del portal (``senado.gob.mx/66/votaciones``,
páginas por año de ejercicio, totales de cada votación y el fragmento
``viewTableVot.php`` con el voto individual). Usa el cliente HTTP
compartido y el modelo normalizado.
"""

import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..states import load_states
from .base import Level, Source
from .http import FetchError, HttpClient
from .models import (
    Camara,
    Legislador,
    Principio,
    Sentido,
    Votacion,
    Voto,
    normalize_entidad,
    normalize_partido,
    normalize_sentido,
)

logger = logging.getLogger(__name__)

SOURCE = "senado"
LEGISLATURA = "LXVI"
BASE_URL = "https://senado.gob.mx/66/"
DATOS_ABIERTOS_URL = "https://micrositios.senado.gob.mx/LGLXVI/datos_abiertos/"
VOTACIONES_URL = BASE_URL + "votaciones"
TABLA_VOTOS_URL = BASE_URL + "app/votaciones/functions/viewTableVot.php"

# Estatus del cargo. En datos abiertos viene ``en_funciones``; los
# senadores que votaron pero ya no están en el corte (licencia,
# renuncia, suplente que cubrió) se rescatan de su perfil o de la tabla.
ESTATUS_EN_FUNCIONES = "en funciones"
ESTATUS_NO_EN_DATOS_ABIERTOS = "no en datos abiertos"

SENADORES_RP = 32

# Intersticial anti-bot de Incapsula servido con HTTP 200.
INCAPSULA_MARKER = b"Incapsula incident ID"


def es_bloqueo_incapsula(content: bytes) -> bool:
    """True si el cuerpo es la página de bloqueo de Incapsula."""
    return INCAPSULA_MARKER in content

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

_RE_JSON_SENADORES = re.compile(r"senadoresDatosAb_(\d{8})\.json", re.IGNORECASE)
_RE_POR_ANIO = re.compile(r"/votaciones/por_anio/LXVI/(\d+)")
_RE_VOTACION = re.compile(r"/66/votacion/(\d+)")
_RE_SENADOR_VOTO = re.compile(r"/66/votaciones/(\d+)#info")
_RE_SENADOR_PERFIL = re.compile(r"/66/senador/(\d+)")
_RE_FECHA = re.compile(r"(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóúü]+)\s+de\s+(\d{4})")


@dataclass(frozen=True)
class SenadoDatos:
    """Resultado completo de la ingesta del Senado."""

    legisladores: tuple[Legislador, ...]
    votaciones: tuple[Votacion, ...]
    votos: tuple[Voto, ...]
    corte_datos_abiertos: date
    datos_abiertos_url: str
    totales_derivados: tuple[str, ...] = ()


def _norm(texto: str) -> str:
    """Minúsculas sin acentos (para comparar etiquetas del portal)."""
    decomposed = unicodedata.normalize("NFKD", texto.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _vacio(texto: object) -> str | None:
    """Cadena recortada o ``None`` si viene vacía o no es texto."""
    if not isinstance(texto, str):
        return None
    return " ".join(texto.split()) or None


def _fecha(texto: str) -> date | None:
    """Fechas del portal tipo ``Martes 01 de julio de 2025`` → date."""
    m = _RE_FECHA.search(texto)
    if not m:
        return None
    mes = MESES.get(m.group(2).lower())
    if mes is None:
        return None
    return date(int(m.group(3)), mes, int(m.group(1)))


def _principio(texto: str) -> Principio | None:
    """Principio de elección desde el texto tipo ``tipoEleccion``."""
    n = _norm(texto)
    if "mayoria relativa" in n:
        return Principio.MR
    if "primera minoria" in n:
        return Principio.PRIMERA_MINORIA
    if "proporcional" in n:
        return Principio.RP
    return None


def parse_datos_abiertos_index(html: str, url: str) -> tuple[str, date]:
    """Índice de datos abiertos → ``(URL del JSON de senadores, corte)``.

    El nombre del archivo lleva la fecha de corte en DDMMYYYY; se toma
    el ``senadoresDatosAb_<fecha>.json`` más reciente del índice.
    """
    soup = BeautifulSoup(html, "html.parser")
    mejor: tuple[date, str] | None = None
    for a in soup.find_all("a", href=True):
        m = _RE_JSON_SENADORES.search(a["href"])
        if not m:
            continue
        digitos = m.group(1)
        corte = date(int(digitos[4:]), int(digitos[2:4]), int(digitos[:2]))
        if mejor is None or corte > mejor[0]:
            mejor = (corte, urljoin(url, a["href"]))
    if mejor is None:
        raise ValueError(f"Sin senadoresDatosAb_*.json en {url}")
    return mejor[1], mejor[0]


def parse_senadores(texto: str, url: str) -> list[Legislador]:
    """JSON de datos abiertos → lista de ``Legislador`` del Senado.

    ``Estado: "Lista Nacional"`` marca a los 32 de representación
    proporcional y queda como ``entidad=None``; el estatus llega como
    ``en_funciones`` y se normaliza a ``en funciones``.
    """
    registros = json.loads(texto)
    legisladores: list[Legislador] = []
    for rec in registros:
        estado = _vacio(rec.get("Estado"))
        entidad = (
            None
            if estado is None or _norm(estado) == "lista nacional"
            else normalize_entidad(estado)
        )
        telefono = _vacio(rec.get("telefono"))
        extension = _vacio(rec.get("extension"))
        if telefono is not None and extension is not None:
            telefono = f"{telefono} ext. {extension}"
        estatus = _vacio(rec.get("estatus"))
        legisladores.append(
            Legislador(
                source=SOURCE,
                source_id=str(rec["idSenador"]),
                nombre=" ".join(
                    f"{rec.get('Nombre', '')} {rec.get('Apellidos', '')}".split()
                ),
                camara=Camara.SENADO,
                legislatura=LEGISLATURA,
                entidad=entidad,
                source_url=url,
                principio=_principio(rec.get("tipoEleccion") or ""),
                partido=normalize_partido(rec.get("Fraccion") or "")
                if _vacio(rec.get("Fraccion"))
                else None,
                estatus=estatus.replace("_", " ") if estatus else None,
                suplente=_vacio(rec.get("Suplente")),
                sexo=_vacio(rec.get("Sexo")),
                correo=_vacio(rec.get("correo")),
                telefono=telefono,
            )
        )
    return legisladores


def parse_anios(html: str, url: str) -> list[str]:
    """Página de votaciones → URLs absolutas de los años de ejercicio."""
    soup = BeautifulSoup(html, "html.parser")
    anios: list[str] = []
    vistos: set[str] = set()
    for a in soup.find_all("a", href=_RE_POR_ANIO):
        href = a["href"]
        if href in vistos:
            continue
        vistos.add(href)
        anios.append(urljoin(url, href))
    return anios


def parse_votaciones_anio(
    html: str, url: str
) -> list[tuple[str, date | None, str, str]]:
    """Año de ejercicio → ``(votacion_id, fecha, titulo, periodo)``.

    La página agrupa las votaciones bajo encabezados ``h4.text-center``
    ("Primer Periodo Ordinario", "Segundo Receso", …) y cada una es un
    enlace ``/66/votacion/<id>`` con la fecha en el ``<strong>`` del
    mismo ``div``. ``periodo`` lleva como prefijo el año de la URL
    (``"3: Primer Periodo Ordinario Tercer Año de Ejercicio"``).
    """
    m_anio = re.search(r"(\d+)\s*$", url)
    anio = m_anio.group(1) if m_anio else ""
    soup = BeautifulSoup(html, "html.parser")
    metas: list[tuple[str, date | None, str, str]] = []
    periodo_txt = ""
    vistos: set[str] = set()
    for el in soup.find_all(["h4", "a"]):
        if el.name == "h4":
            if "text-center" in (el.get("class") or []):
                periodo_txt = " ".join(el.get_text(" ", strip=True).split())
            continue
        m = _RE_VOTACION.search(el.get("href") or "")
        if not m or m.group(1) in vistos:
            continue
        vistos.add(m.group(1))
        div = el.find_parent("div")
        strong = div.find("strong") if div is not None else None
        fecha = _fecha(strong.get_text(" ", strip=True)) if strong else None
        titulo = " ".join(el.get_text(" ", strip=True).split())
        periodo = f"{anio}: {periodo_txt}" if periodo_txt else anio
        metas.append((m.group(1), fecha, titulo, periodo))
    return metas


def parse_totales(html: str, url: str) -> tuple[int, int, int]:
    """Página de una votación → ``(a favor, en contra, abstención)``.

    La ``table.resultado-votacion`` tiene una celda por sentido con la
    etiqueta ("EN PRO", "EN CONTRA", "ABSTENCIÓN") y el número.
    """
    soup = BeautifulSoup(html, "html.parser")
    tabla = soup.find("table", class_="resultado-votacion")
    if tabla is None:
        raise ValueError(f"Sin table.resultado-votacion en {url}")
    totales: dict[str, int] = {}
    for td in tabla.find_all("td"):
        textos = list(td.stripped_strings)
        if len(textos) < 2 or not textos[-1].isdigit():
            continue
        totales[_norm(textos[0])] = int(textos[-1])
    try:
        return totales["en pro"], totales["en contra"], totales["abstencion"]
    except KeyError:
        raise ValueError(
            f"table.resultado-votacion incompleta en {url}"
        ) from None


def _nombre_de_tabla(texto: str) -> str:
    """``Sen. Apellidos, Nombre`` → ``Nombre Apellidos``."""
    nombre = re.sub(r"^Sen\.?\s*", "", texto.strip())
    if "," in nombre:
        apellidos, _, pila = nombre.partition(",")
        nombre = f"{pila.strip()} {apellidos.strip()}"
    return " ".join(nombre.split())


def parse_tabla_votos(
    html: str, url: str, votacion_id: str
) -> list[tuple[Voto, str]]:
    """Fragmento ``viewTableVot.php`` → ``(Voto, nombre del senador)``.

    La primera fila es de encabezado; en las de datos el id del senador
    va en el enlace ``/66/votaciones/<id>#info`` y el sentido del voto
    en la última celda. Solo aparece quien votó; el nombre se devuelve
    reordenado ("Apellidos, Nombre" → "Nombre Apellidos") para rescatar
    a quienes falten en datos abiertos.
    """
    soup = BeautifulSoup(html, "html.parser")
    votos: list[tuple[Voto, str]] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 4:
            continue
        a = tds[1].find("a", href=_RE_SENADOR_VOTO)
        if a is None:
            continue
        senador_id = _RE_SENADOR_VOTO.search(a["href"]).group(1)
        partido_txt = tds[2].get_text(" ", strip=True)
        votos.append(
            (
                Voto(
                    source=SOURCE,
                    votacion_id=votacion_id,
                    legislador_source_id=senador_id,
                    sentido=normalize_sentido(
                        SOURCE, tds[-1].get_text(" ", strip=True)
                    ),
                    partido=normalize_partido(partido_txt)
                    if partido_txt
                    else None,
                    source_url=url,
                ),
                _nombre_de_tabla(a.get_text(" ", strip=True)),
            )
        )
    return votos


def parse_perfil(html: str, url: str) -> Legislador:
    """Perfil ``/66/senador/<id>`` → ``Legislador``.

    Se usa para senadores que votaron pero ya no aparecen en el corte
    de datos abiertos, de ahí el estatus fijo. El partido sale del
    nombre del archivo de ``img.logo-partido`` (``MORENA_.png``).
    """
    soup = BeautifulSoup(html, "html.parser")
    m = _RE_SENADOR_PERFIL.search(url)
    senador_id = m.group(1) if m else ""

    nombre = ""
    h2 = soup.find("h2", class_="nSenador")
    if h2 is not None:
        nombre = re.sub(
            r"^Senador[ae]?\s+", "", h2.get_text(" ", strip=True)
        )
    if not nombre:
        title = soup.find("title")
        if title is not None:
            nombre = re.sub(r"^Sen\.?\s*", "", title.get_text(" ", strip=True))
    nombre = " ".join(nombre.split())

    h3 = soup.find("h3", class_="tipoEleccion")
    principio = (
        _principio(h3.get_text(" ", strip=True)) if h3 is not None else None
    )

    entidad = None
    h4 = soup.find("h4", class_="nEstadi")
    if h4 is not None:
        texto = h4.get_text(" ", strip=True)
        if _norm(texto) != "lista nacional":
            try:
                entidad = normalize_entidad(texto)
            except KeyError:
                entidad = None

    partido = None
    img = soup.find("img", class_="logo-partido")
    if img is not None and img.get("src"):
        partido = normalize_partido(Path(img["src"]).stem.rstrip("_"))

    suplente = None
    p = soup.find("p", class_="suplente")
    if p is not None:
        a = p.find("a")
        if a is not None:
            suplente = _vacio(a.get_text(" ", strip=True))

    return Legislador(
        source=SOURCE,
        source_id=senador_id,
        nombre=nombre,
        camara=Camara.SENADO,
        legislatura=LEGISLATURA,
        entidad=entidad,
        source_url=url,
        principio=principio,
        partido=partido,
        estatus=ESTATUS_NO_EN_DATOS_ABIERTOS,
        suplente=suplente,
    )


def validar_senado(datos: SenadoDatos) -> dict:
    """Comprobaciones de coherencia de la ingesta.

    a) Los votos nominales por sentido cuadran con los totales de la
       página de cada votación.
    b) Los senadores en funciones son ``State.senadores`` por entidad
       (2 MR + 1 primera minoría) y 32 de representación proporcional
       sin entidad.
    c) Todo ``Voto.legislador_source_id`` resuelve a un ``Legislador``,
       todo legislador tiene nombre y no hay sentidos sin traducir.

    Los ids en ``datos.totales_derivados`` son votaciones cuya página no
    traía ``table.resultado-votacion`` y cuyos totales se derivaron del
    fragmento de votos; se reportan aparte y se excluyen de (a), pues
    compararlos consigo mismos no aporta nada.

    ``ok`` es True solo si (b) y (c) pasan; los desajustes de (a) se
    reportan en ``mismatches`` sin tumbar la ingesta.
    """
    # (a) votos vs totales del portal
    conteo = Counter((v.votacion_id, v.sentido) for v in datos.votos)
    derivados = set(datos.totales_derivados)
    mismatches: list[str] = []
    comparaciones = 0
    for vot in datos.votaciones:
        if vot.source_id in derivados:
            continue
        for sentido, esperado in (
            (Sentido.A_FAVOR, vot.a_favor),
            (Sentido.EN_CONTRA, vot.en_contra),
            (Sentido.ABSTENCION, vot.abstencion),
        ):
            comparaciones += 1
            real = conteo.get((vot.source_id, sentido), 0)
            if real != esperado:
                mismatches.append(
                    f"votacion={vot.source_id} {sentido.value}: "
                    f"portal={esperado} tabla={real}"
                )

    # (b) composición del Senado vs estados
    en_funciones = [
        l for l in datos.legisladores if l.estatus == ESTATUS_EN_FUNCIONES
    ]
    por_entidad = Counter(l.entidad for l in en_funciones if l.entidad)
    composicion: dict[str, Counter] = {}
    for l in en_funciones:
        if l.entidad:
            composicion.setdefault(l.entidad, Counter())[l.principio] += 1
    entidades_descuadradas = {
        s.clave: {
            "esperados": s.senadores,
            "senadores": por_entidad.get(s.clave, 0),
            "mr": composicion.get(s.clave, Counter())[Principio.MR],
            "primera_minoria": composicion.get(s.clave, Counter())[
                Principio.PRIMERA_MINORIA
            ],
        }
        for s in load_states()
        if por_entidad.get(s.clave, 0) != s.senadores
        or composicion.get(s.clave, Counter())[Principio.MR] != 2
        or composicion.get(s.clave, Counter())[Principio.PRIMERA_MINORIA] != 1
    }
    rp = [l for l in en_funciones if l.principio == Principio.RP]
    rp_sin_entidad = sum(1 for l in rp if l.entidad is None)

    # (c) votos que no resuelven a legislador / sentido desconocido
    ids_legisladores = {l.source_id for l in datos.legisladores}
    sin_legislador = sorted(
        {v.legislador_source_id for v in datos.votos} - ids_legisladores,
        key=lambda x: (0, int(x)) if x.isdigit() else (1, x),
    )
    sentido_otro = sum(1 for v in datos.votos if v.sentido is Sentido.OTRO)
    sin_nombre = sorted(
        l.source_id for l in datos.legisladores if not l.nombre.strip()
    )

    ok = (
        not entidades_descuadradas
        and len(rp) == SENADORES_RP
        and rp_sin_entidad == SENADORES_RP
        and not sin_legislador
        and sentido_otro == 0
        and not sin_nombre
    )
    return {
        "ok": ok,
        "votos_vs_totales": {
            "comparaciones": comparaciones,
            "mismatches": mismatches,
        },
        "senadores": {
            "en_funciones": len(en_funciones),
            "entidades_descuadradas": entidades_descuadradas,
            "rp_en_funciones": len(rp),
            "rp_sin_entidad": rp_sin_entidad,
            "rp_esperados": SENADORES_RP,
        },
        "votos_sin_legislador": sin_legislador,
        "votos_sentido_otro": sentido_otro,
        "legisladores_sin_nombre": sin_nombre,
        "totales_derivados": sorted(derivados, key=int),
    }


class Senado(Source):
    name = "Senado de la República — Votaciones"
    url = "https://senado.gob.mx/66/votaciones"
    levels = (Level.FEDERAL,)
    dimensions = ("senadores", "votaciones_federales", "comisiones")

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        max_votaciones: int | None = None,
    ) -> None:
        self.client = client
        self.max_votaciones = max_votaciones

    def _texto(
        self, client: HttpClient, url: str, params: dict | None = None
    ) -> tuple[str, str]:
        resp = client.get(url, params=params)
        return resp.text, str(resp.url)

    def fetch(self) -> SenadoDatos:
        """Descarga y normaliza senadores, votaciones y votos."""
        client = self.client or HttpClient(SOURCE, reject=es_bloqueo_incapsula)
        try:
            return self._fetch(client)
        finally:
            if self.client is None:
                client.close()

    def _fetch(self, client: HttpClient) -> SenadoDatos:
        html, url = self._texto(client, DATOS_ABIERTOS_URL)
        json_url, corte = parse_datos_abiertos_index(html, url)
        logger.info("Datos abiertos: %s (corte %s)", json_url, corte)

        texto, url = self._texto(client, json_url)
        legisladores = {l.source_id: l for l in parse_senadores(texto, url)}
        logger.info("Senadores en datos abiertos: %d", len(legisladores))

        html, url = self._texto(client, VOTACIONES_URL)
        anios = parse_anios(html, url)
        logger.info("Años de ejercicio: %s", ", ".join(anios))

        votaciones: list[Votacion] = []
        votos: list[Voto] = []
        nombres_tabla: dict[str, tuple[str, str | None]] = {}
        totales_derivados: list[str] = []
        procesadas = 0
        for anio_url in anios:
            html, url = self._texto(client, anio_url)
            metas = parse_votaciones_anio(html, url)
            logger.info(
                "Año %s: %d votaciones",
                anio_url.rstrip("/").rsplit("/", 1)[-1],
                len(metas),
            )
            for vid, fecha, titulo, periodo in metas:
                if (
                    self.max_votaciones is not None
                    and procesadas >= self.max_votaciones
                ):
                    break
                votacion_url = urljoin(BASE_URL, f"votacion/{vid}")
                html, url = self._texto(client, votacion_url)
                try:
                    totales = parse_totales(html, url)
                except ValueError:
                    # La página existe pero sin table.resultado-votacion
                    # (p. ej. 4716): los totales se derivan del fragmento.
                    totales = None
                html, url = self._texto(
                    client,
                    TABLA_VOTOS_URL,
                    params={
                        "action": "ajax",
                        "cell": "1",
                        "order": "DESC",
                        "votacion": vid,
                        "q": "",
                    },
                )
                tabla = parse_tabla_votos(html, url, vid)
                for voto, nombre in tabla:
                    votos.append(voto)
                    nombres_tabla.setdefault(
                        voto.legislador_source_id, (nombre, voto.partido)
                    )
                if totales is None:
                    conteo = Counter(v.sentido for v, _ in tabla)
                    totales = (
                        conteo[Sentido.A_FAVOR],
                        conteo[Sentido.EN_CONTRA],
                        conteo[Sentido.ABSTENCION],
                    )
                    totales_derivados.append(vid)
                    logger.warning(
                        "votacion %s sin tabla de totales; "
                        "se derivan del fragmento: %s",
                        vid,
                        totales,
                    )
                a_favor, en_contra, abstencion = totales
                votaciones.append(
                    Votacion(
                        source=SOURCE,
                        source_id=vid,
                        camara=Camara.SENADO,
                        legislatura=LEGISLATURA,
                        fecha=fecha,
                        titulo=titulo,
                        a_favor=a_favor,
                        en_contra=en_contra,
                        abstencion=abstencion,
                        solo_asistencia=0,
                        ausente=None,
                        source_url=votacion_url,
                        periodo=periodo,
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

        # senadores que votaron pero ya no están en datos abiertos
        faltantes = sorted(
            {v.legislador_source_id for v in votos} - set(legisladores),
            key=lambda x: int(x) if x.isdigit() else 0,
        )
        if faltantes:
            logger.info(
                "Senadores fuera de datos abiertos: %s", ", ".join(faltantes)
            )
        for senador_id in faltantes:
            perfil_url = urljoin(BASE_URL, f"senador/{senador_id}")
            try:
                html, url = self._texto(client, perfil_url)
                legisladores[senador_id] = parse_perfil(html, url)
            except FetchError:
                nombre, partido = nombres_tabla.get(senador_id, ("", None))
                legisladores[senador_id] = Legislador(
                    source=SOURCE,
                    source_id=senador_id,
                    nombre=nombre,
                    camara=Camara.SENADO,
                    legislatura=LEGISLATURA,
                    entidad=None,
                    source_url=perfil_url,
                    partido=partido,
                    estatus=ESTATUS_NO_EN_DATOS_ABIERTOS,
                )
                logger.info(
                    "  senador %s sin perfil: datos mínimos de la tabla",
                    senador_id,
                )

        return SenadoDatos(
            legisladores=tuple(
                legisladores[k]
                for k in sorted(
                    legisladores, key=lambda x: int(x) if x.isdigit() else 0
                )
            ),
            votaciones=tuple(votaciones),
            votos=tuple(votos),
            corte_datos_abiertos=corte,
            datos_abiertos_url=json_url,
            totales_derivados=tuple(totales_derivados),
        )
