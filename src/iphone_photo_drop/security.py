"""Auth primitives and file-name/media validation. Pure functions, no I/O."""
from __future__ import annotations

import hmac
import os
import re
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


ALLOWED_EXTENSIONS = frozenset(
    {".heic", ".heif", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mov", ".mp4", ".m4v"}
)
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "image/heic", "image/heif", "image/jpeg", "image/png", "image/gif",
        "image/webp", "video/quicktime", "video/mp4", "video/x-m4v",
    }
)
# Content types we tolerate because iOS/Safari often omits or genericizes them.
_LENIENT_CONTENT_TYPES = frozenset({"", "application/octet-stream"})
_MAX_NAME_LEN = 200
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _extension(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def sanitize_filename(raw: str) -> str:
    """Return a safe base filename, or raise ValueError if none can be derived."""
    # Take the final path component regardless of / or \ separators.
    base = re.split(r"[\\/]", raw)[-1]
    base = _CONTROL_CHARS.sub("", base)
    base = base.strip().lstrip(".").strip()
    if not base:
        raise ValueError("filename empty after sanitization")

    ext = _extension(base)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"disallowed extension: {ext!r}")

    if len(base) > _MAX_NAME_LEN:
        stem = base[: _MAX_NAME_LEN - len(ext)]
        base = stem + ext
    return base


def is_allowed_media(filename: str, content_type: str) -> bool:
    if _extension(filename) not in ALLOWED_EXTENSIONS:
        return False
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in _LENIENT_CONTENT_TYPES:
        return True
    return ctype in ALLOWED_CONTENT_TYPES
