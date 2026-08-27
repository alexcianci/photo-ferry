import builtins
import io
import json


def _get_token_cookie(session, conn):
    conn.request("GET", f"/?t={session.token}")
    resp = conn.getresponse()
    body = resp.read()
    assert resp.status == 200
    assert b"Pair with your PC" in body
    setc = resp.getheader("Set-Cookie")
    assert setc and "t=" in setc
    return setc.split(";")[0]  # "t=<token>"


def test_get_root_requires_valid_token(running_server):
    session, connect, _outbox = running_server
    conn = connect()
    conn.request("GET", "/?t=wrong")
    assert conn.getresponse().status == 403


def test_auth_then_upload_saves_file(running_server, tmp_path):
    session, connect, _outbox = running_server
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
    session, connect, _outbox = running_server
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
    session, connect, _outbox = running_server
    conn = connect()
    cookie = _get_token_cookie(session, conn)
    conn.request("POST", "/upload", body=b"x",
                 headers={"Cookie": cookie, "X-Filename": "a.jpg",
                          "Content-Type": "image/jpeg", "Content-Length": "1"})
    assert conn.getresponse().status == 401


def test_upload_rejects_disallowed_type(running_server):
    session, connect, _outbox = running_server
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
    session, connect, _outbox = running_server
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
    session, connect, _outbox = running_server
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
    session, connect, _outbox = running_server
    import photo_ferry.server as server_mod
    monkeypatch.setattr(server_mod.net, "client_in_subnet", lambda *a, **k: False)
    conn = connect()
    conn.request("GET", f"/?t={session.token}")
    assert conn.getresponse().status == 403


def test_lockout_triggers_on_shutdown_callback(cert_pair, tmp_path):
    import http.client
    import ssl
    import threading

    from photo_ferry.server import ReceiverServer
    from photo_ferry.session import Session

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
    session, connect, _outbox = running_server
    conn = connect()
    conn.request("GET", "/ca.crt")
    assert conn.getresponse().status == 404


def test_leaf_trusted_by_client_with_ca_and_serves_ca(cert_pair, tmp_path):
    # cert_pair param gives us the skip-if-no-openssl behavior; we build our own CA.
    import http.client
    import ssl
    import threading

    from photo_ferry import tls
    from photo_ferry.server import ReceiverServer
    from photo_ferry.session import Session

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


def test_server_version_header_carries_the_product_name(running_server):
    session, connect, _outbox = running_server
    conn = connect()
    conn.request("GET", f"/?t={session.token}")
    resp = conn.getresponse()
    resp.read()
    assert resp.getheader("Server", "").startswith("PhotoFerry/")


def _authed_cookie(session, connect):
    conn = connect()
    cookie = _get_token_cookie(session, conn)
    conn.request("POST", "/auth", body=json.dumps({"pin": session.pin}),
                 headers={"Cookie": cookie, "Content-Type": "application/json"})
    conn.getresponse().read()
    return cookie


def test_outbox_manifest_lists_offered_files(running_server, tmp_path):
    session, connect, outbox = running_server
    src = tmp_path / "holiday.jpg"
    src.write_bytes(b"IMGDATA")
    outbox.add([src])
    cookie = _authed_cookie(session, connect)

    conn = connect()
    conn.request("GET", "/outbox", headers={"Cookie": cookie})
    resp = conn.getresponse()
    assert resp.status == 200
    items = json.loads(resp.read())
    assert [i["name"] for i in items] == ["holiday.jpg"]
    assert items[0]["size"] == 7
    assert "path" not in items[0]


def test_outbox_manifest_requires_token(running_server):
    session, connect, _outbox = running_server
    conn = connect()
    conn.request("GET", "/outbox")
    assert conn.getresponse().status == 403


def test_outbox_manifest_requires_auth(running_server):
    session, connect, _outbox = running_server
    conn = connect()
    cookie = _get_token_cookie(session, conn)
    conn.request("GET", "/outbox", headers={"Cookie": cookie})
    assert conn.getresponse().status == 401


def test_outbox_manifest_wrong_token_is_forbidden(running_server):
    """A wrong cookie, not merely an absent one. The session is fully authed here, so
    this isolates the token check from the auth check."""
    session, connect, _outbox = running_server
    _authed_cookie(session, connect)
    conn = connect()
    conn.request("GET", "/outbox", headers={"Cookie": "t=not-the-token"})
    assert conn.getresponse().status == 403


