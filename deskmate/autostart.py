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


def _program_in(command: str) -> Path | None:
    """The program a startup command runs: the first quoted (or first plain) word."""
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        return Path(command[1:end]) if end > 1 else None
    return Path(command.split()[0]) if command else None


def needs_repair(current: str | None, ours: str) -> bool:
    """Only fix the entry when what it points at is gone (the folder was moved or deleted).

    If it points at another DeskMate that still exists (say the installed app, while you
    also run the source folder), leave it alone, so two copies don't keep stealing it."""
    if not current or current == ours:
        return False
    program = _program_in(current)
    if program is None or not program.exists():
        return True
    script = current[len(f'"{program}"'):].strip().strip('"') if current.startswith('"') else ""
    return bool(script) and script.endswith(".pyw") and not Path(script).exists()


def refresh_if_moved() -> None:
    """If the DeskMate this entry starts was moved or deleted, point the entry at this copy."""
    if not supported():
        return
    current = _read()
    if needs_repair(current, launch_command()):
        log.info("The startup entry pointed at a DeskMate that's gone; updating it")
        set_enabled(True)
