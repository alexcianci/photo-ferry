"""Pins the single Outbox that app.main() shares between the server and the window.

main() builds one Outbox and hands it to both ReceiverServer and ReceiverWindow. That
wiring is load-bearing and silently optional: ReceiverServer.__init__ declares
`outbox: Outbox | None = None` and falls back to building its own, so deleting
`outbox=outbox` from the call leaves the whole suite green -- the panel still fills and
the outbox listbox still populates -- while the phone fetches an empty manifest. It is
the one invariant in this feature whose failure mode looks exactly like success, so it
is asserted head-on rather than left to an end-to-end test that does not exist.

No Tk widget is constructed anywhere here. Tkinter UI is not unit-tested in this
codebase and this test does not start: both collaborators are replaced with recorders,
so main() never reaches a real window, a real socket, or openssl.
"""
import inspect

import pytest

from photo_ferry import app
from photo_ferry.config import default_config
from photo_ferry.outbox import Outbox
from photo_ferry.server import ReceiverServer
from photo_ferry.ui import ReceiverWindow


def _make_recorder(calls):
    """A stand-in class that appends every instance, with its arguments, to `calls`."""

    class Recorder:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            calls.append(self)

        def run(self) -> None:
            """ReceiverWindow.run() is main()'s last statement; here it must do nothing."""

    return Recorder


def _arguments(real_cls, recorded):
    """The recorded call re-read through the real class's signature.

    Binding against the genuine __init__ means the assertions hold whether an argument
    was passed positionally or by keyword, and a deleted argument comes back as its
    declared default -- None for `outbox` -- rather than as a KeyError that would report
    the wrong fault.
    """
    bound = inspect.signature(real_cls).bind(*recorded.args, **recorded.kwargs)
    bound.apply_defaults()
    return bound.arguments


def test_main_shares_one_outbox_between_server_and_window(monkeypatch, tmp_path):
    # Hermetic: no LAN probe, no %LOCALAPPDATA% certs, no openssl, no free port needed.
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    cfg = default_config()  # same environment, so the same paths main() will read
    cfg.ca_cert_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.ca_cert_path.write_text("stand-in CA, never parsed: tls is stubbed below")
    cfg.ca_key_path.write_text("stand-in key, never parsed")

    monkeypatch.setattr(app.net, "detect_lan_ip", lambda: "192.168.1.50")
    monkeypatch.setattr(app.net, "port_in_use", lambda host, port: False)
    monkeypatch.setattr(app.tls, "ensure_server_cert", lambda *a, **kw: None)
    # Fail loudly instead of raising a Tk error dialog and SystemExit. Reaching _fatal
    # means the stubs above stopped covering main()'s preflight -- a different fault
    # from the invariant under test, and it should say so.
    monkeypatch.setattr(
        app, "_fatal", lambda message: pytest.fail(f"main() bailed out: {message}")
    )

    server_calls, window_calls = [], []
    monkeypatch.setattr(app, "ReceiverServer", _make_recorder(server_calls))
    monkeypatch.setattr(app, "ReceiverWindow", _make_recorder(window_calls))

    app.main()

    assert len(server_calls) == 1, "main() built the server other than exactly once"
    assert len(window_calls) == 1, "main() built the window other than exactly once"
    server_outbox = _arguments(ReceiverServer, server_calls[0])["outbox"]
    window_outbox = _arguments(ReceiverWindow, window_calls[0])["outbox"]

    assert isinstance(window_outbox, Outbox)
    assert server_outbox is window_outbox, (
        "app.main() must pass the SAME Outbox object to ReceiverServer and\n"
        "ReceiverWindow. ReceiverServer's `outbox` argument defaults to None and it then\n"
        "quietly builds its own, so dropping `outbox=outbox` from that call breaks\n"
        "nothing a test or a user can see: the send panel fills a registry no route can\n"
        "read, and the phone is served an empty manifest.\n"
        f"  server got: {server_outbox!r}\n"
        f"  window got: {window_outbox!r}"
    )
