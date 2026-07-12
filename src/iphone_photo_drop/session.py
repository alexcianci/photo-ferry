"""Thread-safe state for a single receive session."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from . import security


@dataclass(frozen=True)
class ReceivedFile:
    name: str
    size: int


class Session:
    def __init__(
        self,
        token: str,
        pin: str,
        *,
        max_pin_attempts: int = 5,
        idle_timeout_sec: int = 600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.token = token
        self.pin = pin
        self.max_pin_attempts = max_pin_attempts
        self.idle_timeout_sec = idle_timeout_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._authed = False
        self._failed = 0
        self._received: list[ReceivedFile] = []
        self._total = 0
        self._last_activity = clock()

    @classmethod
    def new(cls, **kwargs) -> "Session":
        return cls(security.generate_token(), security.generate_pin(), **kwargs)

    @property
    def authed(self) -> bool:
        with self._lock:
            return self._authed

    @property
    def failed_attempts(self) -> int:
        with self._lock:
            return self._failed

    @property
    def locked_out(self) -> bool:
        with self._lock:
            return self._failed >= self.max_pin_attempts

    @property
    def received(self) -> list[ReceivedFile]:
        with self._lock:
            return list(self._received)

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return self._total

    def register_failure(self) -> int:
        with self._lock:
            self._failed += 1
            return self._failed

    def mark_authed(self) -> None:
        with self._lock:
            self._authed = True
            self._last_activity = self._clock()

    def record_received(self, name: str, size: int) -> None:
        with self._lock:
            self._received.append(ReceivedFile(name, size))
            self._total += size
            self._last_activity = self._clock()

    def touch(self) -> None:
        with self._lock:
            self._last_activity = self._clock()

    def is_idle(self) -> bool:
        with self._lock:
            return (self._clock() - self._last_activity) > self.idle_timeout_sec
