"""Outfits: little accessories drawn on her head (in code, so they fit every character).

Each one is drawn relative to her head circle (``head``: centre and radius, from the
character pack), so it sits right on Yuki, on Piko, and on any character you make. On pixel-art
characters it's drawn small and blown up without smoothing, so it's pixel art too.

Some are unlocked by your bond level; the seasonal ones come out by themselves on the day
(a party hat on your birthday, a Santa hat at Christmas, a witch hat on Halloween).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen


@dataclass(frozen=True)
class Outfit:
    key: str
    name: str
    emoji: str
    level: int = 1          # bond level that unlocks it (0 = seasonal only)


OUTFITS = [
    Outfit("bow", "Ribbon bow", "🎀", 1),
    Outfit("flower", "Flower clip", "🌸", 2),
    Outfit("cat_ears", "Cat ears", "🐱", 3),
    Outfit("headphones", "Headphones", "🎧", 4),
    Outfit("beret", "Beret", "🎨", 5),
    Outfit("crown", "Little crown", "👑", 6),
    Outfit("party_hat", "Party hat", "🥳", 0),
    Outfit("santa_hat", "Santa hat", "🎅", 0),
    Outfit("witch_hat", "Witch hat", "🧙", 0),
]
BY_KEY = {o.key: o for o in OUTFITS}


def unlocked(level: int) -> list[Outfit]:
    return [o for o in OUTFITS if 0 < o.level <= level]


def seasonal(day: date, birthday: str = "") -> str | None:
    """The outfit for today, if today calls for one."""
    if birthday and day.strftime("%m-%d") == birthday:
        return "party_hat"
    if day.month == 12 and 20 <= day.day <= 26:
        return "santa_hat"
    if day.month == 10 and day.day == 31:
        return "witch_hat"
    return None


def newly_unlocked(level: int) -> list[Outfit]:
    return [o for o in OUTFITS if o.level == level]


# ------------------------------------------------------------------- drawing
def draw(painter: QPainter, key: str, center: QPointF, radius: float, accent: QColor, mirrored: bool = False,
         pixel: float = 0.0, smooth: bool = True) -> None:
    """Draw outfit ``key`` on a head at ``center`` with ``radius`` (in the painter's coordinates).
    ``pixel``: for pixel art, the size of one of her pixels on screen (0 = smooth drawing)."""
    if key not in BY_KEY:
        return
    if pixel:
        _draw_pixelated(painter, key, center, radius, accent, mirrored, pixel)
        return
    painter.save()
    painter.translate(center)
    if mirrored:
        painter.scale(-1, 1)
    painter.scale(radius / 100.0, radius / 100.0)  # everything below is drawn for a head of radius 100
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, smooth)
    _SHAPES[key](painter, QColor(accent))
    painter.restore()


def _draw_pixelated(painter: QPainter, key: str, center: QPointF, radius: float, accent: QColor,
                    mirrored: bool, pixel: float) -> None:
    """Pixel-art characters get pixel-art accessories: drawn tiny (one dot per pixel of hers, no
    smoothing), then scaled up without smoothing, so they're on her pixel grid."""
    cells = max(12, round(3.2 * radius / pixel))  # her pixels across the area accessories can reach
    size = cells * pixel
    image = QImage(cells, cells, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    small = QPainter(image)
    draw(small, key, QPointF(cells / 2, cells / 2), radius / pixel, accent, mirrored, smooth=False)
    small.end()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.drawImage(QRectF(center.x() - size / 2, center.y() - size / 2, size, size), image)
    painter.restore()


def _outline(painter: QPainter, width: float = 5.0) -> None:
    pen = QPen(QColor(40, 28, 48, 210), width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)


def _bow(p: QPainter, accent: QColor) -> None:
    color = QColor("#F06A9B")
    p.translate(62, -78)
    p.rotate(18)
    _outline(p)
    p.setBrush(color)
    for side in (-1, 1):
        wing = QPainterPath(QPointF(0, 0))
        wing.cubicTo(QPointF(side * 22, -34), QPointF(side * 52, -26), QPointF(side * 46, 0))
        wing.cubicTo(QPointF(side * 52, 26), QPointF(side * 22, 34), QPointF(0, 0))
        p.drawPath(wing)
    p.setBrush(color.darker(115))
    p.drawEllipse(QPointF(0, 0), 11, 11)


def _flower(p: QPainter, accent: QColor) -> None:
    p.translate(-74, -62)
    _outline(p, 4)
    p.setBrush(QColor("#FFC1DA"))
    for i in range(5):
        angle = i * 72
        p.save()
        p.rotate(angle)
        p.drawEllipse(QPointF(0, -17), 12, 15)
        p.restore()
    p.setBrush(QColor("#FFD866"))
    p.drawEllipse(QPointF(0, 0), 9, 9)


def _cat_ears(p: QPainter, accent: QColor) -> None:
    base = QColor(accent).lighter(115)
    inner = QColor("#FFB8D2")
    for side in (-1, 1):
        p.save()
        p.translate(side * 52, -86)
        p.rotate(side * 18)
        _outline(p)
        p.setBrush(base)
        ear = QPainterPath(QPointF(-28, 18))
        ear.lineTo(QPointF(0, -42))
        ear.lineTo(QPointF(28, 18))
        ear.closeSubpath()
        p.drawPath(ear)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(inner)
        inside = QPainterPath(QPointF(-14, 12))
        inside.lineTo(QPointF(0, -22))
        inside.lineTo(QPointF(14, 12))
        inside.closeSubpath()
        p.drawPath(inside)
        p.restore()


def _headphones(p: QPainter, accent: QColor) -> None:
    band = QPen(QColor(48, 40, 60), 13)
    band.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(band)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(-104, -112, 208, 200), 20 * 16, 140 * 16)
    p.setPen(QPen(QColor(accent).lighter(130), 5))
    p.drawArc(QRectF(-104, -112, 208, 200), 40 * 16, 100 * 16)
    _outline(p)
    for side in (-1, 1):
        p.setBrush(QColor(48, 40, 60))
        p.drawRoundedRect(QRectF(side * 98 - 17, -20, 34, 52), 14, 14)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(side * 98 - 10, -12, 20, 36), 9, 9)


