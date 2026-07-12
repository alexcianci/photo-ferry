"""Stream an uploaded file to the destination folder, safely and atomically."""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import BinaryIO

from . import security


def _unique_path(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem, ext = os.path.splitext(name)
    i = 1
    while True:
        candidate = dest_dir / f"{stem} ({i}){ext}"
        if not candidate.exists():
            return candidate
        i += 1


def save_stream(
    src: BinaryIO,
    content_length: int,
    dest_dir: Path,
    raw_filename: str,
    *,
    max_file_bytes: int,
    chunk_bytes: int = 64 * 1024,
) -> Path:
    """Validate the filename, stream `content_length` bytes to a temp file with a
    running size cap, then atomically move it into place with a unique name.
    Raises ValueError on a bad name or oversize; leaves no partial file behind.
    """
    safe_name = security.sanitize_filename(raw_filename)  # raises on bad input
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f".{safe_name}.{secrets.token_hex(8)}.part"

    committed = False
    try:
        written = 0
        with open(tmp, "wb") as f:
            remaining = content_length
            while remaining > 0:
                chunk = src.read(min(chunk_bytes, remaining))
                if not chunk:
                    break
                written += len(chunk)
                if written > max_file_bytes:
                    raise ValueError("file exceeds max size")
                f.write(chunk)
                remaining -= len(chunk)
        # NOTE: _unique_path + os.replace is a check-then-act; two uploads of the
        # same name racing could clobber (data loss, not a security breach). The
        # upload page uploads strictly sequentially, so this is an accepted low risk.
        final = _unique_path(dest_dir, safe_name)
        os.replace(tmp, final)
        committed = True
        return final
    finally:
        if not committed:
            tmp.unlink(missing_ok=True)
