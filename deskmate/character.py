"""Character packs: a folder of PNG images plus a ``character.json``.

::

    characters/yuki/
        character.json
        idle/idle_01.png          <- the only required image
        happy/happy_01.png        <- optional; anything missing falls back to idle
        sleep/sleep_01.png
        ...

One image in a folder = a still pose. Several images (``walk_01.png``,
``walk_02.png`` ...) = an animation, played in number order.

This module only reads files and checks them; it does not need Qt, so the
checks can run from the command line (``python -m deskmate --check``).
"""

from __future__ import annotations

import json
import logging
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

REQUIRED = ("idle",)
PHASE1 = ("happy", "sleepy", "sleep", "pouty", "surprised", "blush", "talk")
KNOWN = ("idle", "blink", *PHASE1, "walk", "drag", "fall")
ONE_SHOT = {"blink", "fall"}  # animations that play once instead of looping
DEFAULT_FPS = 6.0
MAX_LINE_LENGTH = 160

DEFAULT_THEME = {"bubble": "#FFFFFF", "accent": "#C9A0DC", "text": "#3B2F4A"}

# Used for any line group a pack doesn't define.
DEFAULT_LINES: dict[str, list[str]] = {
    "intro": ["Hi! I'll keep you company. Drag me anywhere, click to pet me, right\u2011click for options."],
    "greet_morning": ["Good morning! Let's have a nice day."],
    "greet_afternoon": ["Good afternoon!"],
    "greet_evening": ["Good evening~"],
    "greet_night": ["You're up late..."],
    "pet": ["Ehehe~", "Hehe, that tickles!", "Mm~ thank you."],
    "too_much": ["Hey! That's too much~"],
    "drag": ["Whoa—!", "Where are we going?"],
    "drop": ["Here is nice.", "Okay, I'll stay here."],
    "fall": ["Oof!", "Ouch... I'm okay!"],
    "wander": ["Let's go over here~"],
    "sleepy": ["*yawn*..."],
    "goodnight": ["Good night..."],
    "wake": ["Mmh...? Oh! You're back!"],
    "ignored": ["Hmph... you forgot about me again?"],
    "forgive": ["Hmph... fine. I forgive you."],
    "late": ["It's really late... don't stay up too long, okay?"],
    "water": ["Drink some water, okay?"],
    "break": ["You've been working for a long time. Stretch a little?"],
    "random": ["What are you working on?", "I'm right here if you need me."],
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_DIGITS = re.compile(r"(\d+)")


@dataclass
class Issue:
    level: str  # "error" | "warning" | "info"
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.message}"


@dataclass
class Animation:
    name: str
    frames: list[Path]
    fps: float = DEFAULT_FPS
    loop: bool = True


@dataclass
class CharacterPack:
    id: str
    root: Path
    name: str
    meta: dict
    animations: dict[str, Animation]
    lines: dict[str, list[str]]
    theme: dict[str, str]
    frame_size: tuple[int, int] | None
    head: tuple[float, float, float]  # head centre x, centre y, top y (0-1, relative to the frame)
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    def has(self, name: str) -> bool:
        return name in self.animations

    def resolve(self, name: str) -> str:
        """The animation to actually play for ``name`` (missing ones fall back to idle)."""
        if name in self.animations:
            return name
        if name == "sleep" and "sleepy" in self.animations:
            return "sleepy"
        return "idle"


