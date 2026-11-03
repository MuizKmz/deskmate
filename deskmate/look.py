"""'Look at my screen': you drag over a part of the screen and she gets a picture of it.

How it goes (the Controller in app.py drives it):

1. She and her windows turn invisible for a moment, so she isn't in her own screenshot.
2. The screen under your mouse is photographed, frozen, and shown full-screen by ScreenPicker.
3. You drag a box over what you want her to see (or press Enter for the whole screen, Esc to
   cancel). The chosen part becomes a Snapshot: a JPEG kept in memory only, never saved.
4. The Snapshot goes to her chat brain together with your question (see chat.ChatSession.show).
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .chat import Snapshot

MAX_SIDE = 1568  # big enough to read code and small text, small enough to be quick and cheap
JPEG_QUALITY = 85
HIDE_MS = 250  # how long to wait after she turns invisible before taking the picture


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


def thumbnail(image: QImage, width: int = 240, height: int = 150) -> QPixmap:
    return QPixmap.fromImage(image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))


class ScreenPicker(QWidget):
    """The frozen screen, dimmed, with a box you drag over the part she should look at."""

    picked = Signal(QImage)  # the chosen part, at full resolution
    cancelled = Signal()
    MIN_DRAG = 12  # smaller than this counts as a click: the whole screen

    HINT = "Drag over what you want me to look at   ·   Enter: whole screen   ·   Esc: cancel"
    SMALL = "The picture only goes to your chat brain with your question. It's never saved."

    def __init__(self, shot: QPixmap, geometry: QRect, accent: QColor):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        super().__init__(None, flags)
        self.setWindowTitle("Look at my screen")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(geometry)
        self._shot = shot
        self._accent = QColor(accent)
        self._start: QPoint | None = None
        self._end: QPoint | None = None
        self._done = False

    def open(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # -------------------------------------------------------------- choosing
    def selection(self) -> QRect:
        if self._start is None or self._end is None:
            return QRect()
        a, b = self._start, self._end  # (QRect(a, b) would include both corners: 1 pixel too big)
        box = QRect(min(a.x(), b.x()), min(a.y(), b.y()), abs(a.x() - b.x()), abs(a.y() - b.y()))
        return box.intersected(self.rect())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.cancel()
        elif event.button() == Qt.MouseButton.LeftButton:
            self._start = self._end = event.position().toPoint()
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._start is not None:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._end = event.position().toPoint()
        box = self.selection()
        self.choose(box if box.width() >= self.MIN_DRAG and box.height() >= self.MIN_DRAG else None)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            box = self.selection()
            self.choose(box if box.width() >= self.MIN_DRAG and box.height() >= self.MIN_DRAG else None)
        else:
            super().keyPressEvent(event)

    def choose(self, box: QRect | None) -> None:
        """``box`` in this window's (logical) pixels, or None for the whole screen."""
        image = self._shot.toImage()
        if box is not None:
            scale_x = image.width() / max(1, self.width())  # the photo has real pixels (e.g. 150% scaling)
            scale_y = image.height() / max(1, self.height())
            real = QRect(round(box.x() * scale_x), round(box.y() * scale_y),
                         round(box.width() * scale_x), round(box.height() * scale_y))
            image = image.copy(real.intersected(image.rect()))
        self._finish()
        self.picked.emit(image)

    def cancel(self) -> None:
        self._finish()
        self.cancelled.emit()

    def _finish(self) -> None:
        self._done = True
        self.hide()
        self.close()

    def closeEvent(self, event) -> None:
        if not self._done:  # closed some other way (Alt+F4): same as Esc
            self._done = True
            self.cancelled.emit()
        super().closeEvent(event)

    # -------------------------------------------------------------- drawing
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(self.rect(), self._shot)
        box = self.selection()
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if not box.isEmpty():
            hole = QPainterPath()
            hole.addRect(QRectF(box))
            shade = shade.subtracted(hole)
        painter.fillPath(shade, QColor(14, 10, 24, 120))
        if not box.isEmpty():
            painter.setPen(QPen(self._accent, 2))
            painter.drawRect(QRectF(box).adjusted(1, 1, -1, -1))
            self._label(painter, f"{box.width()} × {box.height()}", box.bottomRight() + QPoint(-4, 18), right=True)
        self._hint(painter, box)

    def _hint(self, painter: QPainter, box: QRect) -> None:
        font = QFont(self.font())
        font.setPointSizeF(10.5)
        small = QFont(font)
        small.setPointSizeF(8.5)
        painter.setFont(font)
        width = min(max(painter.fontMetrics().horizontalAdvance(self.HINT) + 48, 420), self.width() - 32)
        pill = QRectF((self.width() - width) / 2, 24, width, 56)
        if not box.isEmpty() and pill.intersects(QRectF(box)):
            pill.moveBottom(self.height() - 24)  # don't cover what you're choosing
        path = QPainterPath()
        path.addRoundedRect(pill, 18, 18)
        painter.fillPath(path, QColor(24, 19, 34, 225))
        painter.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 170), 1.2))
        painter.drawPath(path)
        painter.setPen(QColor(244, 238, 250))
        painter.setFont(font)
        painter.drawText(pill.adjusted(12, 8, -12, -26), Qt.AlignmentFlag.AlignCenter, self.HINT)
        painter.setPen(QColor(244, 238, 250, 150))
        painter.setFont(small)
        painter.drawText(pill.adjusted(12, 30, -12, -6), Qt.AlignmentFlag.AlignCenter, self.SMALL)

    def _label(self, painter: QPainter, text: str, at: QPoint, right: bool = False) -> None:
        metrics = painter.fontMetrics()
        rect = QRectF(0, 0, metrics.horizontalAdvance(text) + 12, metrics.height() + 4)
        rect.moveTopRight(at) if right else rect.moveTopLeft(at)
        rect.moveTop(min(rect.top(), self.height() - rect.height() - 2))
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.fillPath(path, QColor(24, 19, 34, 210))
        painter.setPen(QColor(244, 238, 250))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
