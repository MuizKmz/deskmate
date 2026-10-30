"""Starts DeskMate without a console window.

run_deskmate.bat uses this, and so does "Start with Windows".
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    import PySide6  # noqa: F401  (just checking it's installed)
except ImportError:
    from deskmate.app import native_message

    native_message(
        "DeskMate needs PySide6, which isn't installed yet.\n\n"
        "Double-click run_deskmate.bat once to set everything up."
    )
    sys.exit(1)

from deskmate.app import safe_main

sys.exit(safe_main())
