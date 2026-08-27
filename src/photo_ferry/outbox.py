"""Files the PC is offering to the phone, addressed only by opaque id.

The id is the whole security model for the outbound path: the URL never carries a
filesystem path, so a request can only ever name a file the user explicitly picked.
Traversal is not filtered here — it is impossible, because the untrusted input is a
dictionary key.
"""
from __future__ import annotations

import mimetypes
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path

from . import security


@dataclass(frozen=True)
class OutboxEntry:
    id: str
    path: Path
    name: str
    size: int
    ctype: str


def guess_ctype(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


class Outbox:
    """Thread-safe: the Tk thread adds while request threads read."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, OutboxEntry] = {}
        self._order: list[str] = []

    def add(self, paths) -> list[OutboxEntry]:
        """Register each path that is a real, allowed media file. Others are skipped."""
        added: list[OutboxEntry] = []
        for raw in paths:
            path = Path(raw).resolve()
            if not path.is_file():
                continue
            # Reuse the hardened sanitizer for the extension allowlist and for names
            # unsafe on the filesystem. It is not a header sanitizer: it happens to
            # reject double quotes today, but that is incidental to its filesystem
            # purpose, so the Content-Disposition header strips them itself.
            try:
                name = security.sanitize_filename(path.name)
            except ValueError:
                continue
            # Store the value the allowlist actually validated, never the raw one it was
            # derived from. `is_allowed_media` compares a normalized string, so keeping
            # the raw form here let a type carrying a stray CRLF -- mimetypes reads these
            # from the Windows registry, which is user-writable -- pass validation and
            # then split the Content-Type header. Normalizing first also makes the stored
            # value provably one of the allowlist literals, so it is always single-line.
            ctype = security.normalize_ctype(guess_ctype(name))
            if not security.is_allowed_media(name, ctype):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            entry = OutboxEntry(id=secrets.token_urlsafe(16), path=path,
                                name=name, size=size, ctype=ctype)
            with self._lock:
                self._entries[entry.id] = entry
                self._order.append(entry.id)
            added.append(entry)
        return added

    def list(self) -> list[OutboxEntry]:
        with self._lock:
            return [self._entries[i] for i in self._order]

    def get(self, entry_id: str) -> OutboxEntry | None:
        with self._lock:
            return self._entries.get(entry_id)

    def remove(self, entry_id: str) -> None:
        with self._lock:
            if self._entries.pop(entry_id, None) is not None:
                self._order.remove(entry_id)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._order.clear()
