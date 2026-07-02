from __future__ import annotations

import threading
import time

_WINDOW_S = 60.0
_THRESHOLD = 3
_OPEN_S = 30.0


class CircuitBreaker:
    """A small, thread-safe circuit breaker with a half-open single-probe recovery phase.

    State per ``key`` (typically a device id):

    * **closed** — calls flow; transient failures accumulate inside a sliding window.
      Once ``threshold`` failures happen within ``window_s`` the breaker **opens**.
    * **open** — every call is short-circuited for ``open_s`` seconds so a struggling
      device is left alone.
    * **half-open** — when ``open_s`` elapses, exactly one probe call is admitted. If it
      succeeds the breaker closes; if it fails the breaker re-opens for another ``open_s``.
      Concurrent callers are blocked while the single probe is in flight, avoiding a
      thundering herd on recovery.

    Each :class:`~onveef.client.OnvifClient` owns its own instance; the module-level
    functions below operate on a shared process-wide default for backwards compatibility.
    """

    def __init__(
        self,
        *,
        window_s: float = _WINDOW_S,
        threshold: int = _THRESHOLD,
        open_s: float = _OPEN_S,
    ) -> None:
        self.window_s = window_s
        self.threshold = threshold
        self.open_s = open_s
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}
        self._open_until: dict[str, float] = {}
        self._probe_inflight: set[str] = set()

    def configure(
        self,
        *,
        window_s: float | None = None,
        threshold: int | None = None,
        open_s: float | None = None,
    ) -> None:
        """Adjust the sliding-window length, failure threshold, and open duration."""
        with self._lock:
            if window_s is not None:
                self.window_s = window_s
            if threshold is not None:
                self.threshold = threshold
            if open_s is not None:
                self.open_s = open_s

    def is_open(self, key: str) -> bool:
        """Return ``True`` if a call for ``key`` should be short-circuited right now."""
        now = time.monotonic()
        with self._lock:
            until = self._open_until.get(key)
            if until is None:
                return False
            if now < until:
                return True
            if key in self._probe_inflight:
                return True
            self._probe_inflight.add(key)
            return False

    def record_failure(self, key: str) -> None:
        """Record a transient failure; may open (or re-open, from half-open) the breaker."""
        now = time.monotonic()
        with self._lock:
            if key in self._probe_inflight:
                self._probe_inflight.discard(key)
                self._open_until[key] = now + self.open_s
                self._failures.pop(key, None)
                return
            recent = [t for t in self._failures.get(key, []) if now - t < self.window_s]
            recent.append(now)
            self._failures[key] = recent
            if len(recent) >= self.threshold:
                self._open_until[key] = now + self.open_s
                self._failures.pop(key, None)

    def record_success(self, key: str) -> None:
        """Record a success; closes the breaker and clears all failure state for ``key``."""
        with self._lock:
            self._failures.pop(key, None)
            self._open_until.pop(key, None)
            self._probe_inflight.discard(key)

    def reset(self) -> None:
        """Forget all state for every key (mainly for tests)."""
        with self._lock:
            self._failures.clear()
            self._open_until.clear()
            self._probe_inflight.clear()


_default = CircuitBreaker()


def configure(
    *,
    window_s: float | None = None,
    threshold: int | None = None,
    open_s: float | None = None,
) -> None:
    """Configure the process-wide default circuit breaker."""
    global _WINDOW_S, _THRESHOLD, _OPEN_S
    if window_s is not None:
        _WINDOW_S = window_s
    if threshold is not None:
        _THRESHOLD = threshold
    if open_s is not None:
        _OPEN_S = open_s
    _default.configure(window_s=window_s, threshold=threshold, open_s=open_s)


def is_open(device_key: str) -> bool:
    """Return whether the default breaker is open for ``device_key``."""
    return _default.is_open(device_key)


def record_failure(device_key: str) -> None:
    """Record a failure on the default breaker."""
    _default.record_failure(device_key)


def record_success(device_key: str) -> None:
    """Record a success on the default breaker."""
    _default.record_success(device_key)


def reset() -> None:
    """Reset the default breaker's state."""
    _default.reset()
