import shutil
import ssl

import pytest

from iphone_photo_drop import tls


@pytest.mark.skipif(tls.find_openssl() is None, reason="openssl not available")
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
