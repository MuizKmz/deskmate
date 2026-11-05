"""Your bond with her: it grows the more time you spend together. Pure Python, kept in bond.json.

Each character has her own bond (Yuki and Piko each get to know you). Points come from the
things you do together, with a daily limit for each so clicking her 500 times doesn't count:

    a pat 1 (10 a day) · a chat message 3 (30 a day) · a focus session 5 · a game 3 (24 a day)
    · a dance together 2 (6 a day) · coming back on a new day 4

The bond never goes down. Levels unlock outfits, and she gets a little warmer.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

LEVELS = [  # (points needed, name)
    (0, "Just met"),
    (25, "Getting to know you"),
    (70, "Friends"),
    (150, "Good friends"),
    (270, "Close friends"),
    (430, "Best friends"),
    (650, "Partners in crime"),
    (950, "Inseparable"),
]
POINTS = {"pet": 1, "chat": 3, "focus": 5, "game": 3, "dance": 2, "visit": 4}
DAILY_CAP = {"pet": 10, "chat": 30, "focus": 40, "game": 24, "dance": 6, "visit": 4}


@dataclass(frozen=True)
class Level:
    number: int    # 1, 2, ...
    name: str      # "Friends"
    points: int    # your points now
    floor: int     # points this level started at
    next_at: int | None  # points for the next level (None at the top)

    @property
    def progress(self) -> float:
        """How far to the next level (0..1)."""
        if self.next_at is None:
            return 1.0
        return (self.points - self.floor) / max(1, self.next_at - self.floor)

    def describe(self) -> str:
        to_go = f" · {self.next_at - self.points} to the next level" if self.next_at is not None else ""
        return f"Lv {self.number} · {self.name}{to_go}"


def level_for(points: int) -> Level:
    number = 1
    for i, (needed, _name) in enumerate(LEVELS):
        if points >= needed:
            number = i + 1
    floor, name = LEVELS[number - 1]
    next_at = LEVELS[number][0] if number < len(LEVELS) else None
    return Level(number, name, points, floor, next_at)


class Bond:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.data = {k: v for k, v in raw.items() if isinstance(v, dict)}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            log.warning("Bond file unreadable (%s); starting fresh", error)

    def _entry(self, character: str, today: date) -> dict:
        entry = self.data.setdefault(character, {"points": 0, "since": today.isoformat(), "days": 0})
        if entry.get("today") != today.isoformat():
            entry["today"] = today.isoformat()
            entry["counts"] = {}
        return entry

    def level(self, character: str) -> Level:
        return level_for(int(self.data.get(character, {}).get("points", 0)))

    def days_together(self, character: str, today: date) -> int:
        entry = self.data.get(character)
        if not entry:
            return 0
        try:
            return (today - date.fromisoformat(entry["since"])).days + 1
        except (KeyError, ValueError):
            return 0

    def add(self, character: str, kind: str, today: date) -> tuple[int, Level | None]:
        """Something you did together. Returns (points gained, the new level if she just levelled up)."""
        if kind not in POINTS:
            return 0, None
        entry = self._entry(character, today)
        counts = entry["counts"]
        before = self.level(character)
        room = DAILY_CAP[kind] - counts.get(kind, 0)
        gained = max(0, min(POINTS[kind], room))
        if not gained:
            return 0, None
        counts[kind] = counts.get(kind, 0) + gained
        entry["points"] = int(entry.get("points", 0)) + gained
        if kind == "visit":
            entry["days"] = int(entry.get("days", 0)) + 1
        self.save()
        after = self.level(character)
        return gained, after if after.number > before.number else None

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError as error:
            log.warning("Couldn't save the bond: %s", error)
            return False

    def prompt(self, character: str, today: date) -> str:
        """For her chat brain: how close you two are."""
        level = self.level(character)
        days = self.days_together(character, today)
        warmth = ("You've only just met: friendly, a little shy." if level.number <= 1 else
                  "You're getting to know each other." if level.number == 2 else
                  "You're friends: relaxed and warm." if level.number <= 4 else
                  "You're very close: affectionate (like a best friend), playful, you know them well.")
        return (f"Your bond with them: {level.name} (level {level.number}), together for {days} "
                f"day{'s' if days != 1 else ''}. {warmth}")
