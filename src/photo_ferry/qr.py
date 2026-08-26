"""QR code helpers built on segno (pure-Python)."""
from __future__ import annotations

import io

import segno


def receiver_url(ip: str, port: int, token: str) -> str:
    return f"https://{ip}:{port}/?t={token}"


def png_bytes(data: str, *, scale: int = 6) -> bytes:
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()
