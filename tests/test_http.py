"""Cliente HTTP compartido: UA, rate limit, reintentos, caché y cookies.

Todas las pruebas son offline salvo la marcada ``network``: el transporte
es ``httpx.MockTransport`` y el reloj/sleep van inyectados.
"""

import json
from pathlib import Path

import httpx
import pytest

from tucurul.sources.http import (
    DEFAULT_USER_AGENT,
    CacheMiss,
    CacheMode,
    FetchError,
    HttpClient,
)


class RelojFalso:
    """Reloj manual: ``sleep`` registra la espera y avanza el tiempo."""

    def __init__(self) -> None:
        self.ahora = 0.0
        self.esperas: list[float] = []

    def clock(self) -> float:
        return self.ahora

    def sleep(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.ahora += segundos


def cliente(handler, tmp_path: Path, reloj: RelojFalso, **kwargs) -> HttpClient:
    return HttpClient(
        "prueba",
        cache_dir=tmp_path,
        transport=httpx.MockTransport(handler),
        sleep=reloj.sleep,
        clock=reloj.clock,
        **kwargs,
    )


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"contenido")


def test_user_agent(tmp_path):
    visto = {}

    def handler(request):
        visto["ua"] = request.headers["user-agent"]
        return ok(request)

    with cliente(handler, tmp_path, RelojFalso()) as c:
        c.get("https://ejemplo.test/pagina")
    assert visto["ua"] == DEFAULT_USER_AGENT


def test_rate_limit_mismo_host(tmp_path):
    reloj = RelojFalso()
    with cliente(ok, tmp_path, reloj, min_interval=1.0) as c:
        c.get("https://ejemplo.test/a")
        c.get("https://ejemplo.test/b")
    assert reloj.esperas == [1.0]


def test_rate_limit_por_host(tmp_path):
    """Hosts distintos no comparten limiter: no hay espera."""
    reloj = RelojFalso()
    with cliente(ok, tmp_path, reloj, min_interval=1.0) as c:
        c.get("https://aaa.test/pagina")
        c.get("https://bbb.test/pagina")
    assert reloj.esperas == []


def test_reintenta_503_y_luego_200(tmp_path):
    llamadas = []

    def handler(request):
        llamadas.append(request)
        if len(llamadas) == 1:
            return httpx.Response(503)
        return ok(request)

    reloj = RelojFalso()
    with cliente(handler, tmp_path, reloj, retries=3, backoff=2.0) as c:
        resp = c.get("https://ejemplo.test/")
    assert resp.status == 200
    assert len(llamadas) == 2
    assert reloj.esperas == [2.0]  # backoff * 2**0


def test_reintenta_timeout_de_conexion(tmp_path):
    llamadas = []

    def handler(request):
        llamadas.append(request)
        if len(llamadas) == 1:
            raise httpx.ConnectTimeout("agotado", request=request)
        return ok(request)

    reloj = RelojFalso()
    with cliente(handler, tmp_path, reloj, retries=3, backoff=2.0) as c:
        resp = c.get("https://ejemplo.test/")
    assert resp.status == 200
    assert reloj.esperas == [2.0]


def test_reintentos_agotados(tmp_path):
    llamadas = []

    def handler(request):
        llamadas.append(request)
        return httpx.Response(503)

    reloj = RelojFalso()
    with (
        cliente(handler, tmp_path, reloj, retries=2, backoff=2.0) as c,
        pytest.raises(FetchError) as exc,
    ):
        c.get("https://ejemplo.test/")
    assert exc.value.status == 503
    assert len(llamadas) == 3  # 1 intento + 2 reintentos
    assert reloj.esperas == [2.0, 4.0]


