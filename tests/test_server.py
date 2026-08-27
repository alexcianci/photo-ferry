import builtins
import contextlib
import io
import json
import time
import urllib.parse


def _server_address(connect):
    """The (host, port) the fixture's `connect()` closes over.

    conftest builds the connection factory around a port it never yields, so the port is
    read back off an unconnected HTTPSConnection rather than threaded through the
    fixture's return value. Constructing one opens no socket.
    """
    conn = connect()
    return (conn.host, conn.port)


def _tls_connect_raw(connect):
    """A completed TLS handshake with no HTTP request written yet."""
    import socket as socket_mod
    import ssl as ssl_mod

    ctx = ssl_mod.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl_mod.CERT_NONE
    host, port = _server_address(connect)
    return ctx.wrap_socket(socket_mod.create_connection((host, port)),
                           server_hostname=None)


@contextlib.contextmanager
def _standalone_server(cert_pair, tmp_path, **overrides):
    """A server built for one test, so timeouts and chunk size can be dialled per case.

    Yields (session, connect, outbox, server) -- the same first three the running_server
    fixture yields, so the cookie helpers above apply unchanged, plus the server itself
    for tests that need to watch handle_error.
    """
    import http.client
    import ssl as ssl_mod
    import threading

    from photo_ferry.outbox import Outbox
    from photo_ferry.server import ReceiverServer
    from photo_ferry.session import Session

    cert, key = cert_pair
    session = Session.new(max_pin_attempts=3, idle_timeout_sec=600)
    outbox = Outbox()
    settings = dict(
        host="127.0.0.1", port=0, session=session, destination_dir=tmp_path / "inbox",
        cert_path=cert, key_path=key, max_file_bytes=64 * 1024 * 1024,
        max_session_bytes=256 * 1024 * 1024, chunk_bytes=64 * 1024, subnet_prefix=24,
        outbox=outbox,
    )
    settings.update(overrides)
    server = ReceiverServer(**settings)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def connect():
        ctx = ssl_mod.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl_mod.CERT_NONE
        return http.client.HTTPSConnection("127.0.0.1", port, context=ctx)

    try:
        yield session, connect, outbox, server
    finally:
        server.shutdown()
        server.server_close()


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


def test_outbox_fetch_touches_the_session_mid_stream(running_server, tmp_path,
                                                     monkeypatch):
    """Touching only before the first byte let the idle timer kill a long transfer.

    The UI polls session.is_idle() every 400 ms and calls stop() when it trips, so at
    the shipped 600 s timeout any file slow enough to outlast it died halfway. The
    fixture uses chunk_bytes=64, so this file spans many chunks and the timer must be
    refreshed inside the loop, not once at the top of it.
    """
    session, connect, outbox = running_server
    src = tmp_path / "big.jpg"
    src.write_bytes(b"X" * 4096)  # 64 chunks at the fixture's chunk_bytes
    entry = outbox.add([src])[0]
    cookie = _authed_cookie(session, connect)

    touches = []
    real_touch = session.touch
    monkeypatch.setattr(session, "touch", lambda: (touches.append(1), real_touch())[1])

    conn = connect()
    conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": cookie})
    body = conn.getresponse().read()
    assert body == b"X" * 4096
    # One touch before the headers, then one per chunk written. Anything approaching 1
    # means the refresh is back outside the loop.
    assert len(touches) > 10, f"expected a touch per chunk, saw {len(touches)}"