# --------------------------------------------------------------------------- PNG helpers
def png_info(path: Path) -> tuple[int, int, bool]:
    """Return (width, height, has_alpha) by reading the PNG header only."""
    with open(path, "rb") as handle:
        if handle.read(8) != _PNG_SIGNATURE:
            raise ValueError("not a PNG file")
        width = height = None
        has_alpha = False
        while True:
            header = handle.read(8)
            if len(header) < 8:
                break
            length, chunk_type = struct.unpack(">I4s", header)
            if chunk_type == b"IHDR":
                data = handle.read(length)
                handle.seek(4, 1)  # CRC
                width, height, _depth, color_type = struct.unpack(">IIBB", data[:10])
                has_alpha = color_type in (4, 6)  # grey+alpha, RGBA
                continue
            if chunk_type == b"tRNS":
                has_alpha = True
            if chunk_type in (b"IDAT", b"IEND"):
                break
            handle.seek(length + 4, 1)
    if width is None or height is None or width == 0 or height == 0:
        raise ValueError("PNG header is missing or empty")
    return width, height, has_alpha


def _natural_key(path: Path):
    return [int(part) if part.isdigit() else part.lower() for part in _DIGITS.split(path.name)]


def _number(value, default: float, low: float, high: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
        return float(value)
    return default


# --------------------------------------------------------------------------- loading
def available_packs(characters_dir: Path) -> list[Path]:
    if not Path(characters_dir).is_dir():
        return []
    return sorted(
        p for p in Path(characters_dir).iterdir() if p.is_dir() and not p.name.startswith((".", "_"))
    )


def find_pack(characters_dir: Path, wanted: str) -> Path | None:
    """The wanted pack if it exists, otherwise the first one that has an idle image."""
    packs = available_packs(characters_dir)
    for pack in packs:
        if pack.name.lower() == str(wanted).lower():
            return pack
    for pack in packs:
        if (pack / "idle").is_dir():
            return pack
    return packs[0] if packs else None


def load_pack(root: Path) -> CharacterPack:
    root = Path(root)
    pack_id = root.name
    issues: list[Issue] = []

    if not root.is_dir():
        issues.append(Issue("error", f"Character folder not found: {root}"))
        return CharacterPack(pack_id, root, pack_id.title(), {}, {}, dict(DEFAULT_LINES),
                             dict(DEFAULT_THEME), None, (0.5, 0.2, 0.02), issues)

    meta = _read_meta(root, issues)
    name = meta["name"] if isinstance(meta.get("name"), str) and meta["name"].strip() else pack_id.title()
    default_fps = _number(meta.get("fps"), DEFAULT_FPS, 0.5, 60)
    overrides = meta.get("animations") if isinstance(meta.get("animations"), dict) else {}

    animations: dict[str, Animation] = {}
    sizes: dict[str, tuple[int, int]] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        anim_name = folder.name.lower()
        frames: list[Path] = []
        for file in sorted((p for p in folder.iterdir() if p.is_file()), key=_natural_key):
            if file.name.startswith(".") or file.name.lower() in ("thumbs.db", "desktop.ini"):
                continue
            label = f"{folder.name}/{file.name}"
            if file.suffix.lower() != ".png":
                issues.append(Issue("warning", f"{label}: not a PNG, ignored"))
                continue
            try:
                width, height, has_alpha = png_info(file)
            except (OSError, ValueError, struct.error) as exc:
                issues.append(Issue("error", f"{label}: can't be read ({exc})"))
                continue
            if not has_alpha:
                issues.append(Issue("warning", f"{label}: has no transparency, so a box will show around her"))
            sizes[label] = (width, height)
            frames.append(file)
        if not frames:
            continue
        if anim_name not in KNOWN:
            issues.append(Issue("info", f"{folder.name}/: not a standard animation name (loaded anyway)"))
        override = overrides.get(anim_name) if isinstance(overrides.get(anim_name), dict) else {}
        animations[anim_name] = Animation(
            anim_name,
            frames,
            fps=_number(override.get("fps"), default_fps, 0.5, 60),
            loop=bool(override.get("loop", anim_name not in ONE_SHOT)),
        )

    for required in REQUIRED:
        if required not in animations:
            issues.append(Issue("error", f"Missing {required}/{required}_01.png (the one image every character needs)"))

    frame_size = None
    if sizes:
        reference = next((key for key in sizes if key.startswith("idle/")), next(iter(sizes)))
        frame_size = sizes[reference]
        different = [key for key, size in sizes.items() if size != frame_size]
        if different:
            shown = ", ".join(different[:3]) + (" ..." if len(different) > 3 else "")
            issues.append(Issue(
                "warning",
                f"{len(different)} image(s) are not {frame_size[0]}x{frame_size[1]} like idle ({shown}); "
                "they'll be scaled to match but may look jumpy",
            ))

    if "idle" in animations:
        missing = [name for name in PHASE1 if name not in animations]
        if missing:
            issues.append(Issue("info", f"Not provided, idle is used instead: {', '.join(missing)}"))

    return CharacterPack(
        id=pack_id,
        root=root,
        name=name,
        meta=meta,
        animations=animations,
        lines=_read_lines(meta.get("lines"), issues),
        theme=_read_theme(meta.get("theme"), issues),
        frame_size=frame_size,
        head=_read_head(meta.get("head")),
        issues=issues,
    )


def _read_meta(root: Path, issues: list[Issue]) -> dict:
    path = root / "character.json"
    if not path.exists():
        issues.append(Issue("warning", "character.json is missing; using defaults"))
        return {}
    try:
        meta = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(meta, dict):
            raise ValueError("top level must be a JSON object")
        return meta
    except (OSError, ValueError) as exc:
        issues.append(Issue("warning", f"character.json can't be read ({exc}); using defaults"))
        return {}


def _read_lines(raw, issues: list[Issue]) -> dict[str, list[str]]:
    lines = {key: list(value) for key, value in DEFAULT_LINES.items()}
    if raw is None:
        return lines
    if not isinstance(raw, dict):
        issues.append(Issue("warning", "character.json 'lines' must be an object; using default lines"))
        return lines
    for key, value in raw.items():
        if not isinstance(value, list):
            issues.append(Issue("warning", f"lines.{key} must be a list of strings; ignored"))
            continue
        clean = [text.strip() for text in value if isinstance(text, str) and text.strip()]
        too_long = [text for text in clean if len(text) > MAX_LINE_LENGTH]
        if too_long:
            issues.append(Issue("warning", f"lines.{key}: {len(too_long)} line(s) longer than {MAX_LINE_LENGTH} characters were cut"))
        lines[key] = [text[:MAX_LINE_LENGTH] for text in clean]  # an empty list switches a group off
    return lines


def _read_theme(raw, issues: list[Issue]) -> dict[str, str]:
    theme = dict(DEFAULT_THEME)
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in theme and isinstance(value, str) and _HEX.match(value):
                theme[key] = value
            elif key in theme:
                issues.append(Issue("warning", f"theme.{key} must look like #RRGGBB; ignored"))
    return theme


def _read_head(raw) -> tuple[float, float, float]:
    default = (0.5, 0.2, 0.02)
    if not isinstance(raw, dict):
        return default
    x = _number(raw.get("x"), default[0], 0.0, 1.0)
    y = _number(raw.get("y"), default[1], 0.0, 1.0)
    top = _number(raw.get("top"), default[2], 0.0, 1.0)
    return (x, y, min(top, y))


def format_report(pack: CharacterPack) -> str:
    lines = [f"Character: {pack.name}  ({pack.root})"]
    if pack.frame_size:
        lines.append(f"Image size: {pack.frame_size[0]}x{pack.frame_size[1]}")
    for anim in pack.animations.values():
        kind = "still" if len(anim.frames) == 1 else f"{len(anim.frames)} frames @ {anim.fps:g} fps"
        lines.append(f"  {anim.name:10} {kind}")
    if pack.issues:
        lines.append("")
        lines.extend(str(issue) for issue in pack.issues)
    lines.append("")
    lines.append("RESULT: OK" if pack.ok else "RESULT: needs fixing (see ERROR lines)")
    return "\n".join(lines)
