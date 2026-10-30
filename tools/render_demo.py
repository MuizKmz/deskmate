"""Record a short demo video of the real DeskMate window (no screen needed).

The window is driven by a pretend clock, frame by frame, so every animation
(breathing, hop, crossfade, swing, landing, zzz, typing bubble) is exactly what
the app draws.

    python tools/render_demo.py --character yuki      -> docs/demo.mp4 (+ docs/demo.gif)
Needs ffmpeg on PATH.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtCore import QPoint, QPointF, QRect  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from deskmate.bubble import SpeechBubble  # noqa: E402
from deskmate.character import load_pack  # noqa: E402
from deskmate.companion import Companion, load_frames  # noqa: E402
from render_preview import wallpaper  # noqa: E402

FPS = 30


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", default="yuki")
    parser.add_argument("--out", type=Path, default=ROOT / "docs")
    args = parser.parse_args()
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found")
        return 1

    app = QApplication.instance() or QApplication([])
    pack = load_pack(ROOT / "characters" / args.character)
    lines = pack.lines
    clock = FakeClock()
    companion = Companion(pack, load_frames(pack), size="large", clock=clock)
    companion.place(None)
    companion.show()
    companion._timer.stop()  # we drive frames ourselves
    bubble = SpeechBubble(pack.theme)
    bubble._type_timer.stop()

    desk_w, desk_h = 960, 540
    desk = wallpaper(desk_w, desk_h)
    feet_local = companion.feet_global() - companion.pos()
    home = QPoint(desk_w - 40 - companion.width(), desk_h - 48 - feet_local.y() - 2)

    # (start, end, action) timeline in seconds
    script = [
        (0.0, "expr", "idle"),
        (1.2, "say", (lines.get("pet") or ["Ehehe~"])[0], "happy"),
        (1.2, "fx", "hop"),
        (3.6, "expr", "idle"),
        (4.2, "expr", "blush"),
        (6.0, "drag_start", None),
        (8.2, "drag_end", None),
        (9.0, "say", (lines.get("random") or ["What are you working on?"])[0], "talk"),
        (12.0, "expr", "sleepy"),
        (13.4, "expr", "sleep"),
        (16.5, "end", None),
    ]
    bubble_until = -1.0
    bubble_start = 0.0
    dragging = False
    drag_t0 = 0.0
    offset_x = 0.0
    events = list(script)

    with tempfile.TemporaryDirectory() as tmp:
        frame = 0
        while True:
            t = frame / FPS
            clock.t = 1000.0 + t
            while events and events[0][0] <= t:
                _, kind, value, *rest = events.pop(0)
                if kind == "end":
                    events.clear()
                    break
                if kind == "expr":
                    companion.set_expression(value)
                elif kind == "fx":
                    companion.play(value)
                elif kind == "say":
                    companion.set_expression(rest[0])
                    bubble.say(value, 30, companion.head_rect_global(), QRect(0, 0, 4000, 4000))
                    bubble._type_timer.stop()
                    bubble_start, bubble_until = t, t + 2.4 + 0.06 * len(value)
                elif kind == "drag_start":
                    dragging, drag_t0 = True, t
                    companion._dragging = True
                    companion._pivot = QPointF(0, -companion._H * 0.93)
                    companion.set_expression("surprised")
                elif kind == "drag_end":
                    dragging = False
                    companion._dragging = False
                    companion.set_expression("happy")
                    companion.play("land")
            if kind == "end" and not events:
                break

            # Drag: carry her left and back with an easing curve; feed the swing its speed.
            if dragging:
                p = (t - drag_t0) / 2.2
                new_x = -260 * math.sin(math.pi * min(1.0, p))
                companion._vx = (new_x - offset_x) * FPS
                offset_x = new_x
                lift = -40 * math.sin(math.pi * min(1.0, p))
            else:
                offset_x *= 0.0
                lift = 0.0
            companion._on_frame()

            canvas = QImage(desk)
            painter = QPainter(canvas)
            pos = home + QPoint(int(offset_x), int(lift))
            painter.drawImage(pos, companion.grab().toImage())
            if t < bubble_until:
                elapsed = t - bubble_start
                bubble._shown = min(bubble._total, int(elapsed / (SpeechBubble.TYPE_MS / 1000.0)))
                bubble._opacity = min(1.0, elapsed / 0.17, max(0.0, (bubble_until - t) / 0.17))
                head = companion.head_rect_global()
                shift = bubble.geometry().topLeft() - head.topLeft()
                head_on_canvas = pos + (head.topLeft() - companion.pos())
                painter.drawImage(head_on_canvas + shift, bubble.grab().toImage())
            painter.end()
            canvas.save(f"{tmp}/f{frame:04d}.png")
            frame += 1

        args.out.mkdir(parents=True, exist_ok=True)
        mp4 = args.out / "demo.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", f"{tmp}/f%04d.png",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(mp4)], check=True)
        gif = args.out / "demo.gif"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                        "fps=15,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160[p];"
                        "[b][p]paletteuse=dither=sierra2_4a", str(gif)], check=True)
    print(f"Wrote {mp4} ({frame} frames) and {gif}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
