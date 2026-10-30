"""The speech bubble that pops up next to her head.

It's its own little see-through window so it can sit above her head without
making her window bigger. Text appears letter by letter (a "typing" effect).
To keep words from jumping around while typing, the full text is laid out once
and the not-yet-typed part is drawn invisible.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import QWidget


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value)) if low <= high else low


class SpeechBubble(QWidget):
    MAX_TEXT_WIDTH = 220
    PAD_X, PAD_Y = 14, 10
    RADIUS = 14.0
    TAIL = 11
    MARGIN = 4  # room for the soft shadow
    TYPE_MS = 24  # milliseconds per typed character

    def __init__(self, theme: dict[str, str]):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("DeskMate speech bubble")

        self.set_theme(theme)

        self._doc = QTextDocument(self)
        self._doc.setDocumentMargin(0)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._doc.setDefaultTextOption(option)
        font = QFont(self.font())
        font.setPointSizeF(max(10.0, font.pointSizeF() + 1.0))
        self._doc.setDefaultFont(font)

        self._text = ""
        self._total = 0  # length in the document's own units
        self._shown = 0
        self._text_size = QSize()
        self._opacity = 0.0
        self._tail = "down"
        self._tail_pos = 0.0
        self._anchor = QRect()
        self._avail = QRect()

        self._type_timer = QTimer(self)
        self._type_timer.setInterval(self.TYPE_MS)
        self._type_timer.timeout.connect(self._type_step)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.fade_out)
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(170)
        self._fade.valueChanged.connect(self._on_fade)
        self._fade.finished.connect(self._on_fade_done)
        self._fading_out = False

    # ------------------------------------------------------------------ public
    @property
    def text(self) -> str:
        return self._text

    def set_theme(self, theme: dict[str, str]) -> None:
        self._fill = QColor(theme.get("bubble", "#FFFFFF"))
        self._accent = QColor(theme.get("accent", "#C9A0DC"))
        self._ink = QColor(theme.get("text", "#3B2F4A"))
        self.update()

    def say(self, text: str, duration: float, anchor: QRect, available: QRect) -> None:
        """Show ``text`` next to ``anchor`` (her head, in screen coordinates)."""
        self._text = text
        self._doc.setPlainText(text)
        self._doc.setTextWidth(-1)
        width = min(self.MAX_TEXT_WIDTH, math.ceil(self._doc.idealWidth()) + 2)
        self._doc.setTextWidth(width)
        size = self._doc.size()
        self._text_size = QSize(math.ceil(size.width()), math.ceil(size.height()))
        self._total = max(0, self._doc.characterCount() - 1)
        self._shown = 0

        self._anchor, self._avail = QRect(anchor), QRect(available)
        self._place()

        self._fading_out = False
        if not self.isVisible():
            self._opacity = 0.0
            self.show()
        self._start_fade(1.0)
        self._type_timer.start()
        typing_seconds = self._total * self.TYPE_MS / 1000.0
        self._hide_timer.start(int((duration + typing_seconds) * 1000))
        self.update()

    def reposition(self, anchor: QRect, available: QRect) -> None:
        if not self.isVisible():
            return
        self._anchor, self._avail = QRect(anchor), QRect(available)
        self._place()
        self.update()

    def fade_out(self) -> None:
        if not self.isVisible() or self._fading_out:
            return
        self._fading_out = True
        self._type_timer.stop()
        self._start_fade(0.0)

    def dismiss(self) -> None:
        """Hide immediately (no animation)."""
        self._type_timer.stop()
        self._hide_timer.stop()
        self._fade.stop()
        self._fading_out = False
        self._opacity = 0.0
        self.hide()

    def set_on_top(self, on_top: bool) -> None:
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        if visible:
            self.show()

    # -------------------------------------------------------------- internals
    def _start_fade(self, target: float) -> None:
        self._fade.stop()
        self._fade.setStartValue(float(self._opacity))
        self._fade.setEndValue(float(target))
        self._fade.start()

    def _on_fade(self, value) -> None:
        self._opacity = float(value)
        self.update()

    def _on_fade_done(self) -> None:
        if self._fading_out:
            self._fading_out = False
            self.hide()

    def _type_step(self) -> None:
        self._shown = min(self._total, self._shown + 1)
        if self._shown >= self._total:
            self._type_timer.stop()
        self.update()

    def _bubble_size(self) -> QSize:
        return QSize(self._text_size.width() + 2 * self.PAD_X, self._text_size.height() + 2 * self.PAD_Y)

    def _place(self) -> None:
        bubble = self._bubble_size()
        m, tail, r = self.MARGIN, self.TAIL, self.RADIUS
        head, avail = self._anchor, self._avail

        # Preferred: above her head, tail pointing down.
        win_w, win_h = bubble.width() + 2 * m, bubble.height() + tail + 2 * m
        x = head.center().x() - win_w / 2
        y = head.top() - win_h + 6
        if y >= avail.top():
            self._tail = "down"
            x = _clamp(x, avail.left(), avail.right() - win_w + 1)
            self._tail_pos = _clamp(head.center().x() - x, m + r + tail, win_w - m - r - tail)
        else:
            # No room above (she's near the top of the screen): sit beside her head.
            win_w, win_h = bubble.width() + tail + 2 * m, bubble.height() + 2 * m
            y = _clamp(head.center().y() - win_h / 2, avail.top(), avail.bottom() - win_h + 1)
            if head.right() + win_w - 6 <= avail.right():
                self._tail = "left"
                x = head.right() - 6
            else:
                self._tail = "right"
                x = head.left() - win_w + 6
            x = _clamp(x, avail.left(), avail.right() - win_w + 1)
            self._tail_pos = _clamp(head.center().y() - y, m + r + tail, win_h - m - r - tail)
        self.setGeometry(int(round(x)), int(round(y)), int(win_w), int(win_h))

    def _bubble_rect(self) -> QRectF:
        bubble = self._bubble_size()
        m = self.MARGIN
        left = m + (self.TAIL if self._tail == "left" else 0)
        return QRectF(left, m, bubble.width(), bubble.height())

    def _path(self) -> QPainterPath:
        rect = self._bubble_rect()
        body = QPainterPath()
        body.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        t, half, p = self.TAIL, self.TAIL * 0.8, self._tail_pos
        tail = QPainterPath()
        if self._tail == "down":
            tail.moveTo(QPointF(p - half, rect.bottom() - 1))
            tail.lineTo(QPointF(p + half, rect.bottom() - 1))
            tail.lineTo(QPointF(p - 2, rect.bottom() + t))
        elif self._tail == "left":
            tail.moveTo(QPointF(rect.left() + 1, p - half))
            tail.lineTo(QPointF(rect.left() + 1, p + half))
            tail.lineTo(QPointF(rect.left() - t, p + 2))
        else:
            tail.moveTo(QPointF(rect.right() - 1, p - half))
            tail.lineTo(QPointF(rect.right() - 1, p + half))
            tail.lineTo(QPointF(rect.right() + t, p + 2))
        tail.closeSubpath()
        return body.united(tail).simplified()

    def paintEvent(self, _event) -> None:
        if self._opacity <= 0.01 or not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        path = self._path()

        painter.save()
        painter.translate(0, 2)
        painter.fillPath(path, QColor(45, 25, 70, 45))  # soft shadow
        painter.restore()
        painter.fillPath(path, self._fill)
        painter.setPen(QPen(self._accent, 1.6))
        painter.drawPath(path)

        rect = self._bubble_rect()
        painter.translate(rect.left() + self.PAD_X, rect.top() + self.PAD_Y)
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QPalette.ColorRole.Text, self._ink)
        if self._shown < self._total:
            hidden = QAbstractTextDocumentLayout.Selection()
            cursor = QTextCursor(self._doc)
            cursor.setPosition(self._shown)
            cursor.setPosition(self._total, QTextCursor.MoveMode.KeepAnchor)
            hidden.cursor = cursor
            invisible = QTextCharFormat()
            invisible.setForeground(QColor(0, 0, 0, 0))
            hidden.format = invisible
            context.selections = [hidden]
        self._doc.documentLayout().draw(painter, context)
        painter.end()

    def mousePressEvent(self, _event) -> None:
        self.fade_out()
