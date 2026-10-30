"""Record a demo video of the real DeskMate window (no screen needed).

The window runs on a pretend 1280x672 screen with a pretend clock, frame by
frame, so everything you see (breathing, blinking, hops, walking, being thrown,
falling, landing, the typing bubble, zzz) is exactly what the app does.

    python tools/render_demo.py --character yuki      -> docs/demo.mp4 + docs/demo.gif
Needs ffmpeg on PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCREEN_W, SCREEN_H, TASKBAR = 1280, 672, 48
_cfg = Path(tempfile.gettempdir()) / "deskmate_demo_screen.json"
_cfg.write_text(json.dumps({"screens": [{"name": "demo", "x": 0, "y": 0, "width": SCREEN_W, "height": SCREEN_H,
                                          "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))
os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={_cfg}"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from deskmate.brain import speech_duration  # noqa: E402
from deskmate.bubble import SpeechBubble  # noqa: E402
from deskmate.character import load_pack  # noqa: E402
from deskmate.companion import Companion, load_frames  # noqa: E402
from render_preview import wallpaper  # noqa: E402

FPS = 30


class FakeClock:
    t = 1000.0

    def __call__(self):
        return self.t


def mouse(widget, kind, global_point, buttons):
    local = QPointF(widget.mapFromGlobal(global_point))
    button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    event = QMouseEvent(kind, local, QPointF(global_point), button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


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
    companion = Companion(pack, load_frames(pack), size="large", clock=clock, rng=random.Random(4))
    companion.place(None)
    companion.show()
    companion._timer.stop()
    companion._next_blink = clock.t + 1.2  # make sure a blink shows up early
    bubble = SpeechBubble(pack.theme)
    bubble._type_timer.stop()
    desk = wallpaper(SCREEN_W, SCREEN_H + TASKBAR)

    state = {"bubble_start": 0.0, "bubble_until": -1.0, "drag": None}

    def say(text, face):
        companion.set_expression(face)
        bubble.say(text, 60, companion.head_rect_global(), companion.available_rect())
        bubble._type_timer.stop()
        state["bubble_start"] = clock.t
        state["bubble_until"] = clock.t + speech_duration(text) + len(text) * SpeechBubble.TYPE_MS / 1000

    def pick(key, fallback):
        return (lines.get(key) or [fallback])[0]

    timeline = [
        (2.6, lambda: (companion.play("hop"), say(pick("pet", "Ehehe~"), "happy"))),
        (5.4, lambda: companion.set_expression("idle")),
        (5.6, lambda: companion.start_wander(target_x=companion.pos().x() - 330)),
        (11.0, lambda: state.update(drag=("start", clock.t))),
        (16.8, lambda: say(pick("random", "What are you working on?"), "talk")),
        (20.6, lambda: companion.set_expression("sleepy")),
        (22.0, lambda: companion.set_expression("sleep")),
    ]
    end = 25.5
    landed_said = {"done": False}

    def on_landed(impact):
        if impact > 1200 and not landed_said["done"]:
            landed_said["done"] = True
            say(pick("fall", "Oof!"), "surprised")
    companion.landed.connect(on_landed)

    with tempfile.TemporaryDirectory() as tmp:
        frame = 0
        grab_at = None
        while True:
            t = frame / FPS
            if t > end:
                break
            clock.t = 1000.0 + t
            while timeline and timeline[0][0] <= t:
                timeline.pop(0)[1]()

            # Scripted drag: grab her, lift her up and to the left, then fling her to the right.
            if state["drag"]:
                phase, t0 = state["drag"]
                elapsed = clock.t - t0
                if phase == "start":
                    grab_at = companion.mapToGlobal(companion._sprite_rect_local().center())
                    mouse(companion, QEvent.Type.MouseButtonPress, grab_at, Qt.MouseButton.LeftButton)
                    state["drag"] = ("carry", clock.t)
                    companion.set_expression("surprised")
                elif phase == "carry":
                    p = min(1.0, elapsed / 1.6)
                    point = grab_at + QPoint(int(-120 * p), int(-330 * p * (2 - p)))
                    mouse(companion, QEvent.Type.MouseMove, point, Qt.MouseButton.LeftButton)
                    if p >= 1.0:
                        state["drag"] = ("fling", clock.t)
                elif phase == "fling":
                    p = min(1.0, elapsed / 0.18)
                    start = grab_at + QPoint(-120, -330)
                    point = start + QPoint(int(260 * p), int(-40 * p))
                    mouse(companion, QEvent.Type.MouseMove, point, Qt.MouseButton.LeftButton)
                    if p >= 1.0:
                        mouse(companion, QEvent.Type.MouseButtonRelease, point, Qt.MouseButton.NoButton)
                        companion.set_expression("surprised")
                        state["drag"] = None

            companion._on_frame()
            if bubble.isVisible() and clock.t < state["bubble_until"]:
                bubble.reposition(companion.head_rect_global(), companion.available_rect())

            canvas = QImage(desk)
            painter = QPainter(canvas)
            painter.drawImage(companion.pos(), companion.grab().toImage())
            if clock.t < state["bubble_until"]:
                elapsed = clock.t - state["bubble_start"]
                bubble._shown = min(bubble._total, int(elapsed / (SpeechBubble.TYPE_MS / 1000.0)))
                bubble._opacity = min(1.0, elapsed / 0.17, max(0.0, (state["bubble_until"] - clock.t) / 0.17))
                painter.drawImage(bubble.geometry().topLeft(), bubble.grab().toImage())
            elif clock.t >= state["bubble_until"] > 0 and companion.expression in ("happy", "talk", "surprised") \
                    and not companion.falling and state["drag"] is None and t < 20:
                companion.set_expression("idle")
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
