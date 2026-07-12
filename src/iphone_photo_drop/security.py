"""Auth primitives and file-name/media validation. Pure functions, no I/O."""
from __future__ import annotations

import hmac
import secrets


def generate_token() -> str:
    """128-bit URL-safe session token."""
    return secrets.token_urlsafe(16)


def generate_pin() -> str:
    """Six-digit numeric PIN, zero-padded, uniformly random."""
    return f"{secrets.randbelow(1_000_000):06d}"


def verify_token(expected: str, provided: str | None) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(expected, provided)


def verify_pin(expected: str, provided: str | None) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(expected, provided)
