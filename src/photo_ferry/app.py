"""Entry point: wire config, session, server, and the Tkinter window."""
from __future__ import annotations

import sys

from . import net, qr, tls
from .config import default_config
from .server import ReceiverServer
from .session import Session
from .ui import ReceiverWindow


def _fatal(message: str) -> None:
    try:
        import tkinter.messagebox as mb
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        mb.showerror("Photo Ferry", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    cfg = default_config()

    if not cfg.ca_cert_path.exists() or not cfg.ca_key_path.exists():
        _fatal("Setup hasn't run yet. Run setup\\setup.ps1 first.")
        return

    try:
        lan_ip = net.detect_lan_ip()
    except RuntimeError:
        _fatal("No private Wi-Fi/LAN connection found. Connect to your home network.")
        return

    if net.port_in_use(lan_ip, cfg.port):
        _fatal(f"Port {cfg.port} is already in use. Is the receiver already running?")
        return

    # Refresh the leaf certificate if the LAN IP changed since last launch (no-op when
    # stable, so no openssl runs on the common path). The CA that signs it stays put.
    try:
        tls.ensure_server_cert(lan_ip, cfg.ca_cert_path, cfg.ca_key_path,
                               cfg.cert_path, cfg.key_path, cfg.cert_ip_marker)
    except Exception as exc:  # openssl failure, permission, etc.
        _fatal(f"Couldn't prepare the TLS certificate. Re-run setup.\n\n{exc}")
        return

    # The firewall rule is checked off the UI thread (ui.ReceiverWindow) so the window
    # paints instantly; a missing rule surfaces as a non-fatal warning rather than
    # blocking startup.
    session = Session.new(
        max_pin_attempts=cfg.max_pin_attempts,
        idle_timeout_sec=cfg.idle_timeout_sec,
    )
    server = ReceiverServer(
        host=lan_ip, port=cfg.port, session=session,
        destination_dir=cfg.destination_dir,
        cert_path=cfg.cert_path, key_path=cfg.key_path,
        max_file_bytes=cfg.max_file_bytes, max_session_bytes=cfg.max_session_bytes,
        chunk_bytes=cfg.chunk_bytes, subnet_prefix=cfg.subnet_prefix,
        ca_cert_path=cfg.ca_cert_path,
    )
    url = qr.receiver_url(lan_ip, cfg.port, session.token)
    # The UI thread owns shutdown (it polls session.locked_out / is_idle); the server's
    # on_shutdown callback is intentionally left unset here.
    ReceiverWindow(server, url, session.pin).run()


if __name__ == "__main__":
    main()
