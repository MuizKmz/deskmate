"""Buddy mode, the window side: asking permission, the 'watching' badge, and screen pictures.

* ``WatchDialog`` asks first, every time: may she watch, for how long, can she see the screen
  itself (or only which app and title), and how chatty may she be.
* ``WatchBadge`` is a small, half see-through 👁 dot by her head while she watches. Click it to stop.
* ``exclude_from_capture`` keeps her own windows out of the screen picture (Windows 10 2004+):
  she sees what's *behind* her, and doesn't flicker. It's switched on only for the moment she
  takes her picture, so your own screenshots and recordings still show her.
* ``QuickReplies``: when she asks you something, little answer chips appear by her bubble.
* ``grab_screen`` + ``snapshot_from`` turn the screen into a small JPEG, kept in memory only.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget,
)

from .chat import Snapshot

MAX_SIDE = 1568  # big enough to read code and small text, small enough to be quick and cheap
JPEG_QUALITY = 85
HIDE_MS = 250  # without capture exclusion: how long she stays invisible before the picture is taken
EXCLUDE_MS = 120  # with it: how long Windows gets to apply it before the picture is taken
REPLIES_SECONDS = 25  # the answer chips go away after this long
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


def crop_to_window(image: QImage, screen: QRect, window: QRect, smallest: int = 120) -> QImage:
    """Cut a whole-screen picture down to one window (all in Qt's logical pixels; the picture has real ones).

    A window that's tiny or mostly off this screen keeps the whole screen instead.
    """
    part = window.intersected(screen)
    if part.width() < smallest or part.height() < smallest:
        return image
    scale_x, scale_y = image.width() / max(1, screen.width()), image.height() / max(1, screen.height())
    box = QRect(round((part.x() - screen.x()) * scale_x), round((part.y() - screen.y()) * scale_y),
                round(part.width() * scale_x), round(part.height() * scale_y))
    return image.copy(box.intersected(image.rect()))


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
            "• While she watches, a small 👁 sign sits by her head. Click it (or Stop in her menu) to end it.<br>"
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
    """A small, half see-through 👁 dot at the corner of her head while she watches.

    It lights up when the mouse is on it (with a tooltip saying how long is left), and a click
    stops watching. Small on purpose: a sign that she's watching, not something to stare at.
    """

    clicked = Signal()
    SIZE = 22
    RESTING, HOVERED = 0.5, 1.0  # how see-through it is

    def __init__(self, name: str, accent: QColor):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._accent = QColor(accent)
        self._name = name
        self._hovered = False
        self.setWindowOpacity(self.RESTING)
        self.set_left("")

    def set_left(self, left: str) -> None:
        """'12 min left' or '' (until you stop it)."""
        tip = f"{self._name} is watching with you" + (f" · {left}" if left else "") + "\nClick to stop watching"
        if tip != self.toolTip():
            self.setToolTip(tip)

    def place(self, head: QRect) -> None:
        """On the top-right corner of her head, a little outside it."""
        self.move(QPoint(head.right() - self.SIZE // 3, head.top() - self.SIZE // 3))

    def enterEvent(self, _event) -> None:
        self._hovered = True
        self.setWindowOpacity(self.HOVERED)
        self.update()

    def leaveEvent(self, _event) -> None:
        self._hovered = False
        self.setWindowOpacity(self.RESTING)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event) -> None:
        from .menu_style import icon

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(24, 19, 34, 230))
        painter.setPen(QPen(self._accent, 1.6 if self._hovered else 1.1))
        painter.drawEllipse(rect)
        size = self.SIZE - 8
        painter.drawPixmap(4, 4, icon("eye", QColor(244, 238, 250)).pixmap(size, size))


def thumbnail(image: QImage, width: int = 240, height: int = 150) -> QPixmap:
    return QPixmap.fromImage(image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))


# --------------------------------------------------------------- quick replies
class QuickReplies(QWidget):
    """A row of little answer chips next to her bubble, when she asks you something. Click one to answer."""

    chosen = Signal(str)       # an answer was clicked: send it as your chat message
    chat_requested = Signal()  # the 💬 chip: open the chat box to type your own answer

    def __init__(self, accent: QColor):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._accent = QColor(accent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(2, 2, 2, 2)
        self._row.setSpacing(6)
        a = self._accent
        self._style = (f"QPushButton {{ color: #F4EEFA; background: rgba(24, 19, 34, 225); border-radius: 12px;"
                       f" border: 1px solid rgba({a.red()}, {a.green()}, {a.blue()}, 200); padding: 4px 11px;"
                       f" font-size: 9pt; }}"
                       f" QPushButton:hover {{ background: rgba({a.red()}, {a.green()}, {a.blue()}, 120); }}")

    def answers(self) -> list[str]:
        return [b.text() for b in self.findChildren(QPushButton) if b.property("answer")]

    def offer(self, answers: list[str], bubble: QRect, available: QRect, chat: bool = True) -> None:
        """Show ``answers`` as chips just above her bubble (or below it, if there's no room).
        ``chat``: also a 💬 chip, to type your own answer."""
        while self._row.count():
            widget = self._row.takeAt(0).widget()
            if widget is not None:
                from .chatbox import discard

                discard(widget)
        for answer in answers:
            self._row.addWidget(self._chip(answer, answer=True))
        if chat:
            self._row.addWidget(self._chip("💬", answer=False))
        self.adjustSize()
        x = bubble.center().x() - self.width() // 2
        y = bubble.top() - self.height() - 2
        if y < available.top():
            y = bubble.bottom() + 4
        x = max(available.left(), min(x, available.right() - self.width()))
        self.move(QPoint(x, y))
        self.show()
        self.raise_()

    def _chip(self, text: str, answer: bool) -> QPushButton:
        chip = QPushButton(text)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setStyleSheet(self._style)
        chip.setProperty("answer", answer)
        chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        chip.setFixedHeight(26)  # same height for all (Qt drops the rounding if a chip is shorter than 24 px)
        if answer:
            chip.clicked.connect(lambda _=False, t=text: self._pick(t))
        else:
            chip.setToolTip("Type your own answer")
            chip.clicked.connect(self._chat)
        return chip

    def _pick(self, text: str) -> None:
        self.hide()
        self.chosen.emit(text)

    def _chat(self) -> None:
        self.hide()
        self.chat_requested.emit()

