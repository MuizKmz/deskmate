"""Starts DeskMate without a console window.

Works whichever way it's opened:
  * from run_deskmate.bat or "Start with Windows" (the private .venv Python), or
  * double-clicked directly: it hands over to the .venv Python if setup was done,
    and otherwise offers to run the one-time setup (run_deskmate.bat).
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")
VENV_PYTHONW = os.path.join(VENV, "Scripts", "pythonw.exe")
SETUP = os.path.join(HERE, "run_deskmate.bat")

if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _ask_yes_no(text: str) -> bool:
    import ctypes

    MB_OKCANCEL, MB_ICONINFORMATION, IDOK = 0x1, 0x40, 1
    return ctypes.windll.user32.MessageBoxW(None, text, "DeskMate", MB_OKCANCEL | MB_ICONINFORMATION) == IDOK


# 1) Opened with the wrong Python but setup is done: hand over to the private one.
#    (The environment flag makes sure this can never loop.)
if (
    sys.platform == "win32"
    and os.path.exists(VENV_PYTHONW)
    and not _same_path(sys.prefix, VENV)
    and not os.environ.get("DESKMATE_HANDED_OVER")
):
    subprocess.Popen(
        [VENV_PYTHONW, os.path.abspath(__file__), *sys.argv[1:]],
        cwd=HERE,
        env=dict(os.environ, DESKMATE_HANDED_OVER="1"),
    )
    sys.exit(0)

# 2) PySide6 missing: offer the one-time setup instead of just complaining.
try:
    import PySide6  # noqa: F401  (just checking it's installed)
except ImportError:
    if sys.platform == "win32" and os.path.exists(SETUP):
        if _ask_yes_no(
            "DeskMate needs to set itself up once.\n\n"
            "It installs what it needs into a private folder (.venv) here.\n"
            "Takes 1-2 minutes and needs internet.\n\n"
            "Start the setup now?"
        ):
            os.startfile(SETUP)  # opens a window showing the progress, then starts DeskMate
        sys.exit(0)
    from deskmate.app import native_message

    native_message(
        "DeskMate needs PySide6, which isn't installed yet.\n\n"
        "Run:  pip install -r requirements.txt"
    )
    sys.exit(1)

from deskmate.app import safe_main

sys.exit(safe_main())
