"""Shared pytest fixtures for iPhone Photo Drop."""
import http.client
import ssl
import threading

import pytest

from iphone_photo_drop import tls
from iphone_photo_drop.server import ReceiverServer
from iphone_photo_drop.session import Session


@pytest.fixture
def cert_pair(tmp_path):
    if tls.find_openssl() is None:
        pytest.skip("openssl not available")
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    tls.generate_self_signed("127.0.0.1", cert, key)
    return cert, key


@pytest.fixture
def running_server(tmp_path, cert_pair):
    cert, key = cert_pair
    session = Session.new(max_pin_attempts=3, idle_timeout_sec=600)
    dest = tmp_path / "inbox"
    server = ReceiverServer(
        host="127.0.0.1", port=0, session=session, destination_dir=dest,
        cert_path=cert, key_path=key, max_file_bytes=1024, max_session_bytes=1_000_000,
        chunk_bytes=64, subnet_prefix=24,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def connect():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return http.client.HTTPSConnection("127.0.0.1", port, context=ctx)

    yield session, connect
    server.shutdown()
    server.server_close()
