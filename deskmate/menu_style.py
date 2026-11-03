"""Her right-click menu, dressed up: a dark glass card in the character's own colour.

Everything is drawn in code (icons, switches, the submenu arrow), so there are no image
files to ship and the colours follow the character (mauve for Yuki, teal for Piko...).
Underneath it's still a normal QMenu, so keyboard use, submenus and the tray menu all work.
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QProxyStyle, QStyle, QVBoxLayout, QWidget, QWidgetAction

INK = QColor("#F4EEFA")        # main text
MUTED = QColor(244, 238, 250, 140)
GLASS_TOP = QColor(44, 34, 60, 244)
GLASS_BOTTOM = QColor(24, 19, 34, 244)


def _rgba(color: QColor, alpha: float) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.2f})"


def accent_of(theme: dict) -> QColor:
    color = QColor(theme.get("accent", "#C9A0DC"))
    if color.lightnessF() < 0.55:  # keep it bright enough to glow on dark glass
        color = color.lighter(140)
    return color


# ------------------------------------------------------------------- icons
def _path(name: str) -> QPainterPath:
    """Line icons on a 24 x 24 grid."""
    p = QPainterPath()
    if name == "chat":
        p.addRoundedRect(QRectF(3, 4, 18, 13), 4, 4)
        p.moveTo(8, 17); p.lineTo(7, 21); p.lineTo(12, 17)
        p.moveTo(7.5, 9); p.lineTo(16.5, 9); p.moveTo(7.5, 12.5); p.lineTo(13.5, 12.5)
    elif name == "sparkle":
        for cx, cy, r in ((11, 12, 7.5), (18.5, 5.5, 2.6)):
            p.moveTo(cx, cy - r)
            p.quadTo(cx, cy, cx + r, cy); p.quadTo(cx, cy, cx, cy + r)
            p.quadTo(cx, cy, cx - r, cy); p.quadTo(cx, cy, cx, cy - r)
    elif name == "walk":
        p.addEllipse(QRectF(5, 4, 5, 8)); p.addEllipse(QRectF(5.6, 13.5, 3.8, 3.2))
        p.addEllipse(QRectF(14, 8, 5, 8)); p.addEllipse(QRectF(14.6, 17.5, 3.8, 3.2))
    elif name == "moon":
        p.moveTo(15, 3.5)
        p.cubicTo(8, 3.5, 4, 8.5, 4, 13); p.cubicTo(4, 18, 8, 21, 12.5, 21)
        p.cubicTo(16, 21, 18.5, 19.5, 20, 17)
        p.cubicTo(13.5, 18, 9.5, 13.5, 10, 9); p.cubicTo(10.3, 6.5, 12.3, 4.5, 15, 3.5)
    elif name == "sun":
        p.addEllipse(QRectF(8, 8, 8, 8))
        for i in range(8):
            a = i * math.pi / 4
            p.moveTo(12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a))
            p.lineTo(12 + 9 * math.cos(a), 12 + 9 * math.sin(a))
    elif name == "bell":
        p.moveTo(6, 17); p.lineTo(6, 11); p.cubicTo(6, 7, 8.5, 4.5, 12, 4.5)
        p.cubicTo(15.5, 4.5, 18, 7, 18, 11); p.lineTo(18, 17); p.lineTo(20, 18.5); p.lineTo(4, 18.5)
        p.lineTo(6, 17)
        p.moveTo(10, 21); p.quadTo(12, 22.5, 14, 21); p.moveTo(12, 2.5); p.lineTo(12, 4.5)
    elif name == "person":
        p.addEllipse(QRectF(8, 3.5, 8, 8))
        p.moveTo(4, 21); p.cubicTo(4.5, 16, 8, 14, 12, 14); p.cubicTo(16, 14, 19.5, 16, 20, 21)
    elif name == "size":
        p.moveTo(5, 19); p.lineTo(19, 5)
        p.moveTo(12, 5); p.lineTo(19, 5); p.lineTo(19, 12)
        p.moveTo(5, 12); p.lineTo(5, 19); p.lineTo(12, 19)
    elif name == "gear":
        for i in range(8):
            a = i * math.pi / 4
            p.moveTo(12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a))
            p.lineTo(12 + 9.2 * math.cos(a), 12 + 9.2 * math.sin(a))
        p.addEllipse(QRectF(5.5, 5.5, 13, 13)); p.addEllipse(QRectF(9.5, 9.5, 5, 5))
    elif name == "corner":
        p.moveTo(20, 13); p.lineTo(20, 20); p.lineTo(13, 20)
        p.moveTo(5, 5); p.lineTo(17, 17); p.moveTo(17, 10.5); p.lineTo(17, 17); p.lineTo(10.5, 17)
    elif name == "key":
        p.addEllipse(QRectF(3, 8, 8, 8))
        p.moveTo(11, 12); p.lineTo(21, 12); p.moveTo(17, 12); p.lineTo(17, 15.5); p.moveTo(20, 12); p.lineTo(20, 15)
    elif name == "eraser":
        p.moveTo(4, 6); p.lineTo(20, 6); p.moveTo(9.5, 6); p.lineTo(10, 3.5); p.lineTo(14, 3.5); p.lineTo(14.5, 6)
        p.moveTo(6, 6); p.lineTo(7.2, 20.5); p.lineTo(16.8, 20.5); p.lineTo(18, 6)
        p.moveTo(10, 10); p.lineTo(10.4, 17); p.moveTo(14, 10); p.lineTo(13.6, 17)
    elif name == "folder":
        p.moveTo(3, 18.5); p.lineTo(3, 6); p.lineTo(9, 6); p.lineTo(11, 8); p.lineTo(21, 8); p.lineTo(21, 18.5)
        p.closeSubpath()
    elif name in ("eye", "eye-off"):
        p.moveTo(2.5, 12); p.cubicTo(6, 6, 18, 6, 21.5, 12); p.cubicTo(18, 18, 6, 18, 2.5, 12)
        p.addEllipse(QRectF(9, 9, 6, 6))
        if name == "eye-off":
            p.moveTo(4, 4); p.lineTo(20, 20)
    elif name == "power":
        p.arcMoveTo(QRectF(4, 5, 16, 16), 60); p.arcTo(QRectF(4, 5, 16, 16), 60, 300)
        p.moveTo(12, 2.5); p.lineTo(12, 11)
    elif name == "dot":
        p.addEllipse(QRectF(8, 8, 8, 8))
    elif name == "settings":
        for y, x in ((7, 15), (12, 8), (17, 13)):
            p.moveTo(4, y); p.lineTo(20, y); p.addEllipse(QRectF(x - 2.2, y - 2.2, 4.4, 4.4))
    elif name == "plus":
        p.moveTo(12, 5); p.lineTo(12, 19); p.moveTo(5, 12); p.lineTo(19, 12)
    elif name == "clock":
        p.addEllipse(QRectF(3.5, 3.5, 17, 17)); p.moveTo(12, 7.5); p.lineTo(12, 12); p.lineTo(15.5, 14)
    return p


ICON = 20  # menu icon size (logical pixels)


class _MenuStyle(QProxyStyle):
    """Slightly bigger menu icons than Windows' default 16 px, so the switches are readable."""

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_SmallIconSize:
            return ICON
        return super().pixelMetric(metric, option, widget)