def test_404_sin_reintento_ni_cache(tmp_path):
    llamadas = []

    def handler(request):
        llamadas.append(request)
        return httpx.Response(404)

    reloj = RelojFalso()
    with (
        cliente(handler, tmp_path, reloj, retries=3) as c,
        pytest.raises(FetchError) as exc,
    ):
        c.get("https://ejemplo.test/faltante")
    assert exc.value.status == 404
    assert len(llamadas) == 1
    assert reloj.esperas == []
    assert list(tmp_path.iterdir()) == []


def test_cache_hit_sin_transporte(tmp_path):
    llamadas = []

    def handler(request):
        llamadas.append(request)
        return ok(request)

    reloj = RelojFalso()
    url = "https://ejemplo.test/pagina"
    with cliente(handler, tmp_path, reloj) as c:
        resp = c.get(url)
    assert not resp.from_cache
    with cliente(handler, tmp_path, reloj) as c:
        resp2 = c.get(url)
    assert resp2.from_cache
    assert resp2.content == b"contenido"
    assert len(llamadas) == 1
    # archivos de caché: body + json
    archivos = {p.suffix for p in tmp_path.iterdir()}
    assert archivos == {".body", ".json"}


def test_offline_miss_y_hit(tmp_path):
    llamadas = []

    def handler(request):
        llamadas.append(request)
        return ok(request)

    reloj = RelojFalso()
    url = "https://ejemplo.test/pagina"
    with cliente(handler, tmp_path, reloj) as c:
        c.get(url)
    with cliente(handler, tmp_path, reloj, mode=CacheMode.OFFLINE) as c:
        with pytest.raises(CacheMiss):
            c.get("https://ejemplo.test/otra")
        resp = c.get(url)
    assert resp.from_cache
    assert resp.content == b"contenido"
    assert len(llamadas) == 1


def test_refresh_redescarga(tmp_path):
    llamadas = []

    def handler(request):
        llamadas.append(request)
        return httpx.Response(200, content=f"v{len(llamadas)}".encode())

    reloj = RelojFalso()
    url = "https://ejemplo.test/pagina"
    with cliente(handler, tmp_path, reloj) as c:
        assert c.get(url).content == b"v1"
    with cliente(handler, tmp_path, reloj, mode=CacheMode.REFRESH) as c:
        resp = c.get(url)
    assert resp.content == b"v2" and not resp.from_cache
    # la caché quedó actualizada con la nueva descarga
    with cliente(handler, tmp_path, reloj) as c:
        assert c.get(url).content == b"v2"
    assert len(llamadas) == 2


def test_params_cambian_clave_de_cache(tmp_path):
    llamadas = []

    def handler(request):
        llamadas.append(request)
        return ok(request)

    reloj = RelojFalso()
    with cliente(handler, tmp_path, reloj) as c:
        c.get("https://e.test/p", params={"b": 2, "a": 1})
        c.get("https://e.test/p", params={"a": 1, "b": 2})  # mismo orden → hit
        c.get("https://e.test/p", params={"a": 1})  # distintos → miss
    assert len(llamadas) == 2
    urls = {
        json.loads(p.read_text())["url"] for p in tmp_path.glob("*.json")
    }
    assert urls == {"https://e.test/p?a=1&b=2", "https://e.test/p?a=1"}


def test_http_plano_solo_whitelist(tmp_path):
    llamadas = []

    def handler(request):
        llamadas.append(request)
        return ok(request)

    with cliente(handler, tmp_path, RelojFalso()) as c:
        with pytest.raises(ValueError):
            c.get("http://ejemplo.test/")
        resp = c.get("http://sil.gobernacion.gob.mx/x")
    assert resp.status == 200
    assert len(llamadas) == 1


def test_cookies_persistentes(tmp_path):
    def handler(request):
        if request.url.path == "/inicio":
            return httpx.Response(
                200, content=b"ok", headers={"set-cookie": "sesion=abc; Path=/"}
            )
        return httpx.Response(200, content=request.headers.get("cookie", "").encode())

    with cliente(handler, tmp_path, RelojFalso()) as c:
        c.get("https://ejemplo.test/inicio")
        resp = c.get("https://ejemplo.test/datos")
    assert b"sesion=abc" in resp.content


