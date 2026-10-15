"""Cliente HTTP compartido para las fuentes legislativas.

TLS con certifi + intermedios propios (ver ``certs/intermediates.pem``),
cookie jar por sesión, rate limiting por host, reintentos con backoff
exponencial, caché en crudo bajo ``data/raw/<fuente>/`` y detección de
codificación por respuesta. Prohibido ``verify=False``.
"""

import codecs
import hashlib
import json
import re
import ssl
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Self

import certifi
import httpx

from ..states import DATA_DIR

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 TuCurul/0.1 "
    "(+https://github.com/dar4datascience/TuCurul)"
)

# Hosts que solo sirven HTTP plano (SIL de SEGOB no tiene HTTPS).
PLAIN_HTTP_HOSTS = frozenset({"sil.gobernacion.gob.mx"})

RAW_DIR = DATA_DIR / "raw"

INTERMEDIATES_PEM = Path(__file__).parent / "certs" / "intermediates.pem"

# Headers que vale la pena conservar junto al cuerpo en caché.
CACHE_HEADERS = ("content-type", "last-modified", "etag")

# Ventana del HTML donde se busca el <meta charset>.
META_HEAD_BYTES = 4096

_META_CHARSET = re.compile(
    rb"<meta[^>]+charset\s*=\s*[\"']?\s*([a-zA-Z0-9_-]+)", re.IGNORECASE
)
_HEADER_CHARSET = re.compile(r"charset\s*=\s*[\"']?\s*([\w.-]+)", re.IGNORECASE)

# Nombres que los navegadores tratan como windows-1252 aunque digan otra cosa.
_CP1252_ALIAS = {
    "iso88591",
    "latin1",
    "usascii",
    "ascii",
    "iso885911985",
}


class CacheMode(Enum):
    """Política de caché del cliente."""

    NORMAL = "normal"
    OFFLINE = "offline"
    REFRESH = "refresh"


class FetchError(Exception):
    """Descarga fallida: estado HTTP no reintentable o reintentos agotados."""

    def __init__(
        self, url: str, status: int | None = None, detalle: str = ""
    ) -> None:
        self.url = url
        self.status = status
        msg = f"Error al descargar {url}"
        if status is not None:
            msg += f" (HTTP {status})"
        if detalle:
            msg += f": {detalle}"
        super().__init__(msg)


class CacheMiss(FetchError):
    """La URL no está en caché y el modo OFFLINE prohíbe usar la red."""

    def __init__(self, url: str) -> None:
        super().__init__(url, detalle="ausente de la caché (modo offline)")


@dataclass(frozen=True)
class Response:
    """Respuesta HTTP con su codificación detectada."""

    url: str
    status: int
    content: bytes
    encoding: str
    headers: dict[str, str]
    from_cache: bool

    @property
    def text(self) -> str:
        """Cuerpo decodificado; quita el BOM si lo hay."""
        codec = "utf-8-sig" if self.encoding == "utf-8" else self.encoding
        return self.content.decode(codec, errors="replace")


def ssl_context() -> ssl.SSLContext:
    """Contexto TLS: certifi + los intermedios que los portales omiten."""
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cafile=str(INTERMEDIATES_PEM))
    return context


def _normaliza_codec(nombre: str) -> str | None:
    """Nombre de codec Python, con la familia latin-1 mapeada a cp1252."""
    clave = re.sub(r"[^a-z0-9]", "", nombre.strip().lower())
    if clave in _CP1252_ALIAS:
        return "cp1252"
    try:
        return codecs.lookup(nombre.strip()).name
    except LookupError:
        return None


def _declared_charset(content: bytes, content_type: str | None) -> str | None:
    """Charset declarado en Content-Type o en un <meta> de los primeros 4 KiB."""
    if content_type:
        m = _HEADER_CHARSET.search(content_type)
        if m:
            codec = _normaliza_codec(m.group(1))
            if codec:
                return codec
    m = _META_CHARSET.search(content[:META_HEAD_BYTES])
    if m:
        return _normaliza_codec(m.group(1).decode("ascii"))
    return None


def detect_encoding(content: bytes, content_type: str | None = None) -> str:
    """Detecta la codificación del cuerpo, en este orden:

    1. BOM (UTF-8 o UTF-16).
    2. UTF-8 estricto: si decodifica sin errores, se usa aunque la página
       declare otra cosa — hay listados del SITL que dicen ``iso-8859-1``
       pero traen bytes UTF-8 reales.
    3. Charset declarado (header Content-Type, luego ``<meta charset>``),
       con ``iso-8859-1``/``latin-1``/``us-ascii`` mapeados a ``cp1252``
       como hacen los navegadores.
    4. Fallback ``cp1252``: la Gaceta y el SIL publican latin-1.
    """
    if content.startswith(codecs.BOM_UTF8):
        return "utf-8"
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    try:
        content.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    return _declared_charset(content, content_type) or "cp1252"


def decode(content: bytes, content_type: str | None = None) -> tuple[str, str]:
    """Decodifica el cuerpo y devuelve ``(texto, codificación)``."""
    encoding = detect_encoding(content, content_type)
    codec = "utf-8-sig" if encoding == "utf-8" else encoding
    return content.decode(codec, errors="replace"), encoding


