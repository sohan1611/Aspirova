"""Progress watchdog for crawl runs.

The workflow's step timeout is only a last-resort guard. This watchdog tracks
heartbeats from the crawler and escalates when the process is alive but stops
making progress.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TextIO

DEFAULT_HANG_AFTER_SECONDS = 600.0
DEFAULT_HANG_HARD_AFTER_SECONDS = 120.0
DEFAULT_CHECK_INTERVAL_SECONDS = 5.0
HARD_EXIT_CODE = 70


def _configured_seconds(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError:
        print(
            f"WARNING: {name} must be a number; using {default:.0f} seconds",
            flush=True,
        )
        return default
    return max(value, 0.0)


def _default_hard_exit() -> None:
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(HARD_EXIT_CODE)


class CrawlWatchdog:
    """Tracks crawl progress and escalates from graceful stop to hard exit."""

    def __init__(
        self,
        *,
        hang_after_seconds: float = DEFAULT_HANG_AFTER_SECONDS,
        hard_after_seconds: float = DEFAULT_HANG_HARD_AFTER_SECONDS,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        on_soft_hang: Callable[[], None],
        hard_exit: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        output: TextIO | None = None,
    ) -> None:
        self._hang_after_seconds = max(hang_after_seconds, 0.0)
        self._hard_after_seconds = max(hard_after_seconds, 0.0)
        self._check_interval_seconds = max(check_interval_seconds, 0.1)
        self._on_soft_hang = on_soft_hang
        self._hard_exit = hard_exit or _default_hard_exit
        self._clock = clock
        self._output = output if output is not None else sys.stdout

        self._lock = threading.Lock()
        self._last_activity = "crawl-start"
        self._last_beat_monotonic = self._clock()
        self._soft_hang_reported_at: float | None = None
        self._ever_reported_hang = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def from_env(cls, *, on_soft_hang: Callable[[], None]) -> "CrawlWatchdog":
        return cls(
            hang_after_seconds=_configured_seconds(
                "HANG_AFTER_SECONDS", DEFAULT_HANG_AFTER_SECONDS
            ),
            hard_after_seconds=_configured_seconds(
                "HANG_HARD_AFTER_SECONDS", DEFAULT_HANG_HARD_AFTER_SECONDS
            ),
            on_soft_hang=on_soft_hang,
        )

    @property
    def ever_reported_hang(self) -> bool:
        with self._lock:
            return self._ever_reported_hang

    def beat(self, activity: str) -> None:
        with self._lock:
            self._last_activity = activity.strip() or "unknown"
            self._last_beat_monotonic = self._clock()
            self._soft_hang_reported_at = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="crawl-progress-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def check_once(self) -> None:
        now = self._clock()
        soft_hang = False
        hard_hang = False
        message: str | None = None

        with self._lock:
            elapsed = max(now - self._last_beat_monotonic, 0.0)
            if elapsed < self._hang_after_seconds:
                return

            if self._soft_hang_reported_at is None:
                self._soft_hang_reported_at = now
                self._ever_reported_hang = True
                soft_hang = True
                message = (
                    f"HUNG: no progress for {elapsed:.0f}s; "
                    f"last activity was {self._last_activity}"
                )
            elif elapsed >= self._hang_after_seconds + self._hard_after_seconds:
                self._ever_reported_hang = True
                hard_hang = True
                message = (
                    f"HUNG: hard exit after {elapsed:.0f}s without progress; "
                    f"last activity was {self._last_activity}"
                )

        if message is not None:
            print(message, file=self._output, flush=True)

        if soft_hang:
            self._on_soft_hang()
            return

        if hard_hang:
            self._flush_outputs()
            self._hard_exit()

    def _run(self) -> None:
        while not self._stop_event.wait(self._check_interval_seconds):
            self.check_once()

    def _flush_outputs(self) -> None:
        for stream in (self._output, sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass


_ACTIVE_WATCHDOG: CrawlWatchdog | None = None
_ACTIVE_LOCK = threading.Lock()


def beat(activity: str) -> None:
    with _ACTIVE_LOCK:
        active = _ACTIVE_WATCHDOG
    if active is not None:
        active.beat(activity)


@contextmanager
def watch(*, on_soft_hang: Callable[[], None]) -> Iterator[CrawlWatchdog]:
    global _ACTIVE_WATCHDOG

    active = CrawlWatchdog.from_env(on_soft_hang=on_soft_hang)
    with _ACTIVE_LOCK:
        _ACTIVE_WATCHDOG = active
    active.start()
    try:
        yield active
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_WATCHDOG = None
        if not active.ever_reported_hang:
            active.stop()
