"""Logging that keeps working when DeskMate runs without a console window.

When started with ``pythonw`` there is no terminal, so an error would vanish
silently. Everything (including crashes and Qt warnings) goes to a rotating
log file in the data folder instead: ``deskmate.log`` (max ~1 MB x 4 files).
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MARK = "_deskmate_handler"


def setup_logging(log_dir: Path, debug: bool = False) -> Path:
    log_path = Path(log_dir) / "deskmate.log"
    root = logging.getLogger()
    for handler in list(root.handlers):  # safe to call twice (tests, restarts)
        if getattr(handler, _MARK, False):
            root.removeHandler(handler)
            handler.close()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    handlers: list[logging.Handler] = []
    try:
        handlers.append(RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        pass  # read-only disk or similar: still run, just without a log file
    if sys.stderr is not None:  # pythonw sets sys.stderr to None
        handlers.append(logging.StreamHandler(sys.stderr))

    formatter = logging.Formatter(_FORMAT)
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _MARK, True)
        root.addHandler(handler)

    def _excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.getLogger("deskmate").critical("Unhandled error", exc_info=(exc_type, exc, tb))

    def _thread_hook(args):
        name = args.thread.name if args.thread else "?"
        logging.getLogger("deskmate").critical(
            "Unhandled error in thread %s", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    return log_path


def install_qt_message_handler() -> None:
    """Route Qt's own warnings into the same log file."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    log = logging.getLogger("qt")
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, _context, message):
        log.log(levels.get(mode, logging.INFO), message)

    qInstallMessageHandler(handler)
