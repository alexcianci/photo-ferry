"""On-demand HTTPS receiver. Serves the upload page and handles auth + uploads."""
from __future__ import annotations

import json
import ssl
import urllib.parse
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Callable

from . import net, security, storage
from .session import Session

_UPLOAD_HTML = resources.files("iphone_photo_drop").joinpath("static/upload.html").read_bytes()


class ReceiverServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        *,
        host: str,
        port: int,
        session: Session,
        destination_dir: Path,
        cert_path: Path,
        key_path: Path,
        max_file_bytes: int,
        max_session_bytes: int,
        chunk_bytes: int,
        subnet_prefix: int,
        on_shutdown: Callable[[], None] | None = None,
    ) -> None:
        super().__init__((host, port), _Handler)
        self.session = session
        self.destination_dir = destination_dir
        self.max_file_bytes = max_file_bytes
        self.max_session_bytes = max_session_bytes
        self.chunk_bytes = chunk_bytes
        self.subnet_prefix = subnet_prefix
        self.server_ip = host
        self.on_shutdown = on_shutdown

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        self.socket = ctx.wrap_socket(self.socket, server_side=True)

    def trigger_shutdown(self) -> None:
        """Invoke the optional shutdown callback. The callback MUST be idempotent
        and MUST NOT call `self.shutdown()` from a request-handler thread (that
        deadlocks ThreadingHTTPServer); the UI thread owns actual shutdown."""
        if self.on_shutdown:
            self.on_shutdown()


class _Handler(BaseHTTPRequestHandler):
    server_version = "iPhonePhotoDrop/0.1"

    @property
    def app(self) -> ReceiverServer:
        return self.server  # type: ignore[return-value]

    def _client_allowed(self) -> bool:
        return net.client_in_subnet(
            self.client_address[0], self.app.server_ip, self.app.subnet_prefix
        )

    def _cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie(raw)
        morsel = jar.get("t")
        return morsel.value if morsel else None

    def _valid_token_cookie(self) -> bool:
        return security.verify_token(self.app.session.token, self._cookie_token())

    def _send(self, status, body=b"", ctype="text/plain", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _reject_upload(self, status, body=b""):
        # Avoid draining a possibly huge request body into memory; close instead.
        self.close_connection = True
        self._send(status, body)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if not self._client_allowed():
            self._send(HTTPStatus.FORBIDDEN, b"off-subnet")
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/":
            self._send(HTTPStatus.NOT_FOUND, b"not found")
            return
        qs = urllib.parse.parse_qs(parsed.query)
        token = (qs.get("t") or [None])[0]
        if not security.verify_token(self.app.session.token, token):
            self._send(HTTPStatus.FORBIDDEN, b"invalid token")
            return
        cookie = (f"t={self.app.session.token}; HttpOnly; Secure; "
                  f"SameSite=Strict; Path=/")
        self.app.session.touch()
        self._send(HTTPStatus.OK, _UPLOAD_HTML, "text/html; charset=utf-8",
                   {"Set-Cookie": cookie})

    def do_POST(self):
        if not self._client_allowed():
            self._send(HTTPStatus.FORBIDDEN, b"off-subnet")
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/auth":
            self._handle_auth()
        elif parsed.path == "/upload":
            self._handle_upload()
        else:
            self._send(HTTPStatus.NOT_FOUND, b"not found")

    def _content_length(self) -> int:
        raw = self.headers.get("Content-Length", "0")
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return 0
        return n if n >= 0 else 0

    def _read_body(self):
        length = self._content_length()
        return self.rfile.read(length) if length else b""

    def _handle_auth(self):
        session = self.app.session
        if not self._valid_token_cookie():
            self._send(HTTPStatus.FORBIDDEN, b"no token")
            return
        try:
            data = json.loads(self._read_body() or b"{}")
            pin = str(data.get("pin", ""))
        except (ValueError, TypeError):
            pin = ""
        result = session.check_pin(pin)
        if result == "ok":
            self._send(HTTPStatus.OK, b"ok")
        elif result == "locked":
            self._send(HTTPStatus.LOCKED, b"locked out")
            self.app.trigger_shutdown()
        else:  # "wrong"
            self._send(HTTPStatus.UNAUTHORIZED, b"wrong pin")

    def _handle_upload(self):
        session = self.app.session
        # Design note: `session.authed` is a single sticky flag for the one active
        # session (single-phone model). The token is LAN-only, HTTPS, idle-timed, and
        # shown only briefly, so binding auth to the connection is intentionally omitted.
        if not self._valid_token_cookie() or not session.authed:
            self._reject_upload(HTTPStatus.UNAUTHORIZED, b"not authed")
            return
        raw_name = urllib.parse.unquote(self.headers.get("X-Filename", ""))
        ctype = self.headers.get("Content-Type", "")
        if not security.is_allowed_media(raw_name, ctype):
            self._reject_upload(HTTPStatus.BAD_REQUEST, b"disallowed file type")
            return
        length = self._content_length()
        if length <= 0:
            self._reject_upload(HTTPStatus.BAD_REQUEST, b"empty or invalid length")
            return
        if session.total_bytes + length > self.app.max_session_bytes:
            self._reject_upload(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"session limit reached")
            return
        try:
            saved = storage.save_stream(
                self.rfile, length, self.app.destination_dir, raw_name,
                max_file_bytes=self.app.max_file_bytes, chunk_bytes=self.app.chunk_bytes,
            )
        except ValueError:
            self._reject_upload(HTTPStatus.BAD_REQUEST, b"rejected")
            return
        except OSError:
            self._reject_upload(HTTPStatus.INSUFFICIENT_STORAGE, b"write failed")
            return
        try:
            size = saved.stat().st_size
        except OSError:
            size = length
        session.record_received(saved.name, size)
        self._send(HTTPStatus.OK, json.dumps({"saved": saved.name}).encode(),
                   "application/json")
