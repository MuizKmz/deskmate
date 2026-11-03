"""Window tops she can sit on (Windows only).

The physics in companion.py only sees plain *ledges*: the top edge of a window, in Qt's
logical pixels. This file asks Windows for them, so everything else can be tested with
pretend ledges on any computer.

Which windows count: visible, not minimised, not maximised, not "cloaked" (on another
virtual desktop), with a title, not a tool window, not part of the Windows shell, and not
DeskMate itself. A ledge only counts where no window above it covers the spot.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

MIN_WIDTH = 120  # narrower windows aren't worth sitting on


@dataclass(frozen=True)
class Ledge:
    id: int          # the window handle (HWND)
    left: float
    right: float
    top: float
    bottom: float
    z: int = 0       # 0 = the window on top of all others

    def holds(self, x: float) -> bool:
        return self.left <= x <= self.right


def covered(ledges: list[Ledge], ledge: Ledge, x: float) -> bool:
    """Is this spot on the ledge hidden by a window that's in front of it?"""
    y = ledge.top + 1
    return any(o.z < ledge.z and o.left <= x <= o.right and o.top <= y <= o.bottom for o in ledges)


def supported() -> bool:
    return sys.platform == "win32"


class WindowsLedges:
    """Reads the open windows from Windows (EnumWindows + DWM)."""

    SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
                     "Windows.UI.Core.CoreWindow", "ApplicationFrameWindow_Hidden", "XamlExplorerHostIslandWindow"}

    def __init__(self, to_logical=None):
        import ctypes
        from ctypes import wintypes

        self._ct, self._wt = ctypes, wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._dwm = ctypes.WinDLL("dwmapi")
        self._pid = os.getpid()
        self._to_logical = to_logical or (lambda x, y: (x, y))
        self._proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        # Declare argument types so 64-bit window handles are passed as pointers, not 32-bit ints.
        H, u, d = wintypes.HWND, self._user32, self._dwm
        for name in ("IsWindow", "IsWindowVisible", "IsIconic", "IsZoomed", "GetWindowTextLengthW"):
            getattr(u, name).argtypes = [H]
        u.GetWindowLongW.argtypes = [H, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
        u.GetClassNameW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
        u.EnumWindows.argtypes = [self._proc_type, wintypes.LPARAM]
        d.DwmGetWindowAttribute.argtypes = [H, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        d.DwmGetWindowAttribute.restype = ctypes.c_long  # HRESULT: 0 means OK

    def _rect(self, hwnd) -> tuple[int, int, int, int] | None:
        rect = self._wt.RECT()
        if self._dwm.DwmGetWindowAttribute(hwnd, 9, self._ct.byref(rect), self._ct.sizeof(rect)) != 0:  # frame bounds
            if not self._user32.GetWindowRect(hwnd, self._ct.byref(rect)):
                return None
        return rect.left, rect.top, rect.right, rect.bottom

    def _usable(self, hwnd) -> bool:
        u = self._user32
        if not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd) or u.IsZoomed(hwnd):
            return False
        if u.GetWindowLongW(hwnd, -20) & 0x80:  # WS_EX_TOOLWINDOW
            return False
        if u.GetWindowTextLengthW(hwnd) == 0:
            return False
        pid = self._wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, self._ct.byref(pid))
        if pid.value == self._pid:
            return False
        cloaked = self._ct.c_int(0)
        if self._dwm.DwmGetWindowAttribute(hwnd, 14, self._ct.byref(cloaked), 4) == 0 and cloaked.value:  # CLOAKED
            return False
        name = self._ct.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, name, 256)
        return name.value not in self.SHELL_CLASSES

    def _ledge(self, hwnd, z: int) -> Ledge | None:
        rect = self._rect(hwnd)
        if rect is None:
            return None
        left, top = self._to_logical(rect[0], rect[1])
        right, bottom = self._to_logical(rect[2], rect[3])
        if right - left < MIN_WIDTH or bottom - top < 40:
            return None
        return Ledge(int(hwnd), float(left), float(right), float(top), float(bottom), z)

    def ledges(self) -> list[Ledge]:
        found: list[Ledge] = []

        def visit(hwnd, _param):
            try:
                if self._usable(hwnd):
                    ledge = self._ledge(hwnd, len(found))
                    if ledge is not None:
                        found.append(ledge)
            except Exception:  # one odd window must never stop the rest
                log.debug("Skipped a window", exc_info=True)
            return True

        self._user32.EnumWindows(self._proc_type(visit), 0)  # front-most window first
        return found

    def ledge(self, window_id: int) -> Ledge | None:
        """Where that window's top is now (None if it's gone, minimised, hidden...)."""
        if not window_id:
            return None
        hwnd = self._wt.HWND(window_id)
        if not self._user32.IsWindow(hwnd):
            return None
        try:
            return self._ledge(hwnd, 0) if self._usable(hwnd) else None
        except Exception:
            return None


def qt_to_logical():
    """Convert Windows' physical pixels to Qt's logical ones, per monitor (mixed scaling works)."""
    from PySide6.QtGui import QGuiApplication

    def convert(x: float, y: float) -> tuple[float, float]:
        for screen in QGuiApplication.screens():
            ratio = screen.devicePixelRatio()
            origin = screen.geometry().topLeft()  # Qt keeps each screen's origin, and scales from there
            native_w, native_h = screen.geometry().width() * ratio, screen.geometry().height() * ratio
            if origin.x() <= x < origin.x() + native_w and origin.y() <= y < origin.y() + native_h:
                return origin.x() + (x - origin.x()) / ratio, origin.y() + (y - origin.y()) / ratio
        ratio = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
        return x / ratio, y / ratio

    return convert
