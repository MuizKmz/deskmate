"""Small helpers shared by the tests (standard library only)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def write_png(path: Path, width: int = 40, height: int = 60, alpha: bool = True,
              color: tuple[int, int, int, int] = (200, 150, 220, 255)) -> Path:
    """Write a tiny solid-colour PNG without needing Pillow."""
    pixel = bytes(color if alpha else color[:3])
    raw = b"".join(b"\x00" + pixel * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def make_pack(root: Path, animations=("idle", "happy"), size=(40, 60), meta: dict | None = None) -> Path:
    import json

    for name in animations:
        write_png(root / name / f"{name}_01.png", *size)
    if meta is not None:
        (root / "character.json").write_text(json.dumps(meta), encoding="utf-8")
    return root