def icon(name: str, color: QColor, filled: bool = False) -> QIcon:
    result = QIcon()
    for dpr in (1.0, 1.25, 1.5, 2.0):
        pixmap = QPixmap(round(ICON * dpr), round(ICON * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(ICON / 24, ICON / 24)
        path = _path(name)
        if filled or name == "dot":
            painter.fillPath(path, color)
        else:
            painter.setPen(QPen(color, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)
        painter.end()
        result.addPixmap(pixmap)
    return result


def switch_icon(on: bool, accent: QColor) -> QIcon:
    """A little pill switch, used instead of a check mark for on/off options."""
    result = QIcon()
    for dpr in (1.0, 1.25, 1.5, 2.0):
        pixmap = QPixmap(round(ICON * dpr), round(ICON * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0.5, 4.5, ICON - 1, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent if on else QColor(255, 255, 255, 55))
        painter.drawRoundedRect(track, 5.5, 5.5)
        knob = QRectF(ICON - 10 if on else 2, 6, 8, 8)
        painter.setBrush(QColor("#FFFFFF") if on else QColor(255, 255, 255, 170))
        painter.drawEllipse(knob)
        painter.end()
        result.addPixmap(pixmap)
    return result


def _arrow_file(folder: Path, color: QColor) -> str:
    """The submenu arrow has to be an image file for Qt style sheets."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"menu-arrow-{color.name()[1:]}.png"
    if not path.exists():
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(color, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline([QPointF(8, 5), QPointF(13, 10), QPointF(8, 15)])
        painter.end()
        pixmap.save(str(path))
    return path.as_posix()


# ------------------------------------------------------------------- styling
def stylesheet(accent: QColor, arrow: str) -> str:
    return f"""
QMenu {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {_rgba(GLASS_TOP, GLASS_TOP.alphaF())},
                                stop:1 {_rgba(GLASS_BOTTOM, GLASS_BOTTOM.alphaF())});
    border: 1px solid {_rgba(accent, 0.55)};
    border-radius: 14px;
    padding: 7px 5px;
    color: {INK.name()};
    font-size: 10pt;
}}
QMenu::item {{
    padding: 6px 26px 6px 8px;
    margin: 1px 3px;
    border-radius: 8px;
    background: transparent;
}}
QMenu::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {_rgba(accent, 0.55)},
                                stop:0.65 {_rgba(accent, 0.22)}, stop:1 {_rgba(accent, 0.05)});
    color: #FFFFFF;
}}
QMenu::item:disabled {{ color: {_rgba(INK, 0.45)}; }}
QMenu::icon {{ padding-left: 10px; }}
QMenu::indicator {{ width: 0px; height: 0px; }}
QMenu::separator {{
    height: 1px;
    margin: 5px 14px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {_rgba(accent, 0.0)},
                                stop:0.5 {_rgba(accent, 0.45)}, stop:1 {_rgba(accent, 0.0)});
}}
QMenu::right-arrow {{ image: url("{arrow}"); width: 10px; height: 10px; margin-right: 8px; }}
QLabel {{ background: transparent; }}
"""


def style_menu(menu: QMenu, theme: dict, cache: Path) -> None:
    """Glass look + soft fade-in, for a menu and (when they're added later) its submenus."""
    accent = accent_of(theme)
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint
                        | Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    if not isinstance(menu.style(), _MenuStyle):
        style = _MenuStyle()
        style.setParent(menu)  # lives as long as the menu
        menu.setStyle(style)
    menu.setStyleSheet(stylesheet(accent, _arrow_file(cache, INK)))
    if not menu.property("deskmate_fade"):
        menu.setProperty("deskmate_fade", True)
        fade = QPropertyAnimation(menu, b"windowOpacity", menu)
        fade.setDuration(140)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        menu.aboutToShow.connect(fade.start)


def section(menu: QMenu, text: str, accent: QColor) -> QWidgetAction:
    """A small, quiet heading inside the menu (not clickable)."""
    label = QLabel(text.upper())
    label.setStyleSheet(f"color: {_rgba(accent, 0.85)}; font-size: 7.5pt; font-weight: 600;"
                        "letter-spacing: 1.5px; padding: 6px 16px 2px 16px; background: transparent;")
    action = QWidgetAction(menu)
    action.setDefaultWidget(label)
    action.setEnabled(False)
    menu.addAction(action)
    return action


class Header(QWidgetAction):
    """Her round face, name and how she's doing, at the top of the menu."""

    def __init__(self, menu: QMenu, avatar: QPixmap, name: str, accent: QColor, smooth: bool = True):
        self._smooth = smooth
        super().__init__(menu)
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        row = QHBoxLayout(box)
        row.setContentsMargins(12, 6, 18, 8)
        row.setSpacing(10)
        self.avatar = QLabel()
        self.avatar.setFixedSize(40, 40)
        self.set_avatar(avatar, accent)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.name = QLabel(name)
        self.name.setStyleSheet(f"color: {INK.name()}; font-size: 11.5pt; font-weight: 600;")
        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {_rgba(INK, 0.6)}; font-size: 8.5pt;")
        text.addWidget(self.name)
        text.addWidget(self.status)
        row.addWidget(self.avatar)
        row.addLayout(text, 1)
        self.setDefaultWidget(box)
        # Not disabled: Qt would draw her face greyed out. It just has nothing to do when clicked.
        menu.addAction(self)

    def set_avatar(self, avatar: QPixmap, accent: QColor) -> None:
        size, dpr = 40, 2.0
        out = QPixmap(int(size * dpr), int(size * dpr))
        out.setDevicePixelRatio(dpr)
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._smooth)  # pixel art stays crisp
        circle = QPainterPath()
        circle.addEllipse(QRectF(2, 2, size - 4, size - 4))
        tint = QColor(accent)
        tint.setAlpha(110)
        painter.fillPath(circle, QColor(58, 46, 78))
        painter.fillPath(circle, tint)
        painter.setClipPath(circle)
        if not avatar.isNull():
            painter.drawPixmap(QRectF(2, 2, size - 4, size - 4), avatar, QRectF(avatar.rect()))
        painter.setClipping(False)
        painter.setPen(QPen(accent, 2.0))
        painter.drawEllipse(QRectF(2, 2, size - 4, size - 4))
        painter.end()
        self.avatar.setPixmap(out)

    def set_text(self, name: str, status: str) -> None:
        self.name.setText(name)
        self.status.setText(status)
