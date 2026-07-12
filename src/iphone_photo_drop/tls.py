"""Self-signed TLS via a local certificate authority (openssl, from Git-for-Windows).

The model: setup creates a local CA once. The server presents a leaf certificate
for the current LAN IP, signed by that CA. Install the CA on a phone once and the
browser trusts every leaf it signs, so the "not private" warning never returns,
even when the session token or the PC's LAN IP changes.

Fallback if openssl is absent: Windows New-SelfSignedCertificate (see README).
HTTPS is required regardless.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

_GIT_OPENSSL = r"C:\Program Files\Git\usr\bin\openssl.exe"
# Suppress the console window when openssl is spawned from the windowless GUI.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

CA_COMMON_NAME = "Photo Drop Local CA"


def find_openssl() -> str | None:
    found = shutil.which("openssl")
    if found:
        return found
    if Path(_GIT_OPENSSL).exists():
        return _GIT_OPENSSL
    return None


def _require_openssl() -> str:
    openssl = find_openssl()
    if openssl is None:
        raise RuntimeError("openssl not found; see README for the manual cert step")
    return openssl


def _run(openssl: str, args: list[str]) -> None:
    subprocess.run([openssl, *args], check=True, capture_output=True,
                   creationflags=_NO_WINDOW)


def _san(lan_ip: str) -> str:
    return f"subjectAltName=IP:{lan_ip},IP:127.0.0.1,DNS:localhost"


def generate_self_signed(lan_ip: str, cert_path: Path, key_path: Path) -> None:
    """A single self-signed leaf (used by tests and as a simple fallback)."""
    openssl = _require_openssl()
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    _run(openssl, [
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key_path), "-out", str(cert_path),
        "-days", "825", "-subj", "/CN=Photo Drop", "-addext", _san(lan_ip),
    ])


def generate_ca(ca_cert_path: Path, ca_key_path: Path) -> None:
    """Create the local root CA (long-lived; installed on the phone once)."""
    openssl = _require_openssl()
    ca_cert_path.parent.mkdir(parents=True, exist_ok=True)
    _run(openssl, [
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(ca_key_path), "-out", str(ca_cert_path),
        "-days", "3650", "-subj", f"/CN={CA_COMMON_NAME}",
        "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    ])


def generate_leaf(lan_ip: str, ca_cert_path: Path, ca_key_path: Path,
                  cert_path: Path, key_path: Path) -> None:
    """Create a server key + leaf cert for lan_ip, signed by the CA.

    Writes cert_path as the leaf followed by the CA (fullchain) so clients that
    lack the CA still receive it, and key_path as the leaf private key.
    """
    openssl = _require_openssl()
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        csr = Path(td) / "leaf.csr"
        leaf = Path(td) / "leaf.pem"
        _run(openssl, [
            "req", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key_path), "-out", str(csr),
            "-subj", f"/CN={lan_ip}",
            "-addext", _san(lan_ip),
            "-addext", "extendedKeyUsage=serverAuth",
            "-addext", "basicConstraints=critical,CA:FALSE",
        ])
        _run(openssl, [
            "x509", "-req", "-in", str(csr),
            "-CA", str(ca_cert_path), "-CAkey", str(ca_key_path), "-CAcreateserial",
            "-out", str(leaf), "-days", "825", "-copy_extensions", "copyall",
        ])
        cert_path.write_bytes(leaf.read_bytes() + ca_cert_path.read_bytes())


def ensure_server_cert(lan_ip: str, ca_cert_path: Path, ca_key_path: Path,
                       cert_path: Path, key_path: Path, ip_marker_path: Path) -> None:
    """Ensure a leaf cert for the current lan_ip exists, regenerating it only when
    the IP has changed (or files are missing). Reused unchanged on the common path,
    so no openssl runs at launch when the IP is stable.
    """
    if not ca_cert_path.exists() or not ca_key_path.exists():
        raise RuntimeError("local CA missing; run setup first")
    stale = (
        not cert_path.exists()
        or not key_path.exists()
        or not ip_marker_path.exists()
        or ip_marker_path.read_text(encoding="utf-8").strip() != lan_ip
    )
    if stale:
        generate_leaf(lan_ip, ca_cert_path, ca_key_path, cert_path, key_path)
        ip_marker_path.write_text(lan_ip, encoding="utf-8")


def setup(lan_ip: str, ca_cert_path: Path, ca_key_path: Path,
          cert_path: Path, key_path: Path, ip_marker_path: Path) -> None:
    """One-time install helper: create the CA if absent (never overwrite an existing
    one, which would invalidate a phone's trust), then ensure a leaf for lan_ip."""
    if not ca_cert_path.exists() or not ca_key_path.exists():
        generate_ca(ca_cert_path, ca_key_path)
    ensure_server_cert(lan_ip, ca_cert_path, ca_key_path, cert_path, key_path,
                       ip_marker_path)