def _es_bloqueo(content: bytes) -> bool:
    """Predicado de prueba: simula la página de bloqueo de Incapsula."""
    return b"BLOQUEO-ANTIBOT" in content


def test_reject_reintenta_2xx_bloqueado(tmp_path):
    """Un 2xx que satisface ``reject`` se reintenta como si fuera 5xx."""
    llamadas = []

    def handler(request):
        llamadas.append(request)
        if len(llamadas) == 1:
            return httpx.Response(200, content=b"BLOQUEO-ANTIBOT")
        return ok(request)

    reloj = RelojFalso()
    with cliente(
        handler, tmp_path, reloj, retries=3, backoff=2.0, reject=_es_bloqueo
    ) as c:
        resp = c.get("https://ejemplo.test/")
    assert resp.status == 200
    assert resp.content == b"contenido"
    assert len(llamadas) == 2
    assert reloj.esperas == [2.0]
    # solo la respuesta buena quedó en caché
    bodies = list(tmp_path.glob("*.body"))
    assert len(bodies) == 1
    assert bodies[0].read_bytes() == b"contenido"


def test_reject_agotado_es_fetch_error_sin_cache(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"BLOQUEO-ANTIBOT")

    reloj = RelojFalso()
    with (
        cliente(
            handler, tmp_path, reloj, retries=2, backoff=2.0,
            reject=_es_bloqueo,
        ) as c,
        pytest.raises(FetchError) as exc,
    ):
        c.get("https://ejemplo.test/")
    assert exc.value.status == 200
    assert "bloqueo" in str(exc.value)
    assert list(tmp_path.iterdir()) == []  # nunca se cachea lo rechazado


def test_reject_cuerpo_cacheado_se_ignora(tmp_path):
    """Una entrada cacheada que satisface ``reject`` se refetcha."""
    llamadas = []

    def handler(request):
        llamadas.append(request)
        return httpx.Response(
            200, content=b"BLOQUEO-ANTIBOT" if len(llamadas) == 1 else b"contenido"
        )

    reloj = RelojFalso()
    url = "https://ejemplo.test/pagina"
    # sin reject, la página de bloqueo queda cacheada como válida
    with cliente(handler, tmp_path, reloj) as c:
        assert c.get(url).content == b"BLOQUEO-ANTIBOT"
    # con reject, la entrada se ignora y se refetcha (auto-cura la caché)
    with cliente(handler, tmp_path, reloj, reject=_es_bloqueo) as c:
        resp = c.get(url)
    assert resp.content == b"contenido"
    assert not resp.from_cache
    assert len(llamadas) == 2


def test_reject_cuerpo_cacheado_offline_es_miss(tmp_path):
    """En OFFLINE, una entrada cacheada rechazada es un CacheMiss."""
    url = "https://ejemplo.test/pagina"
    with cliente(ok, tmp_path, RelojFalso()) as c:
        c.get(url)
    # envenena el cuerpo cacheado como si hubiera entrado un bloqueo
    key = next(p for p in tmp_path.glob("*.body"))
    key.write_bytes(b"BLOQUEO-ANTIBOT")
    with (
        cliente(
            ok, tmp_path, RelojFalso(), mode=CacheMode.OFFLINE,
            reject=_es_bloqueo,
        ) as c,
        pytest.raises(CacheMiss),
    ):
        c.get(url)


@pytest.mark.network
def test_sitl_real(tmp_path):
    """Prueba el bundle TLS contra el SITL real (requiere red)."""
    with HttpClient("sitl_diputados", cache_dir=tmp_path) as c:
        resp = c.get("https://sitl.diputados.gob.mx/LXVI_leg/curricula.php?dipt=1")
    assert resp.status == 200
    assert "Aguascalientes" in resp.text
