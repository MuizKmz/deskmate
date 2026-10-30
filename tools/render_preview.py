"""Render README pictures using the real DeskMate windows (no screen needed).

    python tools/render_preview.py --character yuki
        -> docs/preview.png      her on a pretend desktop, talking
        -> docs/expressions.png  every expression side by side
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from deskmate.bubble import SpeechBubble  # noqa: E402
from deskmate.character import load_pack  # noqa: E402
from deskmate.companion import Companion, load_frames  # noqa: E402

ORDER = ("idle", "happy", "talk", "blush", "surprised", "pouty", "sleepy", "sleep")


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def wallpaper(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    sky = QLinearGradient(0, 0, width, height)
    sky.setColorAt(0.0, QColor("#2B2350"))
    sky.setColorAt(0.55, QColor("#5B4A8C"))
    sky.setColorAt(1.0, QColor("#E7A9C9"))
    p.fillRect(image.rect(), sky)
    glow = QRadialGradient(QPointF(width * 0.18, height * 0.22), height * 0.35)
    glow.setColorAt(0.0, QColor(255, 244, 214, 150))
    glow.setColorAt(1.0, QColor(255, 244, 214, 0))
    p.fillRect(image.rect(), glow)
    p.setBrush(QColor("#FFF6DD"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(width * 0.18, height * 0.22), 34, 34)  # moon

    # a pretend code editor window
    win = QRectF(width * 0.08, height * 0.36, width * 0.52, height * 0.5)
    p.setBrush(QColor(0, 0, 0, 70))
    p.drawRoundedRect(win.translated(0, 8), 12, 12)
    p.setBrush(QColor("#1E1E2E"))
    p.drawRoundedRect(win, 12, 12)
    p.setBrush(QColor("#2A2A3C"))
    p.drawRoundedRect(QRectF(win.left(), win.top(), win.width(), 34), 12, 12)
    p.drawRect(QRectF(win.left(), win.top() + 20, win.width(), 14))
    for i, colour in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        p.setBrush(QColor(colour))
        p.drawEllipse(QPointF(win.left() + 20 + i * 18, win.top() + 17), 6, 6)
    font = QFont("monospace")
    font.setPixelSize(15)
    p.setFont(font)
    code = [
        ("#C792EA", "def"), ("#82AAFF", " build_deskmate"), ("#C3CEE3", "():"),
    ]
    lines = [
        [("#C792EA", "def "), ("#82AAFF", "build_deskmate"), ("#C3CEE3", "():")],
        [("#C3CEE3", "    pet = "), ("#FFCB6B", "Companion"), ("#C3CEE3", "(yuki)")],
        [("#C3CEE3", "    pet."), ("#82AAFF", "show"), ("#C3CEE3", "()")],
        [("#676E95", "    # she lives here now ~")],
        [("#C792EA", "    return "), ("#F78C6C", "True")],
    ]
    del code
    y = win.top() + 70
    for line in lines:
        x = win.left() + 26
        for colour, text in line:
            p.setPen(QColor(colour))
            p.drawText(QPointF(x, y), text)
            x += p.fontMetrics().horizontalAdvance(text)
        y += 26

    # taskbar
    bar = QRectF(0, height - 48, width, 48)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(24, 20, 40, 225))
    p.drawRect(bar)
    for i in range(5):
        p.setBrush(QColor(255, 255, 255, 40 if i else 90))
        p.drawRoundedRect(QRectF(width / 2 - 110 + i * 46, height - 40, 32, 32), 7, 7)
    p.setPen(QColor(255, 255, 255, 200))
    font = QFont()
    font.setPixelSize(13)
    p.setFont(font)
    p.drawText(QRectF(width - 90, height - 48, 80, 48), Qt.AlignmentFlag.AlignCenter, "12:34")
    p.end()
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", default="yuki")
    parser.add_argument("--say", default=None)
    parser.add_argument("--out", type=Path, default=ROOT / "docs")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    pack = load_pack(ROOT / "characters" / args.character)
    if not pack.ok:
        print("\n".join(str(i) for i in pack.issues))
        return 1
    frames = load_frames(pack)
    args.out.mkdir(parents=True, exist_ok=True)

    # 1) every expression side by side
    companion = Companion(pack, frames, size="large")
    companion.place(None)
    companion.show()
    shots = []
    for name in ORDER:
        if not pack.has(name):
            continue
        companion.set_expression(name)
        spin(0.3)
        shots.append((name, companion.grab().toImage()))
    cell_w, cell_h = shots[0][1].width(), shots[0][1].height() + 34
    sheet = QImage(cell_w * len(shots), cell_h, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#1F1B33"))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont()
    font.setPixelSize(16)
    font.setBold(True)
    p.setFont(font)
    for i, (name, shot) in enumerate(shots):
        p.drawImage(i * cell_w, 0, shot)
        p.setPen(QColor("#E9D8F5"))
        p.drawText(QRectF(i * cell_w, cell_h - 34, cell_w, 30), Qt.AlignmentFlag.AlignCenter, name)
    p.end()
    sheet.save(str(args.out / "expressions.png"))

    # 2) on a pretend desktop, talking
    desk_w, desk_h = 1280, 720
    desk = wallpaper(desk_w, desk_h)
    companion.set_expression("talk")
    spin(0.3)
    sprite = companion.grab().toImage()
    feet_local = companion.feet_global() - companion.pos()
    x = int(desk_w - 70 - feet_local.x() - sprite.width() / 2 + feet_local.x())
    x = desk_w - 60 - sprite.width()
    y = desk_h - 48 - feet_local.y() - 2
    head = companion.head_rect_global().translated(-companion.pos()).translated(x, y)

    bubble = SpeechBubble(pack.theme)
    line = args.say or (pack.lines.get("intro") or ["Hi!"])[0]
    from PySide6.QtCore import QRect

    bubble.say(line, 30, head, QRect(0, 0, desk_w, desk_h - 48))
    spin(0.3 + len(line) * SpeechBubble.TYPE_MS / 1000.0 + 0.3)
    bubble_img = bubble.grab().toImage()

    p = QPainter(desk)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.drawImage(x, y, sprite)
    p.drawImage(bubble.geometry().topLeft(), bubble_img)
    p.end()
    desk.save(str(args.out / "preview.png"))
    print(f"Wrote {args.out / 'preview.png'} and {args.out / 'expressions.png'}")
    bubble.dismiss()
    companion.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
