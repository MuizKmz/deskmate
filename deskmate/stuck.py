"""Stuck helper (buddy mode): notices when you've been fighting the same problem for a while.

Signs of being stuck, from the window title only: an error in your editor or terminal
("Traceback", "error", "failed"...), or searching around for one (Stack Overflow, GitHub
issues, "how to fix..."). When those add up to about 10 minutes within the last 20, while you're
actually at the PC, she offers to take a look. Never twice in a row about the same thing, and
not more than once every 45 minutes. Pure Python.
"""

from __future__ import annotations

import re
from collections import deque

STUCK_MINUTES = 10.0   # minutes of "stuck-looking" time...
WINDOW_MINUTES = 20.0  # ...within this many minutes
COOLDOWN = 45 * 60.0

CODE_APPS = ("code", "cursor", "idea64", "pycharm64", "webstorm64", "rider64", "devenv", "studio64", "eclipse",
             "sublime_text", "notepad++", "windowsterminal", "wt", "cmd", "powershell", "pwsh", "conhost",
             "postman", "datagrip64", "phpstorm64", "goland64", "clion64", "zed", "android studio")
ERROR_WORDS = re.compile(
    r"\b(error|errors|exception|traceback|failed|failing|failure|crash(ed)?|not working|doesn'?t work|"
    r"undefined|cannot|can'?t|unable to|segfault|stack ?trace|panic|fatal|bug|broken|refused|denied|timeout|"
    r"404|500|403|npe|nullpointer|typeerror|valueerror|syntaxerror|keyerror)\b", re.I)
HELP_SITES = re.compile(r"stack ?overflow|issue #\d+|\bissues?\b.*github|\bhow (to|do i)\b|"
                        r"\bfix\b|\bwhy (does|is|do)\b|stackexchange|superuser|serverfault", re.I)


def looks_stuck(activity) -> bool:
    """Does this window look like you're fighting a problem?"""
    if activity is None or activity.private or activity.quiet or activity.kind != "app":
        return False
    title = re.sub(r"[\w\-]+\.[a-z]{1,5}\b", " ", activity.title)  # file names ("errors.py") don't count
    if activity.exe in CODE_APPS:
        return bool(ERROR_WORDS.search(title))
    from .activity import BROWSERS

    if activity.app in BROWSERS:
        return bool(HELP_SITES.search(title) or (ERROR_WORDS.search(title) and "google" in title.lower()))
    return False


class StuckWatch:
    def __init__(self, stuck_minutes: float = STUCK_MINUTES, window_minutes: float = WINDOW_MINUTES,
                 cooldown: float = COOLDOWN):
        self.need = stuck_minutes * 60
        self.window = window_minutes * 60
        self.cooldown = cooldown
        self._samples: deque[tuple[float, float]] = deque()  # (when, stuck seconds counted then)
        self._last_seen = None
        self._last_offer = -1e9
        self._offered_key = None
        self.last_activity = None

    def observe(self, now: float, activity, active: bool) -> bool:
        """Call every few seconds. True when it's time to offer help (about ``activity``)."""
        previous, self._last_seen = self._last_seen, now
        while self._samples and now - self._samples[0][0] > self.window:
            self._samples.popleft()
        if previous is None or not active or not looks_stuck(activity):
            return False
        self._samples.append((now, min(now - previous, 30.0)))  # (a long gap isn't all "stuck" time)
        self.last_activity = activity
        stuck = sum(seconds for _, seconds in self._samples)
        if stuck < self.need or now - self._last_offer < self.cooldown or activity.key == self._offered_key:
            return False
        self._last_offer = now
        self._offered_key = activity.key
        self._samples.clear()
        return True
