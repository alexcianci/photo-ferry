import shutil
import ssl
import subprocess

import pytest

from iphone_photo_drop import tls

needs_openssl = pytest.mark.skipif(tls.find_openssl() is None, reason="openssl not available")


@needs_openssl
def test_generate_self_signed_produces_loadable_cert(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    tls.generate_self_signed("192.168.1.10", cert, key)
    assert cert.exists() and key.exists()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))  # raises if invalid


def test_find_openssl_returns_path_or_none():
    result = tls.find_openssl()
    assert result is None or shutil.which(result) or result.endswith("openssl.exe")


def _ca_and_leaf(tmp_path, ip="192.168.1.10"):
    ca_cert = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    tls.generate_ca(ca_cert, ca_key)
    tls.generate_leaf(ip, ca_cert, ca_key, cert, key)
    return ca_cert, ca_key, cert, key


@needs_openssl
def test_leaf_loads_and_verifies_against_ca(tmp_path):
    ca_cert, _, cert, key = _ca_and_leaf(tmp_path)
    # Server can load the fullchain leaf + key.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))
    # The leaf verifies against the CA (this is what an iPhone with the CA installed does).
    result = subprocess.run(
        [tls.find_openssl(), "verify", "-CAfile", str(ca_cert), str(cert)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@needs_openssl
def test_ensure_server_cert_regenerates_only_on_ip_change(tmp_path):
    ca_cert = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    marker = tmp_path / "cert-ip.txt"
    tls.generate_ca(ca_cert, ca_key)

    tls.ensure_server_cert("192.168.1.10", ca_cert, ca_key, cert, key, marker)
    assert marker.read_text().strip() == "192.168.1.10"
    first = cert.read_bytes()

    # Same IP: no regeneration, bytes unchanged.
    tls.ensure_server_cert("192.168.1.10", ca_cert, ca_key, cert, key, marker)
    assert cert.read_bytes() == first

    # Changed IP: regenerated, marker updated.
    tls.ensure_server_cert("192.168.1.50", ca_cert, ca_key, cert, key, marker)
    assert marker.read_text().strip() == "192.168.1.50"
    assert cert.read_bytes() != first


def test_ensure_server_cert_raises_without_ca(tmp_path):
    with pytest.raises(RuntimeError):
        tls.ensure_server_cert(
            "192.168.1.10", tmp_path / "ca.pem", tmp_path / "ca-key.pem",
            tmp_path / "cert.pem", tmp_path / "key.pem", tmp_path / "ip.txt",
        )
