"""Runtime configuration with safe defaults."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import paths

GIB = 1024**3


@dataclass(frozen=True)
class Config:
    port: int
    idle_timeout_sec: int
    max_pin_attempts: int
    max_file_bytes: int
    max_session_bytes: int
    chunk_bytes: int
    subnet_prefix: int
    handshake_timeout_sec: float
    request_timeout_sec: float
    destination_dir: Path
    cert_path: Path
    key_path: Path
    ca_cert_path: Path
    ca_key_path: Path
    cert_ip_marker: Path


def default_config() -> Config:
    return Config(
        port=8443,
        idle_timeout_sec=600,
        max_pin_attempts=5,
        max_file_bytes=2 * GIB,
        max_session_bytes=20 * GIB,
        chunk_bytes=64 * 1024,
        subnet_prefix=24,
        # Both deadlines bound what an UNAUTHENTICATED peer can hold: the TLS handshake,
        # and then the request line and headers. Either one stalled used to park a worker
        # for free, indefinitely, before the subnet check could refuse it.
        handshake_timeout_sec=10.0,
        request_timeout_sec=30.0,
        destination_dir=paths.destination_dir(),
        cert_path=paths.cert_path(),
        key_path=paths.key_path(),
        ca_cert_path=paths.ca_cert_path(),
        ca_key_path=paths.ca_key_path(),
        cert_ip_marker=paths.cert_ip_marker(),
    )
