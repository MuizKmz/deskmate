"""She remembers you across days. Pure Python, no Qt; one small JSON file on your PC.

Three kinds of memories, all visible (and deletable) in the "What I remember about you" window:

* **facts**: things you told her ("Likes YUI's songs", "Birthday is 12 May"). The chat model
  adds them with a ``<remember>`` tag when you mention something worth keeping, and removes
  them with ``<forget>`` when you ask her to.
* **days**: a one-line diary entry for each day you chatted ("You fixed the perch bug late at
  night~"), written the next time she starts (see ``ChatSession.summarize_day``).
* **habits**: what keeps coming back while she watches with you (buddy mode): songs, sites,
  projects. Counted on your PC, never sent anywhere except as a short line in her prompt.

``prompt()`` turns it into a few lines for her system prompt, so she can say "YUI again?".
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

MAX_FACTS = 40
MAX_DAYS = 14
MAX_HABITS = 60
PROMPT_FACTS, PROMPT_DAYS, PROMPT_HABITS = 15, 3, 6
HABIT_DAYS = 14  # habits older than this aren't mentioned

INSTRUCTIONS = """\
Memory: you remember the user across days (they can see and delete these memories).
If they tell you something worth remembering for other days (something they like or dislike, a project, \
a plan, a person's name, an important date), add this at the very end of your reply: \
<remember>a short fact in third person, like "Likes YUI's songs"</remember>
If they ask you to forget something, add <forget>a few words of that fact</forget> and say you forgot it.
Never remember passwords, money, health details, or anything they call secret. Don't add tags for small talk."""

_SMALL_WORDS = re.compile(r"\b(the|a|an|my|their|is|are|of|to)\b")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _SMALL_WORDS.sub("", re.sub(r"[^\w\s]", "", text.lower()))).strip()


