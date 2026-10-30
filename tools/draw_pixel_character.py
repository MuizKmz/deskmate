"""Draws Piko, DeskMate's built-in pixel-art character, entirely in code.

Every expression shares the same body; only the face changes. Each sprite is
32 x 44 "art pixels", saved 20x bigger with sharp (nearest-neighbour) scaling.

    python tools/draw_pixel_character.py          -> characters/piko/
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

W, H, SCALE = 32, 44, 20

C = {
    "out": (43, 29, 46, 255),
    "hair": (72, 56, 120, 255),
    "hairL": (110, 92, 170, 255),
    "skin": (255, 226, 206, 255),
    "blush": (255, 150, 170, 255),
    "hood": (63, 182, 168, 255),
    "hoodS": (40, 135, 126, 255),
    "phone": (255, 111, 145, 255),
    "white": (255, 255, 255, 255),
    "mouth": (190, 70, 90, 255),
    "tongue": (240, 120, 140, 255),
    "legs": (62, 52, 84, 255),
    "shoe": (250, 250, 255, 255),
}


def px(d: ImageDraw.ImageDraw, points, colour: str) -> None:
    for x, y in points:
        d.point((x, y), fill=C[colour])


def body() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # legs and shoes
    for x0 in (11, 17):
        d.rectangle((x0, 34, x0 + 3, 40), fill=C["out"])
        d.rectangle((x0 + 1, 34, x0 + 2, 40), fill=C["legs"])
    for x0 in (9, 16):
        d.rounded_rectangle((x0, 39, x0 + 6, 43), 2, fill=C["out"])
        d.rounded_rectangle((x0 + 1, 40, x0 + 5, 42), 1, fill=C["shoe"])
    px(d, [(11, 41), (13, 41), (18, 41), (20, 41)], "phone")  # little pink laces
    # hoodie
    d.rounded_rectangle((7, 24, 24, 36), 4, fill=C["out"])
    d.rounded_rectangle((8, 25, 23, 35), 3, fill=C["hood"])
    d.line((15, 26, 15, 35), fill=C["hoodS"])
    d.line((16, 26, 16, 35), fill=C["hoodS"])
    d.line((9, 33, 22, 33), fill=C["hoodS"])  # pocket line
    px(d, [(13, 27), (18, 27), (13, 28), (18, 28), (13, 29), (18, 29)], "white")  # strings
    # head
    d.ellipse((5, 3, 26, 25), fill=C["out"])
    d.ellipse((6, 4, 25, 24), fill=C["skin"])
    # hair: cap, side locks, fringe, shine, ahoge
    d.chord((5, 2, 26, 22), 180, 360, fill=C["out"])
    d.chord((6, 3, 25, 21), 180, 360, fill=C["hair"])
    d.rectangle((6, 11, 8, 21), fill=C["hair"])
    d.rectangle((23, 11, 25, 21), fill=C["hair"])
    for x, h in [(9, 14), (11, 13), (13, 14), (16, 13), (18, 14), (20, 13), (22, 14)]:
        d.line((x, 11, x, h), fill=C["hair"])
        d.line((x + 1, 11, x + 1, h - 1), fill=C["hair"])
    d.line((10, 6, 14, 5), fill=C["hairL"])
    px(d, [(16, 1), (17, 0), (18, 0), (15, 2), (16, 2)], "hair")
    # headphones
    d.arc((4, 2, 27, 24), 200, 340, fill=C["phone"], width=2)
    d.rounded_rectangle((3, 13, 6, 19), 1, fill=C["phone"])
    d.rounded_rectangle((25, 13, 28, 19), 1, fill=C["phone"])
    return img, d


def eyes_open(d, big=False, look=0):
    for ex in (10, 19):
        if big:
            d.rectangle((ex - 1, 14, ex + 2, 18), fill=C["out"])
            px(d, [(ex - 1 + max(0, look), 14), (ex + max(0, look), 15)], "white")
        else:
            d.rectangle((ex, 15, ex + 2, 18), fill=C["out"])
            px(d, [(ex + (1 if look > 0 else 0), 15), (ex + 1 + (1 if look > 0 else 0), 16)], "white")


def cheeks(d, strong=False):
    px(d, [(8, 19), (9, 19), (22, 19), (23, 19)], "blush")
    if strong:
        px(d, [(8, 20), (9, 20), (10, 20), (21, 20), (22, 20), (23, 20), (10, 19), (21, 19)], "blush")


FACES = {}


def face(name):
    def register(fn):
        FACES[name] = fn
        return fn
    return register


@face("idle")
def _idle(d):
    eyes_open(d)
    px(d, [(15, 21), (16, 21)], "mouth")
    cheeks(d)


@face("happy")
def _happy(d):
    for ex in (11, 19):
        px(d, [(ex, 17), (ex + 1, 16), (ex + 2, 17)], "out")
    d.rectangle((14, 20, 17, 21), fill=C["mouth"])
    px(d, [(15, 21), (16, 21)], "tongue")
    cheeks(d, strong=True)


@face("sleepy")
def _sleepy(d):
    for ex in (10, 19):
        d.line((ex, 16, ex + 2, 16), fill=C["out"])
        d.rectangle((ex, 17, ex + 2, 18), fill=C["out"])
    d.rectangle((15, 20, 16, 22), fill=C["mouth"])  # small yawn
    cheeks(d)


@face("sleep")
def _sleep(d):
    for ex in (10, 19):
        px(d, [(ex, 17), (ex + 1, 18), (ex + 2, 17)], "out")
    px(d, [(15, 21), (16, 21)], "mouth")
    cheeks(d)


@face("pouty")
def _pouty(d):
    eyes_open(d)
    px(d, [(9, 13), (10, 13), (11, 14), (22, 13), (21, 13), (20, 14)], "out")  # cross brows
    px(d, [(14, 22), (15, 21), (16, 21), (17, 22)], "mouth")
    cheeks(d, strong=True)


@face("surprised")
def _surprised(d):
    eyes_open(d, big=True)
    d.ellipse((14, 20, 17, 23), fill=C["mouth"])
    cheeks(d)


@face("blush")
def _blush(d):
    eyes_open(d, look=1)
    px(d, [(15, 21), (16, 21), (17, 20)], "mouth")
    cheeks(d, strong=True)


@face("talk")
def _talk(d):
    eyes_open(d)
    d.rectangle((14, 20, 17, 22), fill=C["mouth"])
    px(d, [(15, 22), (16, 22)], "tongue")
    cheeks(d)


LINES = {
    "intro": ["Hi, I'm Piko! Drag me anywhere, click to pat me, right\u2011click for options~"],
    "pet": ["Hehe~", "*happy beep*", "Pat pat!"],
    "too_much": ["Hey! My headphones!"],
    "random": ["Lo-fi beats and you. Nice.", "Need a break? I'll guard the desktop.", "*hums along*"],
    "wake": ["Wha—? Oh, you're back!"],
    "ignored": ["Hmph... 45 minutes and not a single pat?"],
}


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "characters" / "piko"
    for name, draw_face in FACES.items():
        img, d = body()
        draw_face(d)
        (out / name).mkdir(parents=True, exist_ok=True)
        img.resize((W * SCALE, H * SCALE), Image.NEAREST).save(out / name / f"{name}_01.png", optimize=True)
    meta = {
        "name": "Piko",
        "author": "DeskMate",
        "version": "1.0",
        "personality": "cheerful, a bit dramatic, music-loving",
        "smooth": False,
        "head": {"x": round(15.5 / W, 4), "y": round(14 / H, 4), "top": round(1 / H, 4)},
        "theme": {"bubble": "#FFFFFF", "accent": "#3FB6A8", "text": "#2B1D2E"},
        "lines": LINES,
    }
    (out / "character.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Piko drawn into {out}")


if __name__ == "__main__":
    main()
