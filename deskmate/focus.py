"""Focus timer: "let's focus for 25 minutes". Pure Python (no Qt), so it's easy to test.

While you focus she keeps quiet (no chit-chat, no walks, no water reminders), and a little
pill by her head counts down. When the time is up she cheers and suggests a short break; when
the break is over she asks if you want another round.

If you drift off to something distracting (YouTube, Netflix, social media, games) for more than
a minute, she gives you a gentle nudge, at most once every few minutes. Music players don't
count: lots of people focus *with* music. Only the window title and program are looked at, on
your PC, and only while a focus session you started is running.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LENGTHS = (25, 50)  # minutes, in the menu
BREAK_MINUTES = 5
DRIFT_AFTER = 60.0  # seconds on something distracting before she says something
DRIFT_GAP = 5 * 60.0  # ...and not again sooner than this

# Distracting sites (whole words in the browser's window title) and programs.
DISTRACTING_SITES = re.compile(
    r"\b(youtube|netflix|twitch|tiktok|instagram|facebook|reddit|twitter|9gag|disney\+|prime video|viu|shopee|"
    r"lazada|bilibili|crunchyroll)\b|\s/\sx$")
DISTRACTING_APPS = ("steam", "epicgameslauncher", "riotclientservices", "leagueclient", "valorant", "roblox",
                    "robloxplayerbeta", "minecraft", "genshinimpact", "netflix", "tiktok")


def is_distraction(activity) -> bool:
    """Is this window something you'd probably not be focusing on? (Music players aren't.)"""
    if activity is None or activity.private or activity.quiet or activity.music_player:
        return False
    if activity.exe in DISTRACTING_APPS:
        return True
    title = re.sub(r"^\(\d+\)\s*", "", activity.title.lower())
    return bool(DISTRACTING_SITES.search(title))


@dataclass
class Focus:
    """One focus session (and the short break after it)."""

    minutes: int
    started: float
    phase: str = "focus"  # "focus" -> "break" -> "over"
    phase_end: float = 0.0
    _drift_since: float | None = None
    _last_nudge: float = -1e9
    nudges: int = 0

    def __post_init__(self):
        if not self.phase_end:
            self.phase_end = self.started + self.minutes * 60

    @property
    def focusing(self) -> bool:
        return self.phase == "focus"

    def left(self, now: float) -> float:
        return max(0.0, self.phase_end - now)

    def clock(self, now: float) -> str:
        """"24:13" (minutes:seconds left)."""
        seconds = int(self.left(now) + 0.999)
        return f"{seconds // 60}:{seconds % 60:02d}"

    def step(self, now: float) -> str | None:
        """Moves the session on when its time is up: "done" (focus over), "break_over", or None."""
        if now < self.phase_end:
            return None
        if self.phase == "focus":
            self.phase = "break"
            self.phase_end = now + BREAK_MINUTES * 60
            self._drift_since = None
            return "done"
        if self.phase == "break":
            self.phase = "over"
            return "break_over"
        return None

    def observe(self, now: float, activity) -> bool:
        """You're on ``activity`` now. True when it's time for a gentle "back to work~"."""
        if not self.focusing or not is_distraction(activity):
            self._drift_since = None
            return False
        if self._drift_since is None:
            self._drift_since = now
            return False
        if now - self._drift_since >= DRIFT_AFTER and now - self._last_nudge >= DRIFT_GAP:
            self._last_nudge = now
            self.nudges += 1
            return True
        return False

    def focused_minutes(self, now: float) -> int:
        """How long you actually focused (for the day's log), in whole minutes."""
        end = min(now, self.started + self.minutes * 60)
        return max(0, int((end - self.started) / 60))
