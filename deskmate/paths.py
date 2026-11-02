"""Where DeskMate keeps things.

There are two kinds of location:

* the *project* folder (the code and ``characters/``), which can live anywhere, and
* the *data* folder (settings and logs), which belongs to the current user.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def project_root() -> Path:
    """Folder that contains ``deskmate/`` and ``characters/``."""
    if getattr(sys, "frozen", False):  # a packaged .exe: characters/ sits next to it
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    """Where the files that ship with DeskMate are (inside the .exe's _internal folder when packaged)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", project_root()))
    return project_root()


def characters_dir() -> Path:
    """The characters that come with DeskMate."""
    override = os.environ.get("DESKMATE_CHARACTERS")
    if override:
        return Path(override)
    beside_exe = project_root() / "characters"  # a portable copy with characters/ next to the .exe
    return beside_exe if beside_exe.is_dir() else bundle_root() / "characters"


def character_dirs() -> list[Path]:
    """Every place characters can live: the built-in ones, then your own in the data folder
    (%APPDATA%\\DeskMate\\characters), which survives updates. Same name: yours wins."""
    if os.environ.get("DESKMATE_CHARACTERS"):
        return [characters_dir()]
    return [characters_dir(), data_dir() / "characters"]


def data_dir() -> Path:
    """Per-user folder for settings.json and logs (created if missing)."""
    override = os.environ.get("DESKMATE_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "deskmate"
    base.mkdir(parents=True, exist_ok=True)
    return base