@dataclass
class Memory:
    path: Path | None = None
    facts: list[dict] = field(default_factory=list)   # {"text", "added"}
    days: list[dict] = field(default_factory=list)    # {"date", "summary"}, newest last
    habits: dict = field(default_factory=dict)        # key -> {"label", "kind", "count", "last"}

    def __post_init__(self) -> None:
        self._load()

    # ------------------------------------------------------------------ disk
    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.facts = [f for f in data.get("facts", []) if isinstance(f, dict) and isinstance(f.get("text"), str)]
            self.days = [d for d in data.get("days", []) if isinstance(d, dict) and isinstance(d.get("summary"), str)]
            habits = data.get("habits", {})
            self.habits = {k: v for k, v in habits.items() if isinstance(v, dict)} if isinstance(habits, dict) else {}
        except (OSError, ValueError, AttributeError):
            log.warning("Memory file unreadable, starting fresh")

    def save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"facts": self.facts, "days": self.days, "habits": self.habits},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            log.warning("Could not save memory", exc_info=True)

    # ----------------------------------------------------------------- facts
    def remember(self, text: str, today: date) -> bool:
        """Keep a fact. A newer version of the same fact replaces the old one. False if nothing to keep."""
        text = re.sub(r"\s+", " ", text or "").strip().strip('"').rstrip(".")[:160]
        key = _norm(text)
        if len(key) < 3:
            return False
        self.facts = [f for f in self.facts if not _same(_norm(f["text"]), key)]
        self.facts.append({"text": text, "added": today.isoformat()})
        self.facts = self.facts[-MAX_FACTS:]
        self.save()
        return True

    def forget(self, words: str) -> int:
        """Forget every fact that contains these words (as she understood your 'forget that...')."""
        key = _norm(words)
        if len(key) < 3:
            return 0
        before = len(self.facts)
        self.facts = [f for f in self.facts if key not in _norm(f["text"])]
        removed = before - len(self.facts)
        if removed:
            self.save()
        return removed

    # ------------------------------------------------------------------ days
    def add_day(self, day: date, summary: str) -> None:
        summary = re.sub(r"\s+", " ", summary or "").strip()[:200]
        if not summary:
            return
        self.days = [d for d in self.days if d.get("date") != day.isoformat()]
        self.days.append({"date": day.isoformat(), "summary": summary})
        self.days.sort(key=lambda d: d.get("date", ""))
        self.days = self.days[-MAX_DAYS:]
        self.save()

    def has_day(self, day: date) -> bool:
        return any(d.get("date") == day.isoformat() for d in self.days)

    # ---------------------------------------------------------------- habits
    def notice(self, kind: str, label: str, today: date) -> None:
        """Buddy mode saw this again (a song, a site, a project)."""
        label = re.sub(r"\s+", " ", label or "").strip()[:80]
        if not label:
            return
        key = f"{kind}|{label.lower()}"
        habit = self.habits.get(key) or {"label": label, "kind": kind, "count": 0, "last": ""}
        habit["count"] = int(habit.get("count", 0)) + 1
        habit["last"] = today.isoformat()
        self.habits[key] = habit
        if len(self.habits) > MAX_HABITS:  # keep the most-seen ones
            keep = sorted(self.habits.items(), key=lambda kv: (kv[1]["count"], kv[1]["last"]), reverse=True)
            self.habits = dict(keep[:MAX_HABITS])
        self.save()

    def frequent(self, today: date, limit: int = PROMPT_HABITS) -> list[dict]:
        cutoff = (today - timedelta(days=HABIT_DAYS)).isoformat()
        recent = [h for h in self.habits.values() if h.get("last", "") >= cutoff and h.get("count", 0) >= 2]
        return sorted(recent, key=lambda h: (h["count"], h["last"]), reverse=True)[:limit]

    # ---------------------------------------------------------------- remove
    def remove(self, section: str, index_or_key) -> None:
        """Delete one memory from the window: ('facts', i), ('days', i) or ('habits', key)."""
        if section == "habits":
            self.habits.pop(index_or_key, None)
        elif section in ("facts", "days"):
            items = getattr(self, section)
            if 0 <= index_or_key < len(items):
                items.pop(index_or_key)
        self.save()

    def clear(self) -> None:
        self.facts, self.days, self.habits = [], [], {}
        self.save()

    @property
    def empty(self) -> bool:
        return not (self.facts or self.days or self.habits)

    # ---------------------------------------------------------------- prompt
    def prompt(self, today: date) -> str:
        """What she knows about you, for her system prompt (plus how to add to it)."""
        lines = [INSTRUCTIONS]
        if self.facts:
            lines.append("What you remember about them:")
            lines += [f"- {f['text']}" for f in self.facts[-PROMPT_FACTS:]]
        earlier = [d for d in self.days if d.get("date", "") < today.isoformat()][-PROMPT_DAYS:]
        if earlier:
            lines.append("Your diary of recent days together:")
            lines += [f"- {_day_label(d['date'], today)}: {d['summary']}" for d in earlier]
        habits = self.frequent(today)
        if habits:
            lines.append("Things they often do while you watch with them (mention now and then, not every time): "
                         + "; ".join(f"{_habit_text(h)} ({h['count']}x)" for h in habits))
        return "\n".join(lines)


def _same(a: str, b: str) -> bool:
    """Two facts say the same thing ("Likes YUI" vs "likes YUI's songs")."""
    return a == b or (min(len(a), len(b)) >= 6 and (a in b or b in a))


def _day_label(iso: str, today: date) -> str:
    try:
        day = date.fromisoformat(iso)
    except ValueError:
        return iso
    gap = (today - day).days
    return "yesterday" if gap == 1 else f"{day:%A %d %b}" if gap < 7 else f"{day:%d %b}"


def _habit_text(habit: dict) -> str:
    return {"music": "listens to {}", "site": "visits {}", "project": "works on {}"}.get(
        habit.get("kind"), "uses {}").format(habit["label"])


def habit_of(activity) -> tuple[str, str] | None:
    """What's worth counting about an Activity: (kind, label), or None (private, calls, nothing useful)."""
    if activity is None or activity.private or activity.quiet:
        return None
    if activity.kind == "music":
        return "music", activity.title
    if activity.music_player:
        return None  # the songs are counted on their own
    parts = [p.strip() for p in re.split(r"\s+[-—–|]\s+", activity.title) if p.strip()]
    if activity.app in ("VS Code", "Cursor", "PyCharm", "IntelliJ IDEA", "Visual Studio", "Android Studio") \
            and len(parts) >= 2:
        return "project", parts[1]  # "app.py - deskmate" -> the project, not the file
    if activity.app in ("Chrome", "Edge", "Firefox", "Brave", "Opera"):
        return ("site", parts[-1]) if len(parts) >= 2 else None  # "lofi - YouTube" -> YouTube
    return "app", activity.app
