import json


def _get_token_cookie(session, conn):
    conn.request("GET", f"/?t={session.token}")
    resp = conn.getresponse()
    body = resp.read()
    assert resp.status == 200
    assert b"Unlock your PC" in body
    setc = resp.getheader("Set-Cookie")
    assert setc and "t=" in setc
    return setc.split(";")[0]  # "t=<token>"


def test_get_root_requires_valid_token(running_server):
    session, connect = running_server
    conn = connect()
    conn.request("GET", "/?t=wrong")
    assert conn.getresponse().status == 403


def test_auth_then_upload_saves_file(running_server, tmp_path):
    session, connect = running_server
    conn = connect()
    cookie = _get_token_cookie(session, conn)

    conn.request("POST", "/auth", body=json.dumps({"pin": session.pin}),
                 headers={"Cookie": cookie, "Content-Type": "application/json"})
    assert conn.getresponse().status == 200

    conn.request("POST", "/upload", body=b"IMGDATA",
                 headers={"Cookie": cookie, "X-Filename": "beach.jpg",
                          "Content-Type": "image/jpeg", "Content-Length": "7"})
    assert conn.getresponse().status == 200
    assert [r.name for r in session.received] == ["beach.jpg"]


def test_wrong_pin_locks_out_and_shuts_down(running_server):
    session, connect = running_server
    conn = connect()
    cookie = _get_token_cookie(session, conn)
    statuses = []
    for _ in range(3):  # fixture max_pin_attempts == 3
        conn = connect()
        conn.request("POST", "/auth", body=json.dumps({"pin": "000000"}),
                     headers={"Cookie": cookie, "Content-Type": "application/json"})
        statuses.append(conn.getresponse().status)
    assert session.locked_out is True
    assert statuses == [401, 401, 423]


def test_upload_requires_auth(running_server):
    session, connect = running_server
    conn = connect()
    cookie = _get_token_cookie(session, conn)
    conn.request("POST", "/upload", body=b"x",
                 headers={"Cookie": cookie, "X-Filename": "a.jpg",
                          "Content-Type": "image/jpeg", "Content-Length": "1"})
    assert conn.getresponse().status == 401


def test_upload_rejects_disallowed_type(running_server):
    session, connect = running_server
    conn = connect()
    cookie = _get_token_cookie(session, conn)
    conn.request("POST", "/auth", body=json.dumps({"pin": session.pin}),
                 headers={"Cookie": cookie, "Content-Type": "application/json"})
    conn.getresponse().read()
    conn.request("POST", "/upload", body=b"x",
                 headers={"Cookie": cookie, "X-Filename": "evil.exe",
                          "Content-Type": "application/octet-stream", "Content-Length": "1"})
    assert conn.getresponse().status == 400


def test_upload_rejects_oversize_file(running_server):
    session, connect = running_server
    conn = connect()
    cookie = _get_token_cookie(session, conn)
    conn.request("POST", "/auth", body=json.dumps({"pin": session.pin}),
                 headers={"Cookie": cookie, "Content-Type": "application/json"})
    conn.getresponse().read()
    big = b"x" * 5000  # fixture max_file_bytes is 1024
    conn = connect()
    conn.request("POST", "/upload", body=big,
                 headers={"Cookie": cookie, "X-Filename": "big.jpg",
                          "Content-Type": "image/jpeg", "Content-Length": str(len(big))})
    assert conn.getresponse().status == 400


def test_upload_bad_content_length_is_rejected(running_server):
    session, connect = running_server
    conn = connect()
    cookie = _get_token_cookie(session, conn)
    conn.request("POST", "/auth", body=json.dumps({"pin": session.pin}),
                 headers={"Cookie": cookie, "Content-Type": "application/json"})
    conn.getresponse().read()
    conn = connect()
    conn.putrequest("POST", "/upload")
    conn.putheader("Cookie", cookie)
    conn.putheader("X-Filename", "a.jpg")
    conn.putheader("Content-Type", "image/jpeg")
    conn.putheader("Content-Length", "notanumber")
    conn.endheaders()
    assert conn.getresponse().status == 400


def test_off_subnet_client_is_forbidden(running_server, monkeypatch):
    session, connect = running_server
    import iphone_photo_drop.server as server_mod
    monkeypatch.setattr(server_mod.net, "client_in_subnet", lambda *a, **k: False)
    conn = connect()
    conn.request("GET", f"/?t={session.token}")
    assert conn.getresponse().status == 403


def test_lockout_triggers_on_shutdown_callback(cert_pair, tmp_path):
    import http.client
    import ssl
    import threading

    from iphone_photo_drop.server import ReceiverServer
    from iphone_photo_drop.session import Session

    cert, key = cert_pair
    fired = threading.Event()
    session = Session("tok-abcdefghij-0123456789", "123456", max_pin_attempts=1)
    server = ReceiverServer(
        host="127.0.0.1", port=0, session=session, destination_dir=tmp_path / "inbox",
        cert_path=cert, key_path=key, max_file_bytes=1024, max_session_bytes=1_000_000,
        chunk_bytes=64, subnet_prefix=24, on_shutdown=fired.set,
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        port = server.server_address[1]
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx)
        conn.request("POST", "/auth", body=json.dumps({"pin": "000000"}),
                     headers={"Cookie": "t=tok-abcdefghij-0123456789",
                              "Content-Type": "application/json"})
        assert conn.getresponse().status == 423
        assert fired.wait(timeout=2.0) is True
    finally:
        server.shutdown()
        server.server_close()


def test_ca_endpoint_404_without_ca(running_server):
    session, connect = running_server
    conn = connect()
    conn.request("GET", "/ca.crt")
    assert conn.getresponse().status == 404


def test_leaf_trusted_by_client_with_ca_and_serves_ca(cert_pair, tmp_path):
    # cert_pair param gives us the skip-if-no-openssl behavior; we build our own CA.
    import http.client
    import ssl
    import threading

    from iphone_photo_drop import tls
    from iphone_photo_drop.server import ReceiverServer
    from iphone_photo_drop.session import Session

    ca_cert = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    tls.generate_ca(ca_cert, ca_key)
    tls.generate_leaf("127.0.0.1", ca_cert, ca_key, cert, key)

    session = Session.new(max_pin_attempts=3, idle_timeout_sec=600)
    server = ReceiverServer(
        host="127.0.0.1", port=0, session=session, destination_dir=tmp_path / "inbox",
        cert_path=cert, key_path=key, max_file_bytes=1024, max_session_bytes=1_000_000,
        chunk_bytes=64, subnet_prefix=24, ca_cert_path=ca_cert,
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        port = server.server_address[1]
        # A client that TRUSTS the CA verifies the leaf (chain + IP SAN) with no warning,
        # exactly like Safari once the CA profile is installed on the phone.
        ctx = ssl.create_default_context(cafile=str(ca_cert))
        conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx)
        conn.request("GET", "/ca.crt")
        resp = conn.getresponse()
        assert resp.status == 200
        assert b"BEGIN CERTIFICATE" in resp.read()
    finally:
        server.shutdown()
        server.server_close()
