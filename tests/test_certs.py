"""Bundle de intermedios TLS: los 3 esperados, vigentes y cargables.

Falla si algún intermedio vence en menos de 90 días — hay que renovar
``certs/intermediates.pem`` antes de que los portales queden inalcanzables.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes

from tucurul.sources import http

PEM = Path(http.__file__).parent / "certs" / "intermediates.pem"

# (CN del intermedio, prefijo y sufijo de la huella SHA-256) según el
# cuadro del issue #10.
ESPERADOS = [
    ("RapidSSL TLS RSA CA G1", "44:22:E9:63", "AD:C6:9B"),
    ("DigiCert Global G2 TLS RSA SHA256 2020 CA1", "C8:02:5F:9F", "D0:B6:25:A9"),
    ("Go Daddy Secure Certificate Authority - G2", "97:3A:41:27", "32:04:1A:A6"),
]


def _certificados() -> list:
    return x509.load_pem_x509_certificates(PEM.read_bytes())


def _huella(cert) -> str:
    return ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))


def test_exactamente_tres_intermedios():
    assert len(_certificados()) == 3


@pytest.mark.parametrize("cn,prefijo,sufijo", ESPERADOS)
def test_huella_sha256(cn, prefijo, sufijo):
    por_cn = {
        cert.subject.rfc4514_string(): cert for cert in _certificados()
    }
    cert = next((c for s, c in por_cn.items() if f"CN={cn}" in s), None)
    assert cert is not None, f"falta el intermedio {cn}"
    huella = _huella(cert)
    assert huella.startswith(prefijo)
    assert huella.endswith(sufijo)


def test_vigencia_minima_90_dias():
    limite = datetime.now(UTC) + timedelta(days=90)
    for cert in _certificados():
        assert cert.not_valid_after_utc > limite, (
            f"{cert.subject.rfc4514_string()} vence {cert.not_valid_after_utc}"
        )


def test_ssl_context_carga_los_tres():
    context = http.ssl_context()
    cns = {
        valor
        for cert in context.get_ca_certs()
        for rdn in cert["subject"]
        for nombre, valor in rdn
        if nombre == "commonName"
    }
    for cn, _, _ in ESPERADOS:
        assert cn in cns
