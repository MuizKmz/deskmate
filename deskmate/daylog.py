"""A little log of your day, for her evening wrap-up. Pure Python, kept in daylog.json on your PC.

Every half minute or so, while you're actually using the PC, the app adds the time to whatever
you're on: just a short name ("VS Code", "YouTube", "GitHub"), never the window title, never
private windows. Plus the focus sessions you finished, the songs you played (names only) and
how many times you chatted. Only the last two weeks are kept.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

KEEP_DAYS = 14
MAX_SONGS = 30


def label_for(activity) -> str | None:
    """A short, safe name for what you're on: the app, or the website for a browser."""
    from .activity import BROWSERS

    if activity is None or activity.private or activity.kind != "app":
        return None
    if activity.music_player:
        return "YouTube Music" if activity.app in BROWSERS else activity.app
    if activity.app in BROWSERS:
        # "lofi hip hop radio - YouTube" -> "YouTube"; "Pull request #12 · MuizKmz/deskmate" -> the browser
        parts = re.split(r"\s+[-—–|·]\s+", activity.title)
        site = parts[-1].strip() if len(parts) > 1 else ""
        if 1 < len(site) <= 24 and not re.search(r"\d{3,}|[/\\]", site):
            return site
        return activity.app
    return activity.app


class DayLog:
    def __init__(self, path: Path):
        self.path = path
        self.days: dict[str, dict] = {}
        self._dirty = False
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("days"), dict):
                self.days = {k: v for k, v in raw["days"].items() if isinstance(v, dict)}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            log.warning("Day log unreadable (%s); starting fresh", error)

    def _day(self, day: date) -> dict:
        entry = self.days.setdefault(day.isoformat(), {})
        entry.setdefault("apps", {})
        entry.setdefault("focus", [])
        entry.setdefault("songs", [])
        entry.setdefault("chats", 0)
        return entry

    # ---------------------------------------------------------------- writing
    def add_time(self, day: date, label: str, seconds: float) -> None:
        apps = self._day(day)["apps"]
        apps[label] = round(apps.get(label, 0) + seconds, 1)
        self._dirty = True

    def add_focus(self, day: date, minutes: int, finished: bool) -> None:
        if minutes > 0:
            self._day(day)["focus"].append({"minutes": int(minutes), "finished": bool(finished)})
            self._dirty = True

    def add_song(self, day: date, song: str) -> None:
        songs = self._day(day)["songs"]
        if song and song not in songs and len(songs) < MAX_SONGS:
            songs.append(song[:120])
            self._dirty = True

    def add_chat(self, day: date) -> None:
        self._day(day)["chats"] += 1
        self._dirty = True

    def mark(self, day: date, flag: str, value=True) -> None:
        """Remember something about a day (e.g. "wrapup": the wrap-up was shown)."""
        self._day(day)[flag] = value
        self._dirty = True

    def flag(self, day: date, flag: str, default=None):
        return self.days.get(day.isoformat(), {}).get(flag, default)

    def save(self, today: date | None = None) -> bool:
        if not self._dirty:
            return True
        today = today or date.today()
        oldest = (today - timedelta(days=KEEP_DAYS)).isoformat()
        self.days = {k: v for k, v in self.days.items() if k >= oldest}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps({"days": self.days}, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            self._dirty = False
            return True
        except OSError as error:
            log.warning("Couldn't save the day log: %s", error)
            return False

    def clear(self) -> None:
        self.days = {}
        self._dirty = True

    # ---------------------------------------------------------------- reading
    def summary(self, day: date) -> dict:
        entry = self.days.get(day.isoformat(), {})
        apps = sorted(((k, v) for k, v in entry.get("apps", {}).items()), key=lambda kv: -kv[1])
        focus = entry.get("focus", [])
        return {
            "minutes": int(sum(v for _, v in apps) / 60),
            "top": [(name, int(seconds / 60)) for name, seconds in apps if seconds >= 60][:5],
            "focus_sessions": sum(1 for f in focus if f.get("finished")),
            "focus_minutes": sum(int(f.get("minutes", 0)) for f in focus),
            "songs": list(entry.get("songs", [])),
            "chats": int(entry.get("chats", 0)),
        }

    def describe(self, day: date) -> str:
        """The day in plain words (for her brain to write the wrap-up from)."""
        s = self.summary(day)
        if not s["minutes"]:
            return "Nothing logged today."
        parts = [f"On the PC for {hours(s['minutes'])}."]
        if s["top"]:
            parts.append("Most time on: " + ", ".join(f"{name} ({hours(m)})" for name, m in s["top"]) + ".")
        if s["focus_minutes"]:
            parts.append(f"Focus sessions finished: {s['focus_sessions']} ({hours(s['focus_minutes'])} focused).")
        if s["songs"]:
            parts.append("Songs played: " + "; ".join(s["songs"][:6]) + ".")
        if s["chats"]:
            parts.append(f"Chatted with you {s['chats']} time{'s' if s['chats'] != 1 else ''}.")
        return " ".join(parts)


def hours(minutes: int) -> str:
    """95 -> "1 h 35 min"; 40 -> "40 min"."""
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if m else f"{h} h"