class HttpClient:
    """Cliente HTTP por fuente: cookies, rate limit, reintentos y caché.

    ``reject`` es un predicado sobre el cuerpo para detectar páginas de
    bloqueo anti-bot servidas con 2xx (p. ej. intersticiales de
    Incapsula): se reintentan como si fueran 5xx, nunca se cachean y un
    cuerpo cacheado que las satisfaga se ignora.

    Se usa como context manager::

        with HttpClient("sitl_diputados") as client:
            resp = client.get("https://sitl.diputados.gob.mx/...")
    """

    def __init__(
        self,
        source: str,
        *,
        cache_dir: Path | None = None,
        mode: CacheMode = CacheMode.NORMAL,
        min_interval: float = 1.0,
        timeout: float = 30.0,
        retries: int = 4,
        backoff: float = 2.0,
        user_agent: str = DEFAULT_USER_AGENT,
        plain_http_hosts: Iterable[str] = PLAIN_HTTP_HOSTS,
        reject: Callable[[bytes], bool] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.cache_dir = Path(cache_dir) if cache_dir is not None else RAW_DIR / source
        self.mode = mode
        self.min_interval = min_interval
        self.retries = retries
        self.backoff = backoff
        self.plain_http_hosts = frozenset(h.lower() for h in plain_http_hosts)
        self.reject = reject
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self._client = httpx.Client(
            verify=ssl_context(),
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Cierra el cliente (y su cookie jar)."""
        self._client.close()

    def get(self, url: str, params: dict | None = None) -> Response:
        """GET con caché, rate limit por host y reintentos."""
        request_url = self._request_url(url, params)
        key = hashlib.sha256(f"GET {request_url}".encode()).hexdigest()
        if self.mode is not CacheMode.REFRESH:
            cached = self._read_cache(key)
            if (
                cached is not None
                and self.reject is not None
                and self.reject(cached.content)
            ):
                cached = None  # página de bloqueo cacheada: se refetcha
            if cached is not None:
                return cached
            if self.mode is CacheMode.OFFLINE:
                raise CacheMiss(str(request_url))
        response = self._fetch(request_url)
        encoding = detect_encoding(
            response.content, response.headers.get("content-type")
        )
        if 200 <= response.status_code < 300:
            self._write_cache(key, request_url, response, encoding)
        return Response(
            url=str(request_url),
            status=response.status_code,
            content=response.content,
            encoding=encoding,
            headers=dict(response.headers),
            from_cache=False,
        )

    def _request_url(self, url: str, params: dict | None) -> httpx.URL:
        """URL final con query ordenada; valida el esquema."""
        request_url = httpx.URL(url)
        if request_url.scheme == "http":
            if request_url.host not in self.plain_http_hosts:
                raise ValueError(
                    f"HTTP plano no permitido: {request_url.host} "
                    "(solo sil.gobernacion.gob.mx)"
                )
        elif request_url.scheme != "https":
            raise ValueError(f"Esquema no soportado: {request_url.scheme!r}")
        if params:
            request_url = request_url.copy_merge_params(params)
        if request_url.params:
            request_url = request_url.copy_with(
                params=sorted(request_url.params.multi_items())
            )
        return request_url

    def _throttle(self, host: str) -> None:
        """Espera lo necesario para respetar ``min_interval`` por host."""
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._clock()

    def _fetch(self, url: httpx.URL) -> httpx.Response:
        """GET con reintentos ante timeouts, errores de transporte, 429 y 5xx."""
        host = url.host or ""
        for attempt in range(self.retries + 1):
            self._throttle(host)
            try:
                response = self._client.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == self.retries:
                    raise FetchError(str(url), detalle=str(exc)) from exc
            else:
                status = response.status_code
                rechazada = False
                if 200 <= status < 300:
                    if self.reject is None or not self.reject(response.content):
                        return response
                    rechazada = True
                elif status != 429 and status < 500:
                    raise FetchError(str(url), status=status)
                if attempt == self.retries:
                    raise FetchError(
                        str(url),
                        status=status,
                        detalle=(
                            "respuesta rechazada (página de bloqueo)"
                            if rechazada
                            else ""
                        ),
                    )
            self._sleep(self.backoff * 2**attempt)
        raise AssertionError("inalcanzable")

    def _read_cache(self, key: str) -> Response | None:
        body_path = self.cache_dir / f"{key}.body"
        meta_path = self.cache_dir / f"{key}.json"
        if not (body_path.is_file() and meta_path.is_file()):
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return Response(
            url=meta["url"],
            status=meta["status"],
            content=body_path.read_bytes(),
            encoding=meta["encoding"],
            headers=meta.get("headers", {}),
            from_cache=True,
        )

    def _write_cache(
        self, key: str, url: httpx.URL, response: httpx.Response, encoding: str
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.body").write_bytes(response.content)
        meta = {
            "url": str(url),
            "status": response.status_code,
            "headers": {
                h: response.headers[h] for h in CACHE_HEADERS if h in response.headers
            },
            "encoding": encoding,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
