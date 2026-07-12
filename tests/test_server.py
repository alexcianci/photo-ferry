import json


def _get_token_cookie(session, conn):
    conn.request("GET", f"/?t={session.token}")
    resp = conn.getresponse()
    body = resp.read()
    assert resp.status == 200
    assert b"Enter the 6-digit PIN" in body
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
    last = None
    for _ in range(3):
        conn = connect()
        conn.request("POST", "/auth", body=json.dumps({"pin": "000000"}),
                     headers={"Cookie": cookie, "Content-Type": "application/json"})
        last = conn.getresponse().status
    assert session.locked_out is True
    assert last in (401, 423)


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
