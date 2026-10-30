"""'Start with Windows': a per-user entry in the registry Run key.

Only touches ``HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
(no admin rights needed), and only when you tick the option in DeskMate's menu.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .paths import project_root

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DeskMate"


def supported() -> bool:
    return sys.platform == "win32"


def launch_command() -> str:
    """The command Windows runs at sign-in (no console window)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.exists():
        exe = pythonw
    return f'"{exe}" "{project_root() / "run_deskmate.pyw"}"'


def _read() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return None


def is_enabled() -> bool:
    return supported() and bool(_read())


def set_enabled(enabled: bool) -> bool:
    """Returns True on success; logs and returns False on failure."""
    if not supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.error("Could not change 'Start with Windows': %s", exc)
        return False


def refresh_if_moved() -> None:
    """If the DeskMate folder was moved, point the startup entry at the new place."""
    if not supported():
        return
    current = _read()
    if current and current != launch_command():
        log.info("DeskMate folder moved; updating the startup entry")
        set_enabled(True)
