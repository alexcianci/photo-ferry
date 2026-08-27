"""Shared pytest fixtures for iPhone Photo Drop."""
import http.client
import ssl
import threading

import pytest

from photo_ferry import tls
from photo_ferry.outbox import Outbox
from photo_ferry.server import ReceiverServer
from photo_ferry.session import Session


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
    outbox = Outbox()
    server = ReceiverServer(
        host="127.0.0.1", port=0, session=session, destination_dir=dest,
        cert_path=cert, key_path=key, max_file_bytes=1024, max_session_bytes=1_000_000,
        chunk_bytes=64, subnet_prefix=24, outbox=outbox,
        # Far below the shipped defaults so a test that waits for a stalled connection
        # to be reclaimed can do so in seconds rather than half a minute. Every request
        # in the suite is local and sub-millisecond, so this bounds only the deliberate
        # stalls.
        handshake_timeout_sec=2.0, request_timeout_sec=2.0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def connect():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return http.client.HTTPSConnection("127.0.0.1", port, context=ctx)

    yield session, connect, outbox
    server.shutdown()
    server.server_close()
