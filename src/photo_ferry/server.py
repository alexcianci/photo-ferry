"""On-demand HTTPS receiver. Serves the upload page and handles auth + uploads."""
from __future__ import annotations

import json
import socket
import ssl
import urllib.parse
from contextlib import contextmanager
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Callable

from . import net, security, storage
from .outbox import Outbox
from .session import Session

_UPLOAD_HTML = resources.files("photo_ferry").joinpath("static/upload.html").read_bytes()


def _content_disposition(name: str) -> str:
    """An `attachment` disposition that survives header encoding for any filename.

    `send_header` encodes latin-1 strictly, so a CJK or emoji name raised
    UnicodeEncodeError partway through the header block. Because `end_headers` had not
    run yet, nothing was ever flushed and the client saw a dropped connection rather
    than a status it could act on -- a worse failure than a 500. `sanitize_filename`
    permits non-ASCII, so an ordinary photo off a phone reached this.

    The plain `filename=` parameter therefore carries an ASCII-only transliteration,
    and the real name travels in RFC 6266's `filename*`, which is percent-encoded and
    so ASCII by construction. Quotes and backslashes are replaced rather than trusted
    to `sanitize_filename`: that validator exists for filesystem safety, and header
    correctness must not depend on a decision made elsewhere for a different reason.
    The manifest still reports the real name, unchanged.
    """
    ascii_name = "".join(
        ch if ch.isascii() and ch.isprintable() and ch not in '"\\' else "_"
        for ch in name
    )
    quoted = urllib.parse.quote(name, safe="")
    return f"attachment; filename=\"{ascii_name or 'download'}\"; filename*=UTF-8''{quoted}"


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
        handshake_timeout_sec: float = 10.0,
        request_timeout_sec: float = 30.0,
        transfer_timeout_sec: float = 300.0,
        ca_cert_path: Path | None = None,
        outbox: Outbox | None = None,
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
        self.ca_cert_path = ca_cert_path
        self.outbox = outbox if outbox is not None else Outbox()
        self.on_shutdown = on_shutdown

        # Deliberately NOT `self.socket = ctx.wrap_socket(...)`. Wrapping the LISTENING
        # socket makes accept() perform the TLS handshake inline in the serve_forever
        # thread, so a single connection that never sends a byte denies service to
        # everyone, with no timeout and before the subnet check can refuse it. The
        # handshake belongs in the worker thread, which is finish_request.
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ssl_context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        self.handshake_timeout_sec = handshake_timeout_sec
        self.request_timeout_sec = request_timeout_sec
        # Two deadlines, because there are two threat models. request_timeout_sec is
        # tight because it guards the request line and headers, which an UNAUTHENTICATED
        # peer can reach: complete a handshake, send half a request line, park a worker
        # for free. transfer_timeout_sec is loose because by the time either transfer
        # loop runs the peer has passed the subnet check, the token cookie AND the PIN,
        # and the thing most likely to pause it is the phone locking its screen,
        # switching apps, or roaming between access points. 300 s absorbs all of those
        # (a 35 s pause was measured killing a 537 MB upload at the old 30 s ceiling)
        # while staying under the 600 s session idle timeout, so an abandoned transfer
        # is still ended by the session policy the UI shows the user rather than
        # silently by a socket.
        self.transfer_timeout_sec = transfer_timeout_sec

    def get_request(self):
        """Accept only. The socket is still plaintext here, and gets a deadline so a
        client that stalls mid-handshake cannot hold a worker forever.

        The deadline survives the wrap: SSLSocket._create copies the plaintext socket's
        timeout onto itself, so this genuinely bounds the handshake rather than only the
        accept that precedes it.
        """
        sock, addr = self.socket.accept()
        sock.settimeout(self.handshake_timeout_sec)
        return sock, addr

    def finish_request(self, request, client_address):
        """Runs on the worker thread, so this is where the handshake belongs.

        A failed handshake is an ordinary event on a LAN with a self-signed CA -- a
        probe, a cancelled profile install, a client that hangs up. It must not reach
        socketserver.handle_error, which is not silenced and prints a traceback with
        absolute paths.

        `request` is detached by the wrap and its fd now belongs to the SSLSocket, so
        the shutdown_request that ThreadingMixIn runs afterwards on the original is a
        no-op. That is why the TLS socket is torn down here instead: nothing above this
        frame can still see it.
        """
        try:
            tls_sock = self.ssl_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return
        tls_sock.settimeout(self.request_timeout_sec)
        try:
            self.RequestHandlerClass(tls_sock, client_address, self)
        finally:
            try:
                tls_sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            tls_sock.close()

    def trigger_shutdown(self) -> None:
        """Invoke the optional shutdown callback. The callback MUST be idempotent
        and MUST NOT call `self.shutdown()` from a request-handler thread (that
        deadlocks ThreadingHTTPServer); the UI thread owns actual shutdown."""
        if self.on_shutdown:
            self.on_shutdown()


