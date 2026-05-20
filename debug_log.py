"""
Process-wide debug log for API requests/responses and app exceptions.
The DebugPanel UI subscribes to it.
"""
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass


@dataclass
class LogEntry:
    timestamp: float
    kind: str       # "request" | "response" | "exception" | "info"
    name: str
    details: dict

    @property
    def time_str(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))


class DebugLog:
    def __init__(self, max_entries: int = 500):
        self._entries = deque(maxlen=max_entries)
        self._listeners = []
        self._lock = threading.Lock()

    def add_listener(self, cb):
        self._listeners.append(cb)

    def remove_listener(self, cb):
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

    def log_request(self, name: str, *,
                    model: str = "", system: str = "", user: str = "",
                    url: str = "", method: str = "POST", extra: dict = None):
        self._push(LogEntry(
            timestamp=time.time(), kind="request", name=name,
            details={
                "model": model, "system": system, "user": user,
                "url": url, "method": method, **(extra or {}),
            },
        ))

    def log_response(self, name: str, *,
                     status: str = "", duration: float = 0.0,
                     response: str = "", error: str = "", extra: dict = None):
        self._push(LogEntry(
            timestamp=time.time(), kind="response", name=name,
            details={
                "status": status, "duration_s": round(duration, 3),
                "response": response, "error": error, **(extra or {}),
            },
        ))

    def log_exception(self, where: str, exc: BaseException):
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._push(LogEntry(
            timestamp=time.time(), kind="exception", name=where,
            details={"type": type(exc).__name__, "message": str(exc), "traceback": tb},
        ))

    def log_info(self, name: str, message: str):
        self._push(LogEntry(
            timestamp=time.time(), kind="info", name=name,
            details={"message": message},
        ))

    def _push(self, entry: LogEntry):
        with self._lock:
            self._entries.append(entry)
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(entry)
            except Exception:
                pass  # never let a listener crash the producer

    def entries(self) -> list:
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(None)  # None = full reset
            except Exception:
                pass


DEBUG_LOG = DebugLog()


def _install_hooks():
    """Catch unhandled exceptions process-wide and route them into the log."""
    original = sys.excepthook
    def _hook(exc_type, exc, tb):
        try:
            DEBUG_LOG.log_exception("sys.excepthook", exc)
        except Exception:
            pass
        original(exc_type, exc, tb)
    sys.excepthook = _hook


_install_hooks()
