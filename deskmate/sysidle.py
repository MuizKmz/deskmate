"""How long since the user last touched the mouse or keyboard?

On Windows we ask the system directly (``GetLastInputInfo``), which counts
both keyboard and mouse. Elsewhere we fall back to watching the mouse cursor.
"""

from __future__ import annotations

import sys
import time
from typing import Callable

_win_api = None  # set up once, on first use


def _windows_api():
    global _win_api
    if _win_api is None:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        kernel32 = ctypes.windll.kernel32
        kernel32.GetTickCount.restype = wintypes.DWORD
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        _win_api = (ctypes.windll.user32.GetLastInputInfo, kernel32.GetTickCount, info, ctypes.byref(info))
    return _win_api


def system_idle_seconds() -> float | None:
    """Seconds since the last keyboard/mouse input, or None if not available."""
    if sys.platform != "win32":
        return None
    try:
        get_last_input, get_tick_count, info, info_ref = _windows_api()
        if not get_last_input(info_ref):
            return None
        # Both values are 32-bit millisecond counters that wrap every ~49.7 days;
        # masking the difference keeps the result right across a wrap.
        elapsed_ms = (get_tick_count() - info.dwTime) & 0xFFFFFFFF
        return elapsed_ms / 1000.0
    except Exception:  # pragma: no cover - only reachable on odd Windows setups
        return None


class IdleTracker:
    """Seconds since the user was last active, with a cursor-based fallback."""

    def __init__(self, cursor_pos: Callable[[], tuple[int, int]], clock: Callable[[], float] = time.monotonic):
        self._cursor_pos = cursor_pos
        self._clock = clock
        self._last_pos: tuple[int, int] | None = None
        self._last_move = clock()
        self.source = "system" if system_idle_seconds() is not None else "cursor"

    def seconds(self) -> float:
        value = system_idle_seconds()
        if value is not None:
            return value
        now = self._clock()
        try:
            pos = self._cursor_pos()
        except Exception:
            return 0.0
        if pos != self._last_pos:
            self._last_pos = pos
            self._last_move = now
        return now - self._last_move