def test_outbox_file_header_block_survives_a_poisoned_ctype(running_server, tmp_path,
                                                            monkeypatch):
    """A content type carrying CR/LF must never reach the wire intact.

    Either the entry is refused at add time, or it is stored normalized and serves a
    clean single-line header. Both are acceptable; what is not is a split header block,
    which drops nosniff and the attachment disposition out of the headers and into the
    body -- exactly the two things a route serving user files cannot afford to lose.
    """
    session, connect, outbox = running_server
    import photo_ferry.outbox as outbox_mod
    cookie = _authed_cookie(session, connect)

    # Built from chr() rather than escapes so the literal CR/LF cannot be lost to
    # whatever edits this file next -- the bytes under test are the whole point.
    CR, LF = chr(13), chr(10)
    poisons = [
        "image/jpeg" + CR + LF,
        "image/jpeg" + CR + LF + "X-Evil: 1",
        "  IMAGE/JPEG  ",
        "image/" + CR + LF + "jpeg",
        "image/jpeg" + LF + "X-Evil: 1",
    ]
    served = 0
    for i, evil in enumerate(poisons):
        monkeypatch.setattr(outbox_mod, "guess_ctype", lambda name, v=evil: v)
        src = tmp_path / f"poison{i}.jpg"
        src.write_bytes(b"IMGDATA")
        added = outbox.add([src])
        if not added:
            continue  # refused at the door, the other acceptable outcome
        served += 1
        conn = connect()
        conn.request("GET", f"/outbox/{added[0].id}", headers={"Cookie": cookie})
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        assert body == b"IMGDATA"
        ctype = resp.getheader("Content-Type")
        assert ctype == "image/jpeg", f"{evil!r} reached the header as {ctype!r}"
        assert CR not in ctype and LF not in ctype
        assert resp.getheader("X-Content-Type-Options") == "nosniff"
        assert resp.getheader("Content-Disposition", "").startswith("attachment;")
        assert resp.getheader("X-Evil") is None
        assert b"X-Evil" not in body
    assert served >= 2, "the normalizing cases must actually be served, or this proves nothing"


def test_outbox_file_non_ascii_name_streams_with_valid_headers(running_server, tmp_path):
    """CJK and emoji names used to kill the response before a byte was ever flushed.

    send_header encodes latin-1 strictly and end_headers had not run, so the client saw
    a dropped connection rather than a status. The plain filename= parameter now carries
    an ASCII transliteration and the real name rides in RFC 6266 filename*.
    """
    session, connect, outbox = running_server
    src = tmp_path / "写真 📷 holiday.jpg"
    src.write_bytes(b"IMGDATA")
    entry = outbox.add([src])[0]
    assert entry.name == "写真 📷 holiday.jpg"
    cookie = _authed_cookie(session, connect)

    conn = connect()
    conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": cookie})
    resp = conn.getresponse()
    body = resp.read()
    assert resp.status == 200
    assert body == b"IMGDATA"
    assert resp.getheader("Content-Type") == "image/jpeg"
    assert resp.getheader("X-Content-Type-Options") == "nosniff"

    disposition = resp.getheader("Content-Disposition", "")
    assert disposition.startswith("attachment;")
    disposition.encode("latin-1")  # the whole point: this must not raise
    assert 'filename="' in disposition
    assert "filename*=UTF-8''" in disposition
    recovered = urllib.parse.unquote(disposition.split("filename*=UTF-8''")[1])
    assert recovered == entry.name


def test_outbox_manifest_keeps_the_real_non_ascii_name(running_server, tmp_path):
    """The header degrades to ASCII out of necessity; the manifest must not."""
    session, connect, outbox = running_server
    src = tmp_path / "写真 📷.jpg"
    src.write_bytes(b"IMGDATA")
    outbox.add([src])
    cookie = _authed_cookie(session, connect)
    conn = connect()
    conn.request("GET", "/outbox", headers={"Cookie": cookie})
    resp = conn.getresponse()
    assert resp.status == 200
    items = json.loads(resp.read())
    assert [i["name"] for i in items] == ["写真 📷.jpg"]


