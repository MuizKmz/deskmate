"""Make a blink frame (eyes closed) from a character's idle picture.

1. Find the open eyes in idle by their iris colour, and grow that into a mask
   covering lashes, whites and highlights (everything that isn't skin).
2. Paint the eyes over with the surrounding skin (OpenCV inpainting).
3. Take the closed eyelids from her *sleep* picture (same artist, same style),
   straighten them to the idle head, and lay them where her eyes were.

    python tools/make_blink.py characters/yuki             -> characters/yuki/blink/blink_01.png
    python tools/make_blink.py characters/yuki --preview out.png

Works for front-facing characters with coloured irises and a sleep picture.
For anything else, draw or generate a blink picture instead.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def face_box(alpha: np.ndarray, head: dict) -> tuple[int, int, int, int]:
    h, w = alpha.shape
    top = int(head["top"] * h)
    return int(0.15 * w), top + int(0.10 * h), int(0.85 * w), top + int(0.31 * h)


def find_irises(rgb: np.ndarray, alpha: np.ndarray, head: dict) -> list[tuple[int, int, int, int]]:
    """Boxes (x0, y0, x1, y1) of the two irises, left to right."""
    h, w = alpha.shape
    fx0, fy0, fx1, fy1 = face_box(alpha, head)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(int)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    region = np.zeros_like(alpha, dtype=bool)
    region[fy0:fy1, fx0:fx1] = True
    iris = (sat > 45) & (val > 40) & (alpha > 200) & region & ~((hue <= 25) | (hue >= 170))
    iris = cv2.morphologyEx(iris.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _labels, stats, _ = cv2.connectedComponentsWithStats(iris, connectivity=8)
    blobs = sorted((stats[i] for i in range(1, count) if stats[i][cv2.CC_STAT_AREA] > 0.00012 * h * w),
                   key=lambda s: -s[cv2.CC_STAT_AREA])[:2]
    if len(blobs) < 2:
        raise SystemExit("Couldn't find two eyes by colour; draw a blink picture instead.")
    return sorted((int(x), int(y), int(x + bw), int(y + bh)) for x, y, bw, bh, _ in blobs)


def skin_colour(rgb: np.ndarray, irises) -> np.ndarray:
    """Plain face skin: the strip between the eyes (no blush, no lashes)."""
    (lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1) = irises
    gap = rx0 - lx1
    xa, xb = int(lx1 + 0.3 * gap), int(rx0 - 0.3 * gap)
    ya, yb = int(min(ly0, ry0)), int(max(ly1, ry1))
    patch = rgb[ya:yb, xa:max(xa + 1, xb)].reshape(-1, 3).astype(np.float32)
    # ignore hair strands crossing the strip: keep the most common (skin) colours
    luma = patch @ np.float32([0.299, 0.587, 0.114])
    keep = np.abs(luma - np.median(luma)) < 12
    return np.median(patch[keep] if keep.any() else patch, axis=0)


def eye_mask(rgb: np.ndarray, alpha: np.ndarray, irises) -> np.ndarray:
    """Everything around each iris that isn't skin: lashes, whites, highlights."""
    h, w = alpha.shape
    mask = np.zeros((h, w), np.uint8)
    centre = (irises[0][0] + irises[1][2]) / 2
    skin = skin_colour(rgb, irises)
    for box in irises:
        x0, y0, x1, y1 = box
        iw, ih = x1 - x0, y1 - y0
        outer_left = (x0 + x1) / 2 < centre
        wx0 = int(x0 - (0.95 if outer_left else 0.45) * iw)
        wx1 = int(x1 + (0.45 if outer_left else 0.95) * iw)
        wy0, wy1 = int(y0 - 0.6 * ih), int(y1 + 0.2 * ih)
        window = rgb[wy0:wy1, wx0:wx1].astype(np.float32)
        different = np.linalg.norm(window - skin, axis=2) > 26
        hsv = cv2.cvtColor(rgb[wy0:wy1, wx0:wx1], cv2.COLOR_RGB2HSV).astype(int)
        irisish = (hsv[..., 1] > 25) & ~((hsv[..., 0] <= 25) | (hsv[..., 0] >= 170))  # pale iris edges too
        different |= irisish
        seed = np.zeros_like(different)
        seed[y0 - wy0: y1 - wy0, x0 - wx0: x1 - wx0] = True
        count, labels = cv2.connectedComponents((different | seed).astype(np.uint8), connectivity=8)
        touching = set(np.unique(labels[seed & (labels > 0)]))
        part = np.isin(labels, list(touching))
        # keep it compact around the eye (drops long hair strands that happen to touch)
        ellipse = np.zeros_like(part, dtype=np.uint8)
        cv2.ellipse(ellipse, ((x0 + x1) // 2 - wx0 + (-1 if outer_left else 1) * int(0.12 * iw), (y0 + y1) // 2 - wy0 - int(0.05 * ih)),
                    (int(1.05 * iw), int(1.05 * ih)), 0, 0, 360, 1, -1)
        part &= ellipse.astype(bool)
        mask[wy0:wy1, wx0:wx1] |= part.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return cv2.dilate(mask, np.ones((7, 7), np.uint8))


def fill_with_skin(rgb: np.ndarray, mask: np.ndarray, irises) -> np.ndarray:
    """Replace the masked eyes with a smooth skin gradient fitted to the cheek around them.

    Fitting a gentle curve to clean skin pixels (instead of smearing whatever is at
    the edge) avoids picking up hair strands and lash ends.
    """
    out = rgb.astype(np.float32).copy()
    h, w = mask.shape
    skin = skin_colour(rgb, irises)
    count, labels = cv2.connectedComponents((mask > 0).astype(np.uint8))
    for i in range(1, count):
        part = labels == i
        ys, xs = np.where(part)
        y0, y1, x0, x1 = max(0, ys.min() - 16), min(h, ys.max() + 17), max(0, xs.min() - 16), min(w, xs.max() + 17)
        local = part[y0:y1, x0:x1]
        ring = cv2.dilate(local.astype(np.uint8), np.ones((21, 21), np.uint8)).astype(bool) & ~local
        colours = out[y0:y1, x0:x1]
        clean = ring & (np.linalg.norm(colours - skin, axis=2) < 34)  # skin and soft blush, not hair or lashes
        if clean.sum() < 30:
            out[y0:y1, x0:x1][local] = skin
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        nx, ny = (xx - xx.mean()) / 50.0, (yy - yy.mean()) / 50.0
        basis = np.stack([np.ones_like(nx), nx, ny], axis=-1)  # a gentle flat gradient
        coeffs, *_ = np.linalg.lstsq(basis[clean], colours[clean], rcond=None)
        model = np.clip(basis @ coeffs, 0, 255)
        feather = cv2.GaussianBlur(local.astype(np.float32), (0, 0), 3.5)[..., None]
        feather = np.clip(np.maximum(feather * 1.6, local[..., None].astype(np.float32)), 0, 1)
        out[y0:y1, x0:x1] = model * feather + colours * (1 - feather)
    return out


def closed_lids(sleep_rgba: np.ndarray, head: dict) -> list[tuple[np.ndarray, tuple[float, float], float]]:
    """Cut the two closed eyelids out of the sleep picture.

    Returns [(rgba_patch, centre_xy, angle_deg_between_lids)] left to right.
    """
    rgb = sleep_rgba[..., :3]
    alpha = sleep_rgba[..., 3]
    h, w = alpha.shape
    fx0, fy0, fx1, fy1 = face_box(alpha, head)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(int)
    dark = (hsv[..., 2] < 120) & (alpha > 200)
    region = np.zeros_like(dark)
    region[fy0:fy1, fx0:fx1] = True
    dark &= region
    # Lids are thick strokes: an opening removes thin hair outlines.
    thick = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    count, labels, stats, cents = cv2.connectedComponentsWithStats(thick, connectivity=8)
    blobs = sorted((i for i in range(1, count) if stats[i][cv2.CC_STAT_AREA] > 0.00006 * h * w),
                   key=lambda i: -stats[i][cv2.CC_STAT_AREA])[:2]
    if len(blobs) < 2:
        raise SystemExit("Couldn't find closed eyes in the sleep picture.")
    blobs = sorted(blobs, key=lambda i: cents[i][0])
    (lx, ly), (rx, ry) = cents[blobs[0]], cents[blobs[1]]
    tilt = math.degrees(math.atan2(ry - ly, rx - lx))
    lids = []
    luma = rgb.astype(np.float32) @ np.float32([0.299, 0.587, 0.114])
    for i in blobs:
        x, y, bw, bh, _ = stats[i]
        pad = int(0.35 * max(bw, bh))
        X0, Y0, X1, Y1 = max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)
        near = cv2.dilate((labels[Y0:Y1, X0:X1] == i).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        patch_luma = luma[Y0:Y1, X0:X1]
        skin = np.percentile(patch_luma[~near], 60) if (~near).any() else 235.0
        ink = np.percentile(patch_luma[near], 5)
        a = np.clip((skin - patch_luma) / max(1.0, skin - ink), 0, 1) * near
        a = cv2.GaussianBlur(a.astype(np.float32), (0, 0), 0.6)
        colour = np.median(rgb[Y0:Y1, X0:X1][near & (patch_luma < (skin + ink) / 2)], axis=0)
        patch = np.zeros((Y1 - Y0, X1 - X0, 4), np.float32)
        patch[..., :3] = colour
        patch[..., 3] = a
        lids.append((patch, (float(cents[i][0] - X0), float(cents[i][1] - Y0)), tilt))
    return lids


def make_blink(idle: np.ndarray, sleep: np.ndarray, head: dict) -> np.ndarray:
    rgb = np.ascontiguousarray(idle[..., :3])
    alpha = idle[..., 3]
    irises = find_irises(rgb, alpha, head)
    mask = eye_mask(rgb, alpha, irises)

    out = fill_with_skin(rgb, mask, irises)

    idle_tilt = math.degrees(math.atan2(
        (irises[1][1] + irises[1][3]) / 2 - (irises[0][1] + irises[0][3]) / 2,
        (irises[1][0] + irises[1][2]) / 2 - (irises[0][0] + irises[0][2]) / 2,
    ))
    for (patch, (pcx, pcy), sleep_tilt), (x0, y0, x1, y1) in zip(closed_lids(sleep, head), irises):
        iw, ih = x1 - x0, y1 - y0
        ph, pw = patch.shape[:2]
        scale = 1.0  # same artist and size, so keep the lid as drawn
        rot = cv2.getRotationMatrix2D((pcx, pcy), sleep_tilt - idle_tilt, scale)
        target_x, target_y = (x0 + x1) / 2, y0 + 0.62 * ih  # closed lids sit low, like in her sleep picture
        rot[0, 2] += target_x - pcx
        rot[1, 2] += target_y - pcy
        premult = np.dstack([patch[..., :3] * patch[..., 3:4], patch[..., 3]])
        placed = cv2.warpAffine(premult, rot, (alpha.shape[1], alpha.shape[0]), flags=cv2.INTER_CUBIC,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        a = np.clip(placed[..., 3:4], 0, 1)
        colour = np.where(a > 1e-4, placed[..., :3] / np.maximum(a, 1e-4), 0)
        out = colour * a + out * (1 - a)

    result = np.dstack([np.clip(out, 0, 255).astype(np.uint8), alpha])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack", type=Path)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    meta = json.loads((args.pack / "character.json").read_text(encoding="utf-8"))
    head = meta.get("head") or {"x": 0.5, "y": 0.2, "top": 0.02}
    idle = np.asarray(Image.open(args.pack / "idle" / "idle_01.png").convert("RGBA"))
    sleep = np.asarray(Image.open(args.pack / "sleep" / "sleep_01.png").convert("RGBA"))
    blink = make_blink(idle, sleep, head)
    target = args.preview or (args.pack / "blink" / "blink_01.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(blink, "RGBA").save(target, optimize=True)
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
