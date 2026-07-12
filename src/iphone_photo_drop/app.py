"""Entry point: wire config, session, server, and the Tkinter window."""
from __future__ import annotations

import sys

from . import net, qr
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
        mb.showerror("iPhone Photo Drop", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    cfg = default_config()

    if not cfg.cert_path.exists() or not cfg.key_path.exists():
        _fatal("TLS certificate missing. Run setup\\setup.ps1 first.")
        return

    try:
        lan_ip = net.detect_lan_ip()
    except RuntimeError:
        _fatal("No private Wi-Fi/LAN connection found. Connect to your home network.")
        return

    if net.port_in_use(lan_ip, cfg.port):
        _fatal(f"Port {cfg.port} is already in use. Is the receiver already running?")
        return

    if not net.firewall_rule_present():
        _fatal("Firewall rule missing. Run setup\\setup.ps1 again so your iPhone can "
               "connect (a UAC prompt will appear).")
        return

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
    )
    url = qr.receiver_url(lan_ip, cfg.port, session.token)
    # The UI thread owns shutdown (it polls session.locked_out / is_idle); the server's
    # on_shutdown callback is intentionally left unset here.
    ReceiverWindow(server, url, session.pin).run()


if __name__ == "__main__":
    main()
