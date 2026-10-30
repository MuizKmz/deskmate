"""Turn character pictures with a plain background into a clean DeskMate character pack.

What happens to each picture:
  1. The character is cut out of the background with an AI model made for anime art
     (rembg "isnet-anime"; runs offline after a one-time download).
  2. Stray specks are removed and the pale fringe around the edges is cleaned up,
     so there's no white halo on dark wallpapers.
  3. Every expression is lined up with the idle picture by matching her legs and shoes,
     so she doesn't jump or change size when her face changes.
  4. All pictures get the same canvas, with her feet at the bottom centre.
  5. The pack is written as characters/<name>/<expression>/<expression>_01.png
     plus a character.json.

Usage:
    pip install -r tools/requirements-tools.txt
    python tools/prepare_character.py SOURCE_FOLDER --name yuki

Name the source files after the expression (idle.png, happy.jpg, ...) or map them:
    python tools/prepare_character.py SOURCE --name yuki --map idle=a.png happy=b.png
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

EXPRESSIONS = ("idle", "happy", "sleepy", "sleep", "pouty", "surprised", "blush", "talk", "blink")
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}


# ----------------------------------------------------------------------------- input
def find_sources(folder: Path, mapping: list[str]) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for item in mapping:
        if "=" not in item:
            raise SystemExit(f"--map entries look like expression=file.png (got {item!r})")
        name, file = item.split("=", 1)
        path = (folder / file) if not Path(file).is_absolute() else Path(file)
        if not path.exists():
            raise SystemExit(f"{path} does not exist")
        sources[name.strip().lower()] = path
    if sources:
        return sources
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in IMAGE_TYPES:
            continue
        stem = path.stem.lower()
        for name in EXPRESSIONS:
            if name in stem and name not in sources:
                # "sleepy" also contains "sleep": prefer the longest matching name.
                longer = [n for n in EXPRESSIONS if n != name and name in n and n in stem]
                if not longer:
                    sources[name] = path
                    break
    return sources


def load_rgb(path: Path) -> np.ndarray:
    image = Image.open(path)
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(white, rgba)  # flatten any existing transparency onto white
    return np.asarray(image.convert("RGB"))


# ------------------------------------------------------------------------- cut out
def background_colour(rgb: np.ndarray) -> np.ndarray:
    border = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3),
                             rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
    return np.median(border, axis=0).astype(np.float32)


def cut_out(rgb: np.ndarray, session) -> np.ndarray:
    """Alpha matte in 0..1 from the anime segmentation model."""
    from rembg import remove

    mask = remove(Image.fromarray(rgb), session=session, only_mask=True)
    alpha = np.asarray(mask, dtype=np.float32) / 255.0
    if alpha.shape != rgb.shape[:2]:
        alpha = cv2.resize(alpha, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)
    return alpha


def clean_alpha(alpha: np.ndarray, bg_distance: np.ndarray) -> np.ndarray:
    """Remove specks, fill tiny holes, and trim leftover background at the edges."""
    solid = alpha > 0.5
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid.astype(np.uint8), connectivity=8)
    if count > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        keep = np.zeros(count, dtype=bool)
        keep[1:] = areas >= max(200, 0.01 * areas.max())
        kept = keep[labels] & (labels > 0)
    else:
        kept = solid
    near = cv2.dilate(kept.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    alpha = np.where(near & ~(solid & ~kept), alpha, 0.0)  # drop specks and faint noise far from her
    # Tiny enclosed holes (e.g. eye highlights the model wasn't sure about) become solid.
    holes = (alpha <= 0.5).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(holes, connectivity=4)
    h, w = alpha.shape
    x, y, bw, bh, area = (stats[:, i] for i in range(5))
    touches = (x == 0) | (y == 0) | (x + bw >= w) | (y + bh >= h)
    small = (~touches) & (area < 0.0004 * h * w)
    small[0] = False
    alpha = np.where(small[labels], 1.0, alpha)
    # Where the model is only half-sure but the pixel is plain background colour, it's background.
    soft = (alpha > 0) & (alpha < 0.6) & (bg_distance < 10)
    alpha[soft] = 0.0
    return np.clip(alpha, 0.0, 1.0)


def decontaminate(rgb: np.ndarray, alpha: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """Undo the background colour mixed into semi-transparent edge pixels (removes halos)."""
    colour = rgb.astype(np.float32)
    a = alpha[..., None]
    edge = (alpha > 0.03) & (alpha < 0.97)
    recovered = (colour - (1.0 - a) * bg) / np.maximum(a, 1e-3)
    colour[edge] = np.clip(recovered[edge], 0, 255)
    return colour


# ------------------------------------------------------------------------ alignment
def lower_body_mask(alpha: np.ndarray) -> np.ndarray:
    ys = np.where(alpha.max(axis=1) > 0.5)[0]
    top, bottom = ys.min(), ys.max()
    mask = (alpha > 0.5).astype(np.uint8) * 255
    mask[: int(top + 0.58 * (bottom - top))] = 0  # legs, skirt hem and shoes only
    return cv2.erode(mask, np.ones((7, 7), np.uint8))


def feet_anchor(alpha: np.ndarray) -> tuple[float, float]:
    """(x, y) of the point between her feet."""
    ys = np.where(alpha.max(axis=1) > 0.5)[0]
    top, bottom = ys.min(), ys.max()
    band = alpha[int(bottom - 0.06 * (bottom - top)): bottom + 1] > 0.5
    xs = np.where(band.any(axis=0))[0]
    return float((xs.min() + xs.max()) / 2.0), float(bottom)


def estimate_alignment(ref_rgb, ref_alpha, rgb, alpha, allow_scale: bool = False) -> tuple[np.ndarray, str]:
    """Transform that puts this picture's legs and shoes exactly over the idle picture's.

    By default it only *moves* the picture. AI-generated expressions usually keep
    the same size, but small drawing differences (e.g. narrower slippers) can fool
    a scale estimate and make her grow or shrink between faces. Use
    ``allow_scale=True`` for pictures that really were drawn at different sizes.
    """
    detector = cv2.AKAZE_create() if hasattr(cv2, "AKAZE_create") else cv2.ORB_create(5000)
    ref_gray = cv2.cvtColor(ref_rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    kp_ref, des_ref = detector.detectAndCompute(ref_gray, lower_body_mask(ref_alpha))
    kp, des = detector.detectAndCompute(gray, lower_body_mask(alpha))
    if des is not None and des_ref is not None and len(kp) >= 8 and len(kp_ref) >= 8:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        pairs = matcher.knnMatch(des, des_ref, k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.78 * p[1].distance]
        if len(good) >= 10:
            src = np.float32([kp[m.queryIdx].pt for m in good])
            dst = np.float32([kp_ref[m.trainIdx].pt for m in good])
            matrix, inliers = cv2.estimateAffinePartial2D(
                src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0, maxIters=8000, confidence=0.999
            )
            if matrix is not None and inliers is not None:
                scale = math.hypot(matrix[0, 0], matrix[1, 0])
                angle = math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))
                keep = inliers.ravel().astype(bool)
                count = int(keep.sum())
                if count >= 10 and 0.85 <= scale <= 1.15 and abs(angle) <= 4.0:
                    if allow_scale:
                        return matrix, f"matched legs & shoes ({count} points, scale {scale:.3f}, {angle:+.2f} deg)"
                    dx, dy = np.median(dst[keep] - src[keep], axis=0)
                    if abs(dx) <= 60 and abs(dy) <= 60:
                        return (np.float32([[1, 0, dx], [0, 1, dy]]),
                                f"matched legs & shoes ({count} points), moved {dx:+.1f}, {dy:+.1f} px")
    # Fallback: put the feet in the same spot, no scaling.
    (fx, fy), (rx, ry) = feet_anchor(alpha), feet_anchor(ref_alpha)
    return np.float32([[1, 0, rx - fx], [0, 1, ry - fy]]), "feet-only fallback"


def warp(colour: np.ndarray, alpha: np.ndarray, matrix: np.ndarray, size: tuple[int, int]):
    """Warp with premultiplied alpha so edges don't pick up dark or light fringes."""
    stack = np.dstack([colour * alpha[..., None], alpha])
    out = cv2.warpAffine(stack, matrix, size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    out_alpha = np.clip(out[..., 3], 0, 1)
    out_colour = np.where(out_alpha[..., None] > 1e-4, out[..., :3] / np.maximum(out_alpha[..., None], 1e-4), 0)
    return np.clip(out_colour, 0, 255), out_alpha


def feet_error(reference: np.ndarray, alpha: np.ndarray) -> float:
    """How far (in pixels) her feet are from where they stand in the idle picture."""
    (rx, ry), (x, y) = feet_anchor(reference), feet_anchor(alpha)
    return math.hypot(x - rx, y - ry)


# ---------------------------------------------------------------------------- output
def resize_premultiplied(colour, alpha, size):
    stack = np.dstack([colour * alpha[..., None], alpha])
    out = cv2.resize(stack, size, interpolation=cv2.INTER_AREA)
    out_alpha = np.clip(out[..., 3], 0, 1)
    out_colour = np.where(out_alpha[..., None] > 1e-4, out[..., :3] / np.maximum(out_alpha[..., None], 1e-4), 0)
    return np.clip(out_colour, 0, 255), out_alpha


def to_rgba8(colour, alpha) -> Image.Image:
    a8 = np.round(alpha * 255).astype(np.uint8)
    rgb8 = np.round(colour).astype(np.uint8)
    rgb8[a8 == 0] = 0
    return Image.fromarray(np.dstack([rgb8, a8]), "RGBA")


def head_metrics(alpha: np.ndarray) -> dict:
    ys = np.where(alpha.max(axis=1) > 0.5)[0]
    top, bottom = int(ys.min()), int(ys.max())
    height = bottom - top
    band = alpha[top: top + int(0.3 * height)] > 0.5
    xs = np.where(band.any(axis=0))[0]
    h, w = alpha.shape
    return {
        "x": round(float((xs.min() + xs.max()) / 2.0 / w), 4),
        "y": round(float((top + 0.19 * height) / h), 4),
        "top": round(float(top / h), 4),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="folder with the original pictures")
    parser.add_argument("--name", required=True, help="character id, e.g. yuki")
    parser.add_argument("--display-name", help="name shown in the app (default: --name, capitalised)")
    parser.add_argument("--out", type=Path, help="characters folder (default: ../characters next to this tool)")
    parser.add_argument("--map", nargs="*", default=[], help="expression=file pairs")
    parser.add_argument("--height", type=int, default=1024, help="height of the output canvas in pixels")
    parser.add_argument("--meta", type=Path, help="character.json to start from (lines, theme, ...)")
    parser.add_argument("--allow-scale", action="store_true",
                        help="also fix size differences (only if the pictures really differ in size)")
    args = parser.parse_args(argv)

    sources = find_sources(args.source, args.map)
    if "idle" not in sources:
        print("Need an idle picture (name a file idle.png or pass --map idle=FILE)", file=sys.stderr)
        return 1
    print("Pictures:", ", ".join(f"{k}={v.name}" for k, v in sources.items()))

    from rembg import new_session

    session = new_session("isnet-anime")
    cut: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for name, path in sources.items():
        rgb = load_rgb(path)
        bg = background_colour(rgb)
        distance = np.linalg.norm(rgb.astype(np.float32) - bg, axis=2)
        alpha = clean_alpha(cut_out(rgb, session), distance)
        cut[name] = (rgb, decontaminate(rgb, alpha, bg), alpha)
        print(f"  cut out {name:10} ({rgb.shape[1]}x{rgb.shape[0]})")

    ref_rgb, ref_colour, ref_alpha = cut["idle"]
    size = (ref_rgb.shape[1], ref_rgb.shape[0])
    aligned = {"idle": (ref_colour, ref_alpha)}
    report = {}
    for name, (rgb, colour, alpha) in cut.items():
        if name == "idle":
            continue
        matrix, how = estimate_alignment(ref_rgb, ref_alpha, rgb, alpha, allow_scale=args.allow_scale)
        before = feet_error(ref_alpha, alpha)
        colour_w, alpha_w = warp(colour, alpha, matrix, size)
        after = feet_error(ref_alpha, alpha_w)
        if after > before + 1.0:  # alignment made it worse: keep the original placement
            colour_w, alpha_w, how = colour, alpha, "kept as is"
            after = before
        aligned[name] = (colour_w, alpha_w)
        report[name] = f"{how}; feet off by {before:.1f} px -> {after:.1f} px"
        print(f"  aligned {name:10} {report[name]}")

    # One shared canvas: wide enough for every pose, centred on her feet.
    union = np.zeros(ref_alpha.shape, dtype=bool)
    for _colour, alpha in aligned.values():
        union |= alpha > 0.02
    ys, xs = np.where(union)
    feet_x, feet_y = feet_anchor(ref_alpha)
    pad = int(0.012 * ref_alpha.shape[0])
    half = int(max(feet_x - xs.min(), xs.max() - feet_x)) + pad
    top = max(0, int(ys.min()) - pad)
    bottom = min(ref_alpha.shape[0], int(max(ys.max(), feet_y)) + max(2, pad // 3))
    left = int(round(feet_x)) - half
    width, height = 2 * half, bottom - top
    scale = min(1.0, args.height / height)
    out_size = (max(1, round(width * scale)), max(1, round(height * scale)))

    out_root = (args.out or Path(__file__).resolve().parent.parent / "characters") / args.name
    out_root.mkdir(parents=True, exist_ok=True)
    head = None
    for name, (colour, alpha) in aligned.items():
        canvas_c = np.zeros((height, width, 3), np.float32)
        canvas_a = np.zeros((height, width), np.float32)
        x0, x1 = max(0, left), min(alpha.shape[1], left + width)
        canvas_c[:, x0 - left: x1 - left] = colour[top:bottom, x0:x1]
        canvas_a[:, x0 - left: x1 - left] = alpha[top:bottom, x0:x1]
        colour_s, alpha_s = resize_premultiplied(canvas_c, canvas_a, out_size)
        folder = out_root / name
        folder.mkdir(exist_ok=True)
        to_rgba8(colour_s, alpha_s).save(folder / f"{name}_01.png", optimize=True)
        if name == "idle":
            head = head_metrics(alpha_s)
            face = to_rgba8(colour_s, alpha_s)
            r = int((head["y"] - head["top"]) * out_size[1] * 1.3)
            cx, cy = int(head["x"] * out_size[0]), int(head["y"] * out_size[1])
            face.crop((cx - r, cy - r, cx + r, cy + r)).resize((256, 256), Image.LANCZOS).save(out_root / "preview.png")

    meta = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta else {}
    meta.setdefault("name", args.display_name or args.name.title())
    meta["head"] = head
    meta["image_size"] = list(out_size)
    meta["alignment"] = report
    (out_root / "character.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Done: {out_root}  ({out_size[0]}x{out_size[1]} per picture)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