class _Handler(BaseHTTPRequestHandler):
    server_version = "PhotoFerry/0.2"

    @property
    def app(self) -> ReceiverServer:
        return self.server  # type: ignore[return-value]

    @property
    def timeout(self) -> float:
        """A second path to the same deadline, not the one that establishes it.

        finish_request has already put request_timeout_sec on the socket by the time
        this class is instantiated, so deleting this property changes nothing while that
        line stands -- measured, 1.01s either way. It earns its place twice over anyway.
        StreamRequestHandler.setup() re-applies it, so it restores the deadline if
        finish_request's settimeout is ever dropped. Removing both does not leave the
        read unbounded -- it falls back to handshake_timeout_sec, which get_request put
        on the socket and which survives the wrap, so at shipped values the fallback is
        10 s and TIGHTER than the 30 s configured here (measured: 8.01s against an 8 s
        handshake deadline, versus 2.00s with either path in place). The property's job
        is therefore to keep the configured knob authoritative, not to prevent a hang.
        That matters because setup() runs AFTER finish_request, so a `timeout = 30` class
        attribute here would silently beat the server's request_timeout_sec and turn
        that parameter into decoration (measured: a hard-coded 300.0 does exactly that).
        Resolving from the server means any such attribute has to agree with the
        configured value by construction.

        BaseRequestHandler.__init__ assigns self.server before calling setup(), so this
        resolves by the time setup() asks for it.
        """
        return self.app.request_timeout_sec

    @contextmanager
    def _transfer_deadline(self):
        """Widen the socket deadline for a bulk transfer phase, then put it back.

        Deliberately a phase-scoped swap rather than a refresh next to the per-chunk
        session.touch(): settimeout is already per-operation, so re-applying the same
        number every chunk would be a no-op -- the fault was the VALUE, not its
        staleness. A phase swap is also the only mechanism that reaches the upload side,
        where the read loop lives inside storage.save_stream and offers no per-chunk
        seam to hook.

        Restoring the previous value matters for the response written after the phase
        ends, not for a subsequent request: _Handler never sets protocol_version, so it
        is HTTP/1.0 and close_connection is always True -- there is no next request line
        on this connection. Without the restore, a phone that vanished right after its
        last body byte would park a worker for the full transfer deadline trying to
        write a forty-byte response. Measured: the upload's 200 goes out with the socket
        back at 3 s rather than the 77 s the transfer phase ran under.
        """
        sock = self.connection
        previous = sock.gettimeout()
        sock.settimeout(self.app.transfer_timeout_sec)
        try:
            yield
        finally:
            try:
                sock.settimeout(previous)
            except OSError:
                pass  # the peer went away mid-transfer; the socket is already done

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

    # CONTRIBUTOR NOTE: the subnet check below is automatic for every route, but token
    # auth is NOT. Any new route that returns private data or performs an action MUST
    # verify the session token (see do_POST handlers and _outbox_gate). "/ca.crt" is
    # intentionally unauthenticated because it serves only the public CA cert; do not
    # copy that pattern to anything sensitive.
    def do_GET(self):
        if not self._client_allowed():
            self._send(HTTPStatus.FORBIDDEN, b"off-subnet")
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/ca.crt":
            self._serve_ca()
            return
        if parsed.path == "/outbox":
            self._serve_manifest()
            return
        if parsed.path.startswith("/outbox/"):
            self._serve_outbox_file(parsed.path[len("/outbox/"):])
            return
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

    def _outbox_gate(self) -> bool:
        """Token cookie plus PIN auth, exactly as /upload requires. The subnet check
        has already run in do_GET."""
        if not self._valid_token_cookie():
            self._send(HTTPStatus.FORBIDDEN, b"invalid token")
            return False
        if not self.app.session.authed:
            self._send(HTTPStatus.UNAUTHORIZED, b"not authed")
            return False
        return True

    def _serve_manifest(self):
        if not self._outbox_gate():
            return
        self.app.session.touch()
        items = [{"id": e.id, "name": e.name, "size": e.size, "ctype": e.ctype}
                 for e in self.app.outbox.list()]
        self._send(HTTPStatus.OK, json.dumps(items).encode(), "application/json")

    def _serve_outbox_file(self, raw_id: str):
        if not self._outbox_gate():
            return
        # raw_id is untrusted, and is used only as a dictionary key. There is no path
        # built from it, so traversal cannot reach the filesystem.
        entry = self.app.outbox.get(urllib.parse.unquote(raw_id))
        if entry is None:
            self._send(HTTPStatus.NOT_FOUND, b"not found")
            return
        # Re-check filesystem state only: the file may have been deleted since it was
        # picked. Deliberately no media re-check here — name and ctype were frozen on
        # the entry at add time, so testing them again would evaluate a pure function
        # over unchanged inputs and could never fail.
        if not entry.path.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"not found")
            return
        try:
            size = entry.path.stat().st_size
            handle = entry.path.open("rb")
        except OSError:
            self._send(HTTPStatus.NOT_FOUND, b"not found")
            return
        self.app.session.touch()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", entry.ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", _content_disposition(entry.name))
        self.end_headers()
        # The whole stream runs under the loose deadline. A TimeoutError out of
        # wfile.write here is the phone having gone away for good; handle_one_request
        # catches it, sets close_connection and returns, so it stays an ordinary
        # disconnect and never reaches socketserver.handle_error.
        with self._transfer_deadline(), handle as f:
            remaining = size
            while remaining > 0:
                chunk = f.read(min(self.app.chunk_bytes, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)
                # Refresh the idle timer per chunk, not only before the first byte.
                # ui.py polls session.is_idle() every 400 ms and calls stop() when it
                # trips, so any transfer lasting longer than the idle timeout was being
                # killed midway -- at the shipped 600 s that is a 2 GiB file on any link
                # under about 3.5 MB/s. touch() is one lock and one clock read.
                self.app.session.touch()

    def _serve_ca(self):
        # The CA *public* certificate (no private key). Unauthenticated on purpose:
        # a phone needs it to establish trust before the token flow. Subnet-checked
        # like every request. The MIME type makes iOS offer to install it.
        ca = self.app.ca_cert_path
        if ca is None or not ca.exists():
            self._send(HTTPStatus.NOT_FOUND, b"no CA")
            return
        self._send(HTTPStatus.OK, ca.read_bytes(), "application/x-x509-ca-cert",
                   {"Content-Disposition": 'attachment; filename="PhotoDropCA.crt"'})

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
            with self._transfer_deadline():
                saved = storage.save_stream(
                    self.rfile, length, self.app.destination_dir, raw_name,
                    max_file_bytes=self.app.max_file_bytes,
                    chunk_bytes=self.app.chunk_bytes,
                )
        except ValueError:
            self._reject_upload(HTTPStatus.BAD_REQUEST, b"rejected")
            return
        # TimeoutError MUST be caught above OSError, which it subclasses. A stalled
        # phone otherwise lands in the disk-failure branch below and is told its storage
        # gave out -- measured, a 35 s pause mid-upload answered 507 Insufficient
        # Storage. save_stream's own `finally` unlinks the .part file either way, so
        # nothing partial is left behind; only the diagnosis was wrong.
        except TimeoutError:
            self._reject_upload(HTTPStatus.REQUEST_TIMEOUT, b"upload stalled")
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
