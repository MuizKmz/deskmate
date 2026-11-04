"""Make a "mouth closed" talk frame from a character's talk picture (mouth open).

While she speaks, DeskMate switches between talk_01 (mouth open) and talk_02 (mouth closed),
in time with her voice. The two pictures must be the same except for the mouth, so talk_02 is
made *from* talk_01:

1. Find the open mouth: the saturated pink/red blob in the lower middle of her face.
2. Paint it over with the surrounding skin (OpenCV inpainting).
3. Draw a small closed smile where it was, in the colour of the mouth's own outline.

    python tools/make_mouth.py characters/yuki                 -> characters/yuki/talk/talk_02.png
    python tools/make_mouth.py characters/yuki --preview out.png   (open | closed, zoomed on the face)
    python tools/make_mouth.py characters/yuki --box 275,311,36,23 (if the mouth isn't found by itself)

Works for painted / anime-style faces with a coloured open mouth. Pixel-art characters are
easier to draw by hand (Piko's are drawn in tools/draw_pixel_character.py).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def find_mouth(rgba: np.ndarray, head: dict) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the open mouth in a talk picture."""
    h, w = rgba.shape[:2]
    top = int(head.get("top", 0.05) * h)
    fx0, fx1 = int(0.30 * w), int(0.70 * w)
    fy0, fy1 = top + int(0.12 * h), top + int(0.34 * h)
    region = cv2.cvtColor(np.ascontiguousarray(rgba[fy0:fy1, fx0:fx1, :3]), cv2.COLOR_RGB2HSV).astype(int)
    hue, sat, val = region[..., 0], region[..., 1], region[..., 2]
    red = ((hue <= 12) | (hue >= 165)) & (sat >= 80) & (val >= 90) & (val <= 245)
    red &= rgba[fy0:fy1, fx0:fx1, 3] > 200
    count, labels, stats, _ = cv2.connectedComponentsWithStats(red.astype(np.uint8), 8)
    if count <= 1:
        raise SystemExit("No open mouth found. Give its box with --box x,y,w,h.")
    # The mouth: the biggest blob that's wider than it is tall-ish, nearest the middle.
    best = max(range(1, count), key=lambda i: stats[i, cv2.CC_STAT_AREA]
               - 0.5 * abs(stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] / 2 - (fx1 - fx0) / 2))
    x, y, bw, bh = (int(stats[best, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH,
                                                    cv2.CC_STAT_HEIGHT))
    return fx0 + x, fy0 + y, bw, bh


def close_mouth(rgba: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    out = rgba.copy()
    pad = max(3, int(0.22 * max(w, h)))
    # Everything in a slightly bigger ellipse around the mouth (lips, outline, teeth) goes.
    mask = np.zeros(rgba.shape[:2], np.uint8)
    cv2.ellipse(mask, (x + w // 2, y + h // 2), (w // 2 + pad, h // 2 + pad), 0, 0, 360, 255, -1)
    # The outline colour: the darkest pixels of the mouth area, before painting it over.
    area = rgba[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad, :3].reshape(-1, 3).astype(int)
    darkest = area[np.argsort(area.sum(axis=1))[: max(3, len(area) // 25)]]
    line = tuple(int(c) for c in darkest.mean(axis=0))
    bgr = cv2.cvtColor(np.ascontiguousarray(rgba[..., :3]), cv2.COLOR_RGB2BGR)
    filled = cv2.inpaint(bgr, mask, 7, cv2.INPAINT_TELEA)
    # A small closed smile across the upper part of where the mouth was.
    centre = (x + w // 2, y + int(h * 0.30))
    axes = (max(3, int(w * 0.30)), max(2, int(h * 0.22)))
    thickness = max(2, round(w / 16))
    cv2.ellipse(filled, centre, axes, 0, 20, 160, line[::-1], thickness, cv2.LINE_AA)
    out[..., :3] = cv2.cvtColor(filled, cv2.COLOR_BGR2RGB)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pack", type=Path, help="character folder, e.g. characters/yuki")
    parser.add_argument("--box", help="the open mouth's box in talk_01: x,y,w,h (found automatically if left out)")
    parser.add_argument("--preview", type=Path, help="save a zoomed before/after picture instead")
    args = parser.parse_args()

    source = args.pack / "talk" / "talk_01.png"
    rgba = np.array(Image.open(source).convert("RGBA"))
    meta = json.loads((args.pack / "character.json").read_text(encoding="utf-8"))
    box = tuple(int(v) for v in args.box.split(",")) if args.box else find_mouth(rgba, meta.get("head", {}))
    print("Open mouth at x=%d y=%d (%dx%d)" % box)
    closed = close_mouth(rgba, box)
    if args.preview:
        x, y, w, h = box
        m = 3 * max(w, h)
        crop = (max(0, x - m), max(0, y - m), x + w + m, y + h + m)
        before = Image.fromarray(rgba).crop(crop)
        after = Image.fromarray(closed).crop(crop)
        sheet = Image.new("RGBA", (before.width * 2 + 10, before.height), (40, 40, 50, 255))
        sheet.paste(before, (0, 0))
        sheet.paste(after, (before.width + 10, 0))
        sheet.resize((sheet.width * 3, sheet.height * 3), Image.LANCZOS).save(args.preview)
        print(f"Preview: {args.preview}")
        return 0
    target = args.pack / "talk" / "talk_02.png"
    Image.fromarray(closed).save(target, optimize=True)
    print(f"Saved {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
