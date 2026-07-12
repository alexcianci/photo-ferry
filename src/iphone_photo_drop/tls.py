"""Generate a self-signed TLS cert/key via openssl (present via Git-for-Windows).

Fallback if openssl is absent: run Windows New-SelfSignedCertificate manually
(see README). HTTPS is required regardless.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_GIT_OPENSSL = r"C:\Program Files\Git\usr\bin\openssl.exe"


def find_openssl() -> str | None:
    found = shutil.which("openssl")
    if found:
        return found
    if Path(_GIT_OPENSSL).exists():
        return _GIT_OPENSSL
    return None


def generate_self_signed(lan_ip: str, cert_path: Path, key_path: Path) -> None:
    openssl = find_openssl()
    if openssl is None:
        raise RuntimeError("openssl not found; see README for the manual cert step")
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    subject = "/CN=iPhone Photo Drop"
    san = f"subjectAltName=IP:{lan_ip},IP:127.0.0.1,DNS:localhost"
    cmd = [
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key_path), "-out", str(cert_path),
        "-days", "825", "-subj", subject, "-addext", san,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