def _beret(p: QPainter, accent: QColor) -> None:
    p.translate(8, -80)
    p.rotate(-12)
    _outline(p)
    p.setBrush(QColor("#C2414F"))
    p.drawEllipse(QRectF(-78, -30, 156, 52))
    p.setBrush(QColor("#A8343F"))
    p.drawRoundedRect(QRectF(-4, -42, 8, 16), 3, 3)


def _crown(p: QPainter, accent: QColor) -> None:
    p.translate(0, -104)
    _outline(p, 4)
    p.setBrush(QColor("#FFD24A"))
    crown = QPainterPath(QPointF(-40, 14))
    for x, y in ((-46, -22), (-22, -2), (0, -34), (22, -2), (46, -22), (40, 14)):
        crown.lineTo(QPointF(x, y))
    crown.closeSubpath()
    p.drawPath(crown)
    p.setBrush(QColor("#F06A9B"))
    p.drawEllipse(QPointF(0, 2), 6, 6)
    p.setBrush(QColor("#7FD3F7"))
    for x in (-24, 24):
        p.drawEllipse(QPointF(x, 6), 4.5, 4.5)


def _party_hat(p: QPainter, accent: QColor) -> None:
    p.translate(30, -96)
    p.rotate(14)
    _outline(p)
    cone = QPainterPath(QPointF(-36, 20))
    cone.lineTo(QPointF(0, -76))
    cone.lineTo(QPointF(36, 20))
    cone.closeSubpath()
    p.setBrush(QColor(accent).lighter(120))
    p.drawPath(cone)
    p.save()
    p.setClipPath(cone)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFD866"))
    for y in (-50, -22, 6):
        stripe = QPainterPath(QPointF(-60, y))
        stripe.lineTo(QPointF(60, y - 18))
        stripe.lineTo(QPointF(60, y - 8))
        stripe.lineTo(QPointF(-60, y + 10))
        stripe.closeSubpath()
        p.drawPath(stripe)
    p.restore()
    _outline(p, 4)
    p.setBrush(QColor("#F06A9B"))
    p.drawEllipse(QPointF(0, -80), 11, 11)


def _santa_hat(p: QPainter, accent: QColor) -> None:
    p.translate(6, -92)
    p.rotate(-8)
    _outline(p)
    p.setBrush(QColor("#D9344A"))
    hat = QPainterPath(QPointF(-70, 18))
    hat.cubicTo(QPointF(-50, -60), QPointF(30, -80), QPointF(84, -30))
    hat.lineTo(QPointF(70, 18))
    hat.closeSubpath()
    p.drawPath(hat)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(QRectF(-80, 8, 160, 26), 13, 13)
    p.drawEllipse(QPointF(88, -30), 15, 15)


def _witch_hat(p: QPainter, accent: QColor) -> None:
    p.translate(0, -92)
    p.rotate(-6)
    _outline(p)
    p.setBrush(QColor(52, 36, 70))
    p.drawEllipse(QRectF(-94, 0, 188, 34))
    hat = QPainterPath(QPointF(-48, 16))
    hat.cubicTo(QPointF(-30, -40), QPointF(-6, -88), QPointF(40, -96))
    hat.cubicTo(QPointF(16, -70), QPointF(30, -20), QPointF(48, 16))
    hat.closeSubpath()
    p.drawPath(hat)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#F2A541"))
    p.drawRect(QRectF(-44, 2, 90, 12))


_SHAPES = {"bow": _bow, "flower": _flower, "cat_ears": _cat_ears, "headphones": _headphones, "beret": _beret,
           "crown": _crown, "party_hat": _party_hat, "santa_hat": _santa_hat, "witch_hat": _witch_hat}
assert set(_SHAPES) == set(BY_KEY)