def test_outbox_manifest_off_subnet_is_forbidden(running_server, monkeypatch):
    """Pair first, while still on-subnet, so this proves even a fully paired client is
    refused once it appears off-subnet."""
    session, connect, _outbox = running_server
    cookie = _authed_cookie(session, connect)
    import photo_ferry.server as server_mod
    monkeypatch.setattr(server_mod.net, "client_in_subnet", lambda *a, **k: False)
    conn = connect()
    conn.request("GET", "/outbox", headers={"Cookie": cookie})
    assert conn.getresponse().status == 403


def test_outbox_file_streams_bytes(running_server, tmp_path):
    session, connect, outbox = running_server
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"VIDEOBYTES")
    entry = outbox.add([src])[0]
    cookie = _authed_cookie(session, connect)

    conn = connect()
    conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": cookie})
    resp = conn.getresponse()
    body = resp.read()
    assert resp.status == 200
    assert body == b"VIDEOBYTES"
    assert resp.getheader("Content-Type") == "video/mp4"
    assert 'filename="clip.mp4"' in resp.getheader("Content-Disposition", "")


def test_outbox_file_unknown_id_is_404(running_server):
    session, connect, _outbox = running_server
    cookie = _authed_cookie(session, connect)
    conn = connect()
    conn.request("GET", "/outbox/doesnotexist", headers={"Cookie": cookie})
    assert conn.getresponse().status == 404


def test_outbox_file_traversal_id_reads_nothing(running_server, tmp_path, monkeypatch):
    """A traversal-shaped id must be a dictionary miss, never a filesystem read.

    The spy sits on io.open rather than Path.open so the assertion still holds if a
    future change rebuilds a path from the URL and opens it some other way. builtins.open
    is patched too: it is the same function object as io.open but a separate name, so
    rebinding one does not rebind the other.
    """
    session, connect, _outbox = running_server
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"TOPSECRET")

    cookie = _authed_cookie(session, connect)  # before the spy, so pairing is not counted

    opened = []
    real_open = io.open

    def spy(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", spy)
    monkeypatch.setattr(builtins, "open", spy)

    for bad in ["../../etc/passwd", "..%2f..%2fsecret.txt", f"..\\{secret.name}"]:
        conn = connect()
        conn.request("GET", f"/outbox/{bad}", headers={"Cookie": cookie})
        assert conn.getresponse().status == 404
    assert opened == []


def test_outbox_file_wrong_token_is_forbidden(running_server, tmp_path):
    session, connect, outbox = running_server
    src = tmp_path / "a.jpg"
    src.write_bytes(b"X")
    entry = outbox.add([src])[0]
    _authed_cookie(session, connect)
    conn = connect()
    conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": "t=not-the-token"})
    assert conn.getresponse().status == 403


def test_outbox_file_off_subnet_is_forbidden(running_server, tmp_path, monkeypatch):
    session, connect, outbox = running_server
    src = tmp_path / "a.jpg"
    src.write_bytes(b"X")
    entry = outbox.add([src])[0]
    cookie = _authed_cookie(session, connect)
    import photo_ferry.server as server_mod
    monkeypatch.setattr(server_mod.net, "client_in_subnet", lambda *a, **k: False)
    conn = connect()
    conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": cookie})
    assert conn.getresponse().status == 403


def test_outbox_file_requires_auth(running_server, tmp_path):
    session, connect, outbox = running_server
    src = tmp_path / "a.jpg"
    src.write_bytes(b"X")
    entry = outbox.add([src])[0]
    conn = connect()
    cookie = _get_token_cookie(session, conn)
    conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": cookie})
    assert conn.getresponse().status == 401


def test_outbox_file_vanished_between_pick_and_fetch_is_404(running_server, tmp_path):
    session, connect, outbox = running_server
    src = tmp_path / "gone.jpg"
    src.write_bytes(b"X")
    entry = outbox.add([src])[0]
    src.unlink()
    cookie = _authed_cookie(session, connect)
    conn = connect()
    conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": cookie})
    assert conn.getresponse().status == 404


def test_outbox_fetch_touches_the_session(running_server, tmp_path):
    session, connect, outbox = running_server
    src = tmp_path / "a.jpg"
    src.write_bytes(b"X")
    entry = outbox.add([src])[0]
    cookie = _authed_cookie(session, connect)
    session._last_activity -= 10_000  # simulate a long-idle session
    conn = connect()
    conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": cookie})
    conn.getresponse().read()
    assert session.is_idle() is False
