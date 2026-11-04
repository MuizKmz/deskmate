"""Shared pieces for her glass windows (Settings, Setup, What's new).

* ``GlassWindow``: a frameless, rounded, dark-glass window in the character's colours, with her
  round face, a title and ✕ at the top. Drag it by the top bar; Esc closes it.
* ``Switch``: a small on/off switch (like the ones in her menu), as a real button.
* ``css`` / ``button_style``: colours as Qt style sheet text.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QKeyEvent, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from .menu_style import GLASS_BOTTOM, GLASS_TOP, INK, accent_of


def css(color: QColor, alpha: float | None = None) -> str:
    a = color.alphaF() if alpha is None else alpha
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {a:.2f})"


def button_style(accent: QColor, strong: bool = False) -> str:
    """A rounded glass button; ``strong`` is the main one (filled with her colour)."""
    if strong:
        return (f"QPushButton {{ color: white; background: {css(accent, 0.85)}; border: none; border-radius: 12px;"
                f" padding: 6px 16px; font-weight: 600; }} QPushButton:hover {{ background: {css(accent, 1.0)}; }}"
                " QPushButton:disabled { background: rgba(255,255,255,0.12); color: rgba(255,255,255,0.5); }")
    return (f"QPushButton {{ color: {INK.name()}; background: rgba(255,255,255,0.06);"
            f" border: 1px solid {css(accent, 0.5)}; border-radius: 12px; padding: 5px 14px; }}"
            f" QPushButton:hover {{ background: {css(accent, 0.3)}; }}"
            " QPushButton:disabled { color: rgba(244,238,250,0.4); border-color: rgba(255,255,255,0.15); }")


def label_style(size: float = 9.5, alpha: float = 1.0, bold: bool = False) -> str:
    return f"color: {css(INK, alpha)}; font-size: {size}pt;" + (" font-weight: 600;" if bold else "")


class Switch(QAbstractButton):
    """An on/off switch. ``toggled(bool)`` like a checkbox."""

    def __init__(self, accent: QColor, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._accent = QColor(accent)

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 3, 38, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._accent if self.isChecked() else QColor(255, 255, 255, 50))
        if not self.isEnabled():
            painter.setOpacity(0.4)
        painter.drawRoundedRect(track, 8, 8)
        knob = QRectF(21 if self.isChecked() else 1, 1, 20, 20).adjusted(1, 1, -1, -1)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(knob)


class GlassWindow(QWidget):
    """A dark-glass window with her face and a title on top. Put your content in ``self.body``."""

    def __init__(self, title: str, subtitle: str, theme: dict, avatar: QPixmap, smooth: bool = True,
                 size: QSize = QSize(560, 460)):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.resize(size)
        self.accent = accent_of(theme)
        self._drag_from: QPoint | None = None
        from .chatbox import _AvatarHolder
        from .menu_style import Header

        top = QWidget(self)
        bar = QHBoxLayout(top)
        bar.setContentsMargins(16, 12, 10, 8)
        face = QLabel()
        face.setFixedSize(40, 40)
        Header.set_avatar(_AvatarHolder(face, smooth), avatar, self.accent)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel(title)
        self.title.setStyleSheet(label_style(11.5, bold=True))
        self.subtitle = QLabel(subtitle)
        self.subtitle.setStyleSheet(label_style(8.5, 0.6))
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Close (Esc)")
        close.setStyleSheet(f"QToolButton {{ color: {css(INK, 0.7)}; font-size: 12pt; border: none; padding: 4px 8px;"
                            f" border-radius: 8px; }} QToolButton:hover {{ background: {css(self.accent, 0.3)}; }}")
        close.clicked.connect(self.close)
        bar.addWidget(face)
        bar.addLayout(titles, 1)
        bar.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self._top = top

        self.body = QWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top)
        layout.addWidget(self.body, 1)

    def open_near(self, body: QRect, available: QRect) -> None:
        """Beside her (left if there's room), fully on screen."""
        x = body.left() - self.width() - 10
        if x < available.left():
            x = body.right() + 10
        y = body.bottom() - self.height()
        x = max(available.left(), min(x, available.right() - self.width()))
        y = max(available.top(), min(y, available.bottom() - self.height()))
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._top.geometry().contains(event.position().toPoint()):
            self._drag_from = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_from = None

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0, GLASS_TOP)
        gradient.setColorAt(1, GLASS_BOTTOM)
        painter.fillPath(path, gradient)
        a = self.accent
        painter.setPen(QPen(QColor(a.red(), a.green(), a.blue(), 140), 1.2))
        painter.drawPath(path)
        line_y = self._top.geometry().bottom() + 1
        painter.setPen(QPen(QColor(a.red(), a.green(), a.blue(), 60), 1))
        painter.drawLine(QPoint(16, line_y), QPoint(int(rect.width()) - 16, line_y))
