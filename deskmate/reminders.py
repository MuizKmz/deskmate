"""Reminders: "remind me at 3pm about the meeting". Pure Python, no Qt.

Times she understands (in chat, or in Reminders > Add reminder...):

    15:00   3pm   3:30 pm   9am          today, or tomorrow if that time has passed
    in 20 min   20m   in 2 hours   1h30   +45                      from now

Reminders are saved in the data folder, so they survive a restart. If one came due
while DeskMate was closed, she mentions it when she starts (if it's from today).
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

MAX_REMINDERS = 50
MAX_TEXT = 120
MISSED_WITHIN = timedelta(hours=12)  # older missed reminders are dropped quietly

_CLOCK = re.compile(r"^(?:at\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$", re.I)
_DURATION = re.compile(
    r"^(?:(in)\s+|(\+)\s*)?(?:(\d+)\s*(h|hr|hrs|hour|hours)\b\s*)?(?:(\d+)\s*(m|min|mins|minute|minutes)?)?$", re.I)


def parse_when(text: str, now: datetime) -> datetime | None:
    """A time like '15:00', '3pm' or 'in 20 min' as a datetime after ``now`` (None if not understood)."""
    text = re.sub(r"\s+", " ", (text or "").strip().lower())
    text = re.sub(r"(\d)h(\d)", r"\1h \2", text)  # 1h30 -> 1h 30
    if not text:
        return None
    clock = _CLOCK.match(text)
    if clock and (clock.group(2) or clock.group(3) or text.startswith("at ")):
        hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
        suffix = (clock.group(3) or "").replace(".", "")
        if suffix:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if suffix == "pm" else 0)
        if hour > 23 or minute > 59:
            return None
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return due if due > now else due + timedelta(days=1)
    duration = _DURATION.match(text)
    if duration:
        marker, hours, minutes, unit = duration.group(1) or duration.group(2), duration.group(3), duration.group(5), duration.group(6)
        if minutes and not (unit or marker or hours):  # a bare number ("10 push-ups") is not a time
            return None
        if hours or minutes:
            total = timedelta(hours=int(hours or 0), minutes=int(minutes or 0))
            if timedelta(0) < total <= timedelta(days=2):
                return (now + total).replace(microsecond=0)
    return None


def parse_request(text: str, now: datetime) -> tuple[datetime, str] | None:
    """'15:00 meeting', '3pm call mom', 'in 20 min stretch', 'meeting at 3pm' -> (due, what)."""
    words = re.sub(r"\s+", " ", (text or "").strip()).split(" ")
    words = [w for w in words if w]
    longest = min(4, len(words))
    for k in range(longest, 0, -1):  # time first: "3:30 pm submit report"
        due = parse_when(" ".join(words[:k]).rstrip("-:,"), now)
        if due:
            return due, clean_text(" ".join(words[k:]).strip(" -:,")) or "your reminder"
    for k in range(longest, 0, -1):  # time last: "submit report at 3:30 pm"
        due = parse_when(" ".join(words[-k:]), now)
        if due and k < len(words):
            return due, clean_text(" ".join(words[:-k]).strip(" -:,")) or "your reminder"
    return None


def clean_text(text: str) -> str:
    text = re.sub(r"^(?:to|about|for|that)\s+", "", re.sub(r"\s+", " ", text or "").strip(), flags=re.I)
    return text[:MAX_TEXT].strip()


@dataclass
class Reminder:
    id: str
    due: str  # ISO time, local
    text: str

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.due)

    def label(self, now: datetime) -> str:
        due = self.when
        day = "" if due.date() == now.date() else "tomorrow " if due.date() == (now + timedelta(days=1)).date() \
            else f"{due:%a %d %b} "
        return f"{day}{due:%H:%M}  {self.text}"


class ReminderBook:
    def __init__(self, path: Path | None, clock: Callable[[], datetime] = datetime.now):
        self.path = path
        self.clock = clock
        self.items: list[Reminder] = []
        self._load()

    # --------------------------------------------------------------- storage
    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data.get("reminders", []):
                reminder = Reminder(str(item["id"]), str(item["due"]), clean_text(str(item["text"])))
                reminder.when  # noqa: B018  (raises if the date is broken)
                self.items.append(reminder)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            log.warning("Reminders file unreadable; starting with none")
            self.items = []
        self.items.sort(key=lambda r: r.due)

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"reminders": [asdict(r) for r in self.items]}, indent=1, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            log.warning("Could not save reminders", exc_info=True)

    # ------------------------------------------------------------------- use
    def add(self, due: datetime, text: str) -> Reminder | None:
        text = clean_text(text) or "your reminder"
        if len(self.items) >= MAX_REMINDERS or due <= self.clock() - timedelta(minutes=1):
            return None
        reminder = Reminder(uuid.uuid4().hex[:8], due.replace(microsecond=0).isoformat(), text)
        self.items.append(reminder)
        self.items.sort(key=lambda r: r.due)
        self._save()
        return reminder

    def cancel(self, reminder_id: str) -> bool:
        before = len(self.items)
        self.items = [r for r in self.items if r.id != reminder_id]
        if len(self.items) != before:
            self._save()
            return True
        return False

    def upcoming(self) -> list[Reminder]:
        now = self.clock()
        return [r for r in self.items if r.when > now]

    def pop_due(self) -> list[Reminder]:
        """Reminders whose time has come (removed from the book)."""
        now = self.clock()
        due = [r for r in self.items if r.when <= now]
        if due:
            self.items = [r for r in self.items if r.when > now]
            self._save()
        return due

    def pop_missed(self) -> list[Reminder]:
        """At start-up: ones that came due while DeskMate was closed (recent ones only)."""
        now = self.clock()
        return [r for r in self.pop_due() if now - r.when <= MISSED_WITHIN]
