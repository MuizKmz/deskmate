"""Buddy mode, the window side: asking permission, the 'watching' badge, and screen pictures.

* ``WatchDialog`` asks first, every time: may she watch, for how long, can she see the screen
  itself (or only which app and title), and how chatty may she be.
* ``WatchBadge`` is a small 👀 pill beside her for as long as she watches. Click it to stop.
* ``exclude_from_capture`` keeps her own windows out of the screen picture (Windows 10 2004+):
  she sees what's *behind* her, and doesn't flicker. Turned off again when she stops watching,
  so your own screenshots and recordings still show her.
* ``grab_screen`` + ``snapshot_from`` turn the screen into a small JPEG, kept in memory only.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout, QWidget,
)

from .chat import Snapshot

MAX_SIDE = 1568  # big enough to read code and small text, small enough to be quick and cheap
JPEG_QUALITY = 85
HIDE_MS = 250  # without capture exclusion: how long she stays invisible before the picture is taken
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11

DURATIONS = [(30, "30 minutes"), (60, "1 hour"), (120, "2 hours"), (0, "Until I stop it")]
LEVELS = [("quiet", "Now and then (every 10 min at most)"), ("normal", "Sometimes (every 4 min at most)"),
          ("chatty", "Often (every 1–2 min)")]


# ------------------------------------------------------------------ pictures
def snapshot_from(image: QImage, max_side: int = MAX_SIDE) -> Snapshot:
    """Shrink (if needed) and JPEG-encode a picture for the chat brain."""
    if max(image.width(), image.height()) > max_side:
        image = image.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    image = image.convertToFormat(QImage.Format.Format_RGB888)  # JPEG has no transparency
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if image.save(buffer, "JPEG", JPEG_QUALITY):
        return Snapshot(bytes(buffer.data()), image.width(), image.height())
    buffer = QBuffer()  # no JPEG support in this Qt build (unusual): PNG is always there
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Snapshot(bytes(buffer.data()), image.width(), image.height(), "image/png")


def grab_screen(screen) -> QImage:
    """A picture of one whole screen, in real pixels."""
    return screen.grabWindow(0).toImage()


def exclude_from_capture(widget: QWidget, on: bool) -> bool:
    """Hide ``widget`` from screen pictures (it stays visible to you). True if Windows did it."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        return bool(user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE))
    except Exception:
        return False


# ---------------------------------------------------------------- permission
class WatchDialog(QDialog):
    """'Can I watch with you?' Asked every time she starts watching."""

    def __init__(self, name: str, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Let {name} watch with you?")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(470)

        intro = QLabel(
            f"<b>{name} will see what you're doing</b> — which app or tab is open, and what's on your screen — "
            f"and react like a friend sitting next to you (“Ooh, is this your study playlist?”). "
            f"You can also ask her about anything on your screen.")
        intro.setWordWrap(True)

        self.duration = QComboBox()
        for minutes, label in DURATIONS:
            self.duration.addItem(label, minutes)
        self.duration.setCurrentIndex(max(0, self.duration.findData(settings["watch_minutes"])))
        self.picture = QCheckBox("She can see the screen itself (smarter)")
        self.picture.setChecked(settings["watch_picture"])
        self.picture.setToolTip("Off: she only knows the app and window title, like \"lofi beats - YouTube\".")
        self.level = QComboBox()
        for level, label in LEVELS:
            self.level.addItem(label, level)
        self.level.setCurrentIndex(max(0, self.level.findData(settings["watch_level"])))

        form = QFormLayout()
        form.addRow("For", self.duration)
        form.addRow("She speaks up", self.level)
        form.addRow("", self.picture)

        privacy = QLabel(
            "• Pictures go only to your chat brain, never saved to disk (today's chat keeps the words).<br>"
            "• She never looks at incognito / private windows, password managers or banking, "
            "and stays quiet during calls.<br>"
            "• While she watches, a 👀 badge sits next to her. Click it (or Stop in her menu) to end it.<br>"
            "• Each comment sends one picture to your chat brain (about a cent or less with a mini/Haiku model).")
        privacy.setWordWrap(True)
        privacy.setStyleSheet("color: gray;")

        buttons = QDialogButtonBox()
        self.allow = buttons.addButton("Let her watch", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Not now", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(6)
        layout.addLayout(form)
        layout.addWidget(privacy)
        layout.addWidget(buttons)

    @property
    def minutes(self) -> int:
        return self.duration.currentData()

    @property
    def with_picture(self) -> bool:
        return self.picture.isChecked()

    @property
    def chattiness(self) -> str:
        return self.level.currentData()


# --------------------------------------------------------------------- badge
class WatchBadge(QWidget):
    """A small '👀 watching' pill beside her while buddy mode is on. Click it to stop."""

    clicked = Signal()
    W, H = 104, 26

    def __init__(self, name: str, accent: QColor):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.W, self.H)
        self._accent = QColor(accent)
        self._text = "👀 watching"
        self._name = name
        self.set_left("")

    def set_left(self, left: str) -> None:
        """'12 min left' or '' (until you stop it)."""
        self.setToolTip(f"{self._name} is watching your screen with you" + (f" ({left})" if left else "")
                        + ".\nClick to stop.")

    def place(self, body: QRect) -> None:
        """Just above her head, on the right."""
        self.move(QPoint(body.right() - self.W + 6, max(0, body.top() - self.H - 2)))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.fillPath(path, QColor(24, 19, 34, 225))
        painter.setPen(QPen(self._accent, 1.4))
        painter.drawPath(path)
        painter.setPen(QColor(244, 238, 250))
        font = painter.font()
        font.setPointSizeF(8.5)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


def thumbnail(image: QImage, width: int = 240, height: int = 150) -> QPixmap:
    return QPixmap.fromImage(image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