def test_stalled_handshake_does_not_block_other_clients(running_server):
    """One TCP connection that never sends a byte must not deny service.

    The handshake used to run in the accept loop, so an idle connection held the whole
    server: accept() itself blocked on a ClientHello that never came, no worker thread
    was ever spawned, and the subnet check -- which lives two layers above the handshake
    -- never got a chance to refuse it. This opens a raw socket, sends nothing at all,
    and requires a healthy client to still be served promptly.
    """
    import socket as socket_mod

    session, connect, _outbox = running_server
    cookie = _authed_cookie(session, connect)

    conn = connect()
    conn.request("GET", "/outbox", headers={"Cookie": cookie})
    assert conn.getresponse().status == 200  # healthy before the stall

    stalled = socket_mod.create_connection(_server_address(connect))
    try:
        healthy = connect()
        healthy.timeout = 5.0
        healthy.request("GET", "/outbox", headers={"Cookie": cookie})
        assert healthy.getresponse().status == 200
    finally:
        stalled.close()


def test_half_open_request_does_not_pin_a_worker_forever(running_server):
    """A completed handshake followed by a partial request line must time out.

    Without a read deadline each half-request parked a worker thread for the life of the
    process -- measured at 26 connections producing 28 live threads with no reclamation.

    Reclamation is observed through the sockets rather than through
    threading.active_count(): the deadline makes the server close the connection, so
    every client sees EOF. That is state this test owns, and it has no slack -- an
    active_count assertion needs a tolerance, and any tolerance still passes with one of
    the five workers pinned forever. A recv that times out is the failure, not a pass,
    so TimeoutError is caught above OSError rather than folded into it.
    """
    _session, connect, _outbox = running_server
    socks = [_tls_connect_raw(connect) for _ in range(5)]
    try:
        for s in socks:
            s.send(b"GET /outbox HTTP/1.0\r\n")  # deliberately never finished
            s.settimeout(15.0)
        started = time.monotonic()
        for i, s in enumerate(socks):
            try:
                answered = s.recv(64)
            except TimeoutError:
                raise AssertionError(
                    f"socket {i} was still open 15s in; its worker was never reclaimed"
                )
            except OSError:
                answered = b""  # a reset, which Windows prefers to a clean close
            assert answered == b"", (
                f"socket {i} was answered rather than closed: {answered!r}"
            )
        assert time.monotonic() - started < 12.0
    finally:
        for s in socks:
            s.close()


