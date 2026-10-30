"""Add a new animation (e.g. a walk cycle) to an existing character pack.

The pictures can be any size, on a plain background. Each one is cut out, scaled
so she is exactly as tall as in her idle picture, stood on the same floor line,
and moved sideways so her head stays where it is in idle (a steady head is what
stops a walk cycle from wobbling).

    python tools/add_frames.py characters/yuki walk walk1.png walk2.png walk3.png walk4.png --fps 7

Writes characters/yuki/walk/walk_01.png ... and the speed into character.json.
Draw walk frames facing RIGHT: DeskMate flips them when she walks left.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_character import (  # noqa: E402
    background_colour, clean_alpha, cut_out, decontaminate, load_rgb, resize_premultiplied, to_rgba8,
)


def body_box(alpha: np.ndarray) -> tuple[int, int]:
    """Top of her hair and the bottom of her lowest foot (rows)."""
    rows = np.where((alpha > 0.5).sum(axis=1) > 2)[0]
    return int(rows.min()), int(rows.max())


def head_centre_x(alpha: np.ndarray, top: int, height: int) -> float:
    """Middle of her head, measured on the top 12% of her body (hair only, no ponytail tip)."""
    band = alpha[top: top + max(4, int(0.12 * height))] > 0.5
    cols = np.where(band.any(axis=0))[0]
    return (cols.min() + cols.max()) / 2.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack", type=Path, help="character folder, e.g. characters/yuki")
    parser.add_argument("animation", help="animation name, e.g. walk")
    parser.add_argument("pictures", nargs="+", type=Path, help="frames in order")
    parser.add_argument("--fps", type=float, help="frames per second for this animation")
    parser.add_argument("--preview", type=Path, help="also save a strip of idle + all frames here")
    args = parser.parse_args(argv)

    idle = np.asarray(Image.open(args.pack / "idle" / "idle_01.png").convert("RGBA"), np.float32) / 255.0
    canvas_h, canvas_w = idle.shape[:2]
    i_top, i_bottom = body_box(idle[..., 3])
    i_height = i_bottom - i_top
    i_head = head_centre_x(idle[..., 3], i_top, i_height)

    from rembg import new_session

    session = new_session("isnet-anime")
    out_dir = args.pack / args.animation
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob(f"{args.animation}_*.png"):
        old.unlink()
    frames = []
    for n, path in enumerate(args.pictures, 1):
        rgb = load_rgb(path)
        bg = background_colour(rgb)
        distance = np.linalg.norm(rgb.astype(np.float32) - bg, axis=2)
        alpha = clean_alpha(cut_out(rgb, session), distance)
        colour = decontaminate(rgb, alpha, bg)
        top, bottom = body_box(alpha)
        scale = i_height / (bottom - top)
        size = (max(1, round(rgb.shape[1] * scale)), max(1, round(rgb.shape[0] * scale)))
        colour_s, alpha_s = resize_premultiplied(colour, alpha, size)
        top_s, bottom_s = body_box(alpha_s)
        dx = int(round(i_head - head_centre_x(alpha_s, top_s, bottom_s - top_s)))
        dy = i_bottom - bottom_s
        canvas_c = np.zeros((canvas_h, canvas_w, 3), np.float32)
        canvas_a = np.zeros((canvas_h, canvas_w), np.float32)
        ys0, xs0 = max(0, dy), max(0, dx)
        ys1, xs1 = min(canvas_h, dy + size[1]), min(canvas_w, dx + size[0])
        canvas_c[ys0:ys1, xs0:xs1] = colour_s[ys0 - dy: ys1 - dy, xs0 - dx: xs1 - dx]
        canvas_a[ys0:ys1, xs0:xs1] = alpha_s[ys0 - dy: ys1 - dy, xs0 - dx: xs1 - dx]
        lost = alpha_s.sum() - canvas_a.sum()
        image = to_rgba8(canvas_c, canvas_a)
        image.save(out_dir / f"{args.animation}_{n:02d}.png", optimize=True)
        frames.append(image)
        warn = f"  (!) {lost / alpha_s.sum():.1%} of her is outside the canvas" if lost > 0.002 * alpha_s.sum() else ""
        print(f"  {path.name}: scaled x{scale:.3f}, moved {dx:+d},{dy:+d}{warn}")

    meta_path = args.pack / "character.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if args.fps:
        meta.setdefault("animations", {}).setdefault(args.animation, {})["fps"] = args.fps
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.preview:
        strip = Image.new("RGBA", (canvas_w * (len(frames) + 1), canvas_h), (236, 230, 244, 255))
        strip.alpha_composite(Image.fromarray((idle * 255).astype(np.uint8)), (0, 0))
        for k, frame in enumerate(frames, 1):
            strip.alpha_composite(frame, (canvas_w * k, 0))
        strip.convert("RGB").save(args.preview)
    print(f"Done: {len(frames)} frames in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