def test_tls_still_required_after_the_move(running_server):
    """The handshake moved threads; it must not have become optional.

    A plaintext request line at the TLS port must not earn an HTTP response: the bytes
    are not a ClientHello, the handshake fails, and finish_request returns without ever
    constructing a handler. Windows surfaces that as a reset about as often as a clean
    EOF, so both are accepted -- what is not accepted is anything that parses as a status
    line. The second half is what stops this passing against a dead server.
    """
    import socket as socket_mod

    session, connect, _outbox = running_server

    raw = socket_mod.create_connection(_server_address(connect))
    raw.settimeout(10.0)
    try:
        raw.sendall(b"GET /outbox HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        try:
            answered = raw.recv(64)
        except OSError:
            answered = b""
        assert not answered.startswith(b"HTTP/"), (
            f"a plaintext client got a real response: {answered!r}"
        )
    finally:
        raw.close()

    conn = connect()
    conn.timeout = 10.0
    conn.request("GET", f"/?t={session.token}")
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 200


def test_request_timeout_sec_actually_bounds_the_read(cert_pair, tmp_path):
    """A non-default request_timeout_sec must actually bound the request-header read.

    What establishes that deadline is finish_request's settimeout, not the handler's
    `timeout` property -- deleting the property leaves this passing at 1.01s, measured.
    1.0 s is chosen far from the 30 s default on purpose: if the deadline reverts, the
    recv below runs out its own 12 s ceiling and the elapsed assertion fails rather than
    the test passing slowly.

    The probe at the end is a separate, weaker claim: that the handler resolves its
    `timeout` from the server instead of hard-coding one. That property is a backstop
    rather than the mechanism -- but not dead code: setup() re-applies it, so removing
    finish_request's settimeout alone leaves the deadline intact. Removing both falls
    back to handshake_timeout_sec rather than to an unbounded read, and at shipped
    values that fallback is tighter than this deadline, so the property guards the
    configured value's authority rather than guarding against a hang. A `timeout = 300.0`
    class attribute in its place IS applied by setup(), after finish_request, and does
    override the configured value (measured: 12.01s instead of 1.00s).
    """
    import socket as socket_mod
    import ssl as ssl_mod
    import threading

    from photo_ferry.server import ReceiverServer, _Handler
    from photo_ferry.session import Session

    cert, key = cert_pair
    session = Session.new(max_pin_attempts=3, idle_timeout_sec=600)
    server = ReceiverServer(
        host="127.0.0.1", port=0, session=session, destination_dir=tmp_path / "inbox",
        cert_path=cert, key_path=key, max_file_bytes=1024, max_session_bytes=1_000_000,
        chunk_bytes=64, subnet_prefix=24,
        handshake_timeout_sec=5.0, request_timeout_sec=1.0,
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        port = server.server_address[1]
        ctx = ssl_mod.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl_mod.CERT_NONE
        sock = ctx.wrap_socket(socket_mod.create_connection(("127.0.0.1", port)),
                               server_hostname=None)
        try:
            sock.send(b"GET /outbox HTTP/1.0\r\n")  # deliberately never finished
            sock.settimeout(12.0)
            started = time.monotonic()
            try:
                answered = sock.recv(64)
            except OSError:
                answered = b""  # a reset, which Windows prefers to a clean close
            elapsed = time.monotonic() - started
        finally:
            sock.close()
        assert answered == b"", f"a half request was answered: {answered!r}"
        assert elapsed < 6.0, (
            f"the read was still open {elapsed:.1f}s in; request_timeout_sec=1.0 was "
            "ignored and the deadline fell back to the class default"
        )

        # The weaker claim: the handler reads its deadline off the server rather than
        # carrying a competing copy, so a class attribute added later cannot disagree
        # with the configured value. BaseRequestHandler.__init__ assigns self.server
        # before calling setup(), so this is the same lookup setup() performs.
        probe = _Handler.__new__(_Handler)
        probe.server = server
        assert probe.timeout == 1.0
    finally:
        server.shutdown()
        server.server_close()


def _put_upload_headers(conn, cookie, name, length):
    """Open an upload request and stop, so the body can be fed in around a pause."""
    conn.putrequest("POST", "/upload")
    conn.putheader("Cookie", cookie)
    conn.putheader("X-Filename", name)
    conn.putheader("Content-Type", "image/jpeg")
    conn.putheader("Content-Length", str(length))
    conn.endheaders()


def test_upload_survives_a_pause_longer_than_the_header_deadline(cert_pair, tmp_path):
    """A phone that locks its screen mid-upload must not lose the upload.

    request_timeout_sec is 1.0 s here and the pause is 3.0 s, so this fails outright if
    the tight header deadline is still governing the body read. Bounding the whole
    connection with it was measured answering 507 to a 35 s pause at the shipped 30 s,
    with nothing landing in the destination.
    """
    with _standalone_server(cert_pair, tmp_path, request_timeout_sec=1.0,
                            transfer_timeout_sec=20.0) as (session, connect, _ob, _srv):
        cookie = _authed_cookie(session, connect)
        body = b"IMGDATA" * 64
        conn = connect()
        conn.timeout = 30.0
        _put_upload_headers(conn, cookie, "slow.jpg", len(body))
        conn.send(body[:100])
        time.sleep(3.0)  # the screen locks
        conn.send(body[100:])
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        assert status == 200, f"a 3s pause lost the upload: {status}"
        assert sorted(p.name for p in (tmp_path / "inbox").iterdir()) == ["slow.jpg"]


def test_upload_stalled_past_the_transfer_deadline_is_408_not_507(cert_pair, tmp_path):
    """A stalled phone must never be told its disk failed.

    TimeoutError subclasses OSError, so without an earlier clause it falls into
    _handle_upload's disk-failure branch and the user is diagnosed with storage trouble
    they do not have. save_stream's own `finally` unlinks the .part file regardless, so
    the destination is asserted empty here to show the wrong status was the only defect.
    """
    with _standalone_server(cert_pair, tmp_path, request_timeout_sec=1.0,
                            transfer_timeout_sec=1.0) as (session, connect, _ob, _srv):
        cookie = _authed_cookie(session, connect)
        conn = connect()
        conn.timeout = 30.0
        _put_upload_headers(conn, cookie, "abandoned.jpg", 448)
        conn.send(b"IMGDATA" * 10)  # and then never the remaining bytes
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        assert status == 408, f"a stalled phone was told its disk failed: {status}"
        assert list((tmp_path / "inbox").iterdir()) == [], "a partial file was left behind"


def test_download_survives_a_pause_longer_than_the_header_deadline(cert_pair, tmp_path):
    """The commit before this one added a per-chunk touch() so a long download would
    outlive the 600 s idle timeout; a 30 s socket deadline on the same loop is 20x
    tighter and truncates instead of stopping cleanly.

    The payload is far larger than any send buffer, so the server genuinely is blocked
    in wfile.write during the pause rather than having handed everything to the kernel.
    """
    with _standalone_server(cert_pair, tmp_path, request_timeout_sec=1.0,
                            transfer_timeout_sec=20.0,
                            chunk_bytes=256 * 1024) as (session, connect, outbox, _srv):
        payload = b"X" * (8 * 1024 * 1024)
        src = tmp_path / "big.jpg"
        src.write_bytes(payload)
        entry = outbox.add([src])[0]
        cookie = _authed_cookie(session, connect)

        conn = connect()
        conn.timeout = 60.0
        conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": cookie})
        resp = conn.getresponse()
        head = resp.read(4096)
        time.sleep(3.0)  # the phone switches apps
        rest = resp.read()
        assert len(head) + len(rest) == len(payload)


def test_download_stalled_past_the_transfer_deadline_is_a_quiet_disconnect(cert_pair,
                                                                           tmp_path):
    """A download deadline is newly reachable from wfile.write, and must stay quiet.

    handle_one_request catches TimeoutError around method(), sets close_connection and
    returns, so a phone that goes away for good is an ordinary disconnect. If it ever
    escaped instead, socketserver.handle_error would print a traceback carrying absolute
    paths -- the same thing finish_request goes out of its way to avoid for a failed
    handshake.
    """
    import http.client

    with _standalone_server(cert_pair, tmp_path, request_timeout_sec=1.0,
                            transfer_timeout_sec=1.0,
                            chunk_bytes=256 * 1024) as (session, connect, outbox, server):
        errors = []
        server.handle_error = lambda *a: errors.append(a)
        payload = b"X" * (8 * 1024 * 1024)
        src = tmp_path / "big.jpg"
        src.write_bytes(payload)
        entry = outbox.add([src])[0]
        cookie = _authed_cookie(session, connect)

        conn = connect()
        conn.timeout = 60.0
        conn.request("GET", f"/outbox/{entry.id}", headers={"Cookie": cookie})
        resp = conn.getresponse()
        try:
            head = resp.read(4096)
        except (OSError, http.client.HTTPException):
            head = b""
        time.sleep(3.0)  # nothing is read; the server's write hits the 1.0s deadline
        assert errors == [], f"a stalled download reached handle_error: {errors}"
        try:
            rest = resp.read()
        except (OSError, http.client.HTTPException):
            rest = b""
        assert len(head) + len(rest) < len(payload), "the transfer deadline never fired"


def test_page_offers_both_directions(running_server):
    session, connect, _outbox = running_server
    conn = connect()
    conn.request("GET", f"/?t={session.token}")
    resp = conn.getresponse()
    assert resp.status == 200
    body = resp.read()
    assert b"Send to PC" in body
    assert b"Get from PC" in body
