"""The brain decides which expression to show and what to say.

It's pure Python on purpose, with no Qt, so every rule can be unit-tested with a
fake clock. The window asks it two questions a few times per second:
"which face now?" and "anything to say?".

How it thinks:

    base mood   lasts a long time:   idle | sleepy | sleep | pouty
    reaction    short and expires:   happy after a pet, talk while speaking, ...

    face shown = surprised while being dragged,
                 else the reaction (until it expires),
                 else the base mood.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

# Timings in seconds. Tuned for a calm companion, not a needy one.
SLEEPY_AFTER = 5 * 60  # you stop using the computer -> she gets sleepy
SLEEP_AFTER = 15 * 60  # ... and then falls asleep
WAKE_IF_IDLE_UNDER = 3  # you touched mouse/keyboard again -> you're back
IGNORED_AFTER = 45 * 60  # you're busy but haven't touched her -> she pouts
PET_SPAM_COUNT, PET_SPAM_WINDOW = 5, 4.0  # 5 clicks within 4 s is too much
PET_LINE_GAP = 6.0  # don't put a speech bubble on every single click
HOVER_BLUSH_AFTER = 1.5  # mouse resting on her makes her shy
WATER_EVERY = 60 * 60  # care reminder: drink water
BREAK_AFTER = 50 * 60  # care reminder: non-stop work streak
RETURN_GRACE = 15 * 60  # after you come back, wait before the next water reminder
CHATTER_MIN, CHATTER_MAX = 6 * 60, 14 * 60  # random chit-chat interval
LATE_HOURS = range(0, 5)  # midnight to 5 am counts as "late"

LABELS = {
    "idle": "chilling",
    "happy": "happy",
    "sleepy": "sleepy",
    "sleep": "sleeping",
    "pouty": "pouting",
    "surprised": "surprised",
    "blush": "flustered",
    "talk": "talking",
}


@dataclass
class Speech:
    text: str
    duration: float


def speech_duration(text: str) -> float:
    """Seconds a bubble stays up: longer text, longer time (2.4 to 7 s)."""
    return min(7.0, max(2.4, 1.5 + 0.06 * len(text)))


class Brain:
    def __init__(
        self,
        lines: dict[str, list[str]],
        *,
        now: float,
        rng: random.Random | None = None,
        wallclock: Callable[[], datetime] = datetime.now,
        chatty: bool = True,
        reminders: bool = True,
    ):
        self.lines = lines
        self.rng = rng or random.Random()
        self.wallclock = wallclock
        self.chatty = chatty
        self.reminders = reminders

        self.base = "idle"
        self.manual_sleep = False
        self.last_interaction = now
        self._reaction: tuple[str, float] | None = None
        self._dragging = False
        self._pets: deque[float] = deque()
        self._last_pet_line = -1e9
        self._hover_since: float | None = None
        self._hover_reacted = False
        self._ignored_said = False
        self._active_since = now
        self._last_water = now
        self._next_chatter = now + self.rng.uniform(CHATTER_MIN, CHATTER_MAX)
        self._late_day = None
        self._speech_until = -1e9
        self._speech: list[Speech] = []
        self._animations: list[str] = []

    # ------------------------------------------------------------------ outputs
    def expression(self, now: float) -> str:
        if self._dragging:
            return "surprised"
        if self._reaction and now < self._reaction[1]:
            return self._reaction[0]
        return self.base

    def label(self, now: float) -> str:
        return LABELS.get(self.expression(now), self.expression(now))

    def drain_speech(self) -> list[Speech]:
        out, self._speech = self._speech, []
        return out

    def drain_animations(self) -> list[str]:
        out, self._animations = self._animations, []
        return out

    @property
    def asleep(self) -> bool:
        return self.base == "sleep"

    # ------------------------------------------------------------------ helpers
    def _react(self, expression: str, now: float, seconds: float) -> None:
        self._reaction = (expression, now + seconds)

    def _speaking(self, now: float) -> bool:
        return now < self._speech_until

    def _say(self, key: str, now: float, expression: str | None = None) -> bool:
        """Queue a random line from group ``key``. The face matches while she talks."""
        options = self.lines.get(key) or []
        if not options:
            return False
        text = self.rng.choice(options)
        duration = speech_duration(text)
        self._speech.append(Speech(text, duration))
        self._speech_until = now + duration
        self._react(expression or "talk", now, duration)
        return True

    def _late(self) -> bool:
        return self.wallclock().hour in LATE_HOURS

    def _touch(self, now: float) -> bool:
        """Any interaction resets the 'ignored' timer. Returns True if it ended a pout."""
        self.last_interaction = now
        if self.base == "pouty":
            self.base = "idle"
            self._ignored_said = False
            if not self._say("forgive", now, "blush"):
                self._react("blush", now, 2.5)
            return True
        return False

    def _fall_asleep(self, now: float) -> None:
        self.base = "sleep"
        self._reaction = None

    def _wake(self, now: float, quiet: bool = False) -> None:
        self.manual_sleep = False
        self.base = "idle"
        self.last_interaction = now
        self._ignored_said = False
        self._active_since = now
        self._last_water = max(self._last_water, now - WATER_EVERY + RETURN_GRACE)
        if quiet:
            self._react("surprised", now, 1.0)
            return
        self._animations.append("hop")
        if not self._say("wake", now, "surprised"):
            self._react("surprised", now, 1.5)

    # ------------------------------------------------------------------- events
    def on_start(self, now: float) -> None:
        hour = self.wallclock().hour
        if hour in LATE_HOURS or hour >= 22:
            key = "greet_night"
        elif hour < 12:
            key = "greet_morning"
        elif hour < 18:
            key = "greet_afternoon"
        else:
            key = "greet_evening"
        self._animations.append("hop")
        if not self._say(key, now, "happy"):
            self._react("happy", now, 2.0)

    def on_first_run(self, now: float) -> None:
        """The very first launch: introduce herself (falls back to a normal greeting)."""
        self._animations.append("hop")
        if not self._say("intro", now, "happy"):
            self.on_start(now)

    def on_pet(self, now: float) -> None:
        if self.base == "sleep":
            self._wake(now)
            return
        if self._touch(now):
            return
        self._pets.append(now)
        while self._pets and now - self._pets[0] > PET_SPAM_WINDOW:
            self._pets.popleft()
        if len(self._pets) >= PET_SPAM_COUNT:
            self._pets.clear()
            self._animations.append("shake")
            if not self._say("too_much", now, "pouty"):
                self._react("pouty", now, 2.5)
            return
        self._animations.append("hop")
        if not self._speaking(now) and now - self._last_pet_line >= PET_LINE_GAP:
            self._last_pet_line = now
            if self._say("pet", now, "happy"):
                return
        self._react("happy", now, 2.0)

    def on_talk_request(self, now: float) -> None:
        """'Talk to me' from the menu."""
        if self.base == "sleep":
            self._wake(now)
            return
        if self._touch(now):
            return
        if not self._say("random", now):
            self._react("happy", now, 2.0)

    def on_hover(self, now: float, inside: bool) -> None:
        if inside:
            self._hover_since = now
            self._hover_reacted = False
        else:
            self._hover_since = None

    def on_drag_start(self, now: float) -> None:
        if self.base == "sleep":
            self._wake(now, quiet=True)
        self._touch(now)
        self._dragging = True
        if self.rng.random() < 0.5:
            self._say("drag", now, "surprised")

    def on_drag_end(self, now: float) -> None:
        self._dragging = False
        self.last_interaction = now
        self._animations.append("land")
        if self.rng.random() < 0.5 and self._say("drop", now):
            return
        self._react("happy", now, 1.5)

    def set_manual_sleep(self, now: float, asleep: bool) -> None:
        if asleep:
            self._say("goodnight", now, "sleepy")
            self.base = "sleep"
            self.manual_sleep = True
        else:
            self._wake(now)

    # --------------------------------------------------------------------- tick
    def tick(self, now: float, user_idle: float | None) -> None:
        """Call a few times per second.

        ``user_idle`` is how many seconds ago the user last used the mouse or
        keyboard (``None`` if unknown).
        """
        idle = user_idle
        away = idle is not None and idle >= SLEEPY_AFTER
        if away:
            self._active_since = now  # a real pause breaks the non-stop work streak
        late = self._late()

        # Sleep and wake with the user (unless she was put to bed from the menu).
        if not self.manual_sleep and idle is not None:
            if self.base == "sleep":
                if idle < WAKE_IF_IDLE_UNDER:
                    self._wake(now)
            elif idle >= SLEEP_AFTER:
                self._fall_asleep(now)
            elif idle >= SLEEPY_AFTER and self.base in ("idle", "pouty"):
                self.base = "sleepy"
                self._say("sleepy", now, "sleepy")

        # Late at night she gets sleepy too (and says so once per night).
        if self.base == "idle" and late:
            self.base = "sleepy"
            today = self.wallclock().date()
            if self._late_day != today:
                self._late_day = today
                self._say("late", now, "sleepy")
        elif self.base == "sleepy" and not late and not away:
            self.base = "idle"

        user_active = idle is None or idle < 60

        # Busy all this time and never said hi? Pout.
        if (
            self.base == "idle"
            and user_active
            and not self._ignored_said
            and not self._dragging
            and now - self.last_interaction >= IGNORED_AFTER
        ):
            self.base = "pouty"
            self._ignored_said = True
            self._animations.append("shake")
            self._say("ignored", now, "pouty")

        # Mouse resting on her: shy blush.
        if (
            self._hover_since is not None
            and not self._hover_reacted
            and now - self._hover_since >= HOVER_BLUSH_AFTER
            and self.base != "sleep"
            and not self._dragging
            and not self._speaking(now)
        ):
            self._hover_reacted = True
            self._react("blush", now, 2.5)

        awake = self.base != "sleep"

        # Care reminders.
        if self.reminders and awake and user_active and not self._speaking(now):
            if now - self._last_water >= WATER_EVERY:
                self._last_water = now
                self._say("water", now)
            elif now - self._active_since >= BREAK_AFTER:
                self._active_since = now
                self._say("break", now)

        # Random chit-chat.
        if self.chatty and self.base == "idle" and user_active and now >= self._next_chatter:
            self._next_chatter = now + self.rng.uniform(CHATTER_MIN, CHATTER_MAX)
            if not self._speaking(now) and not self._dragging:
                self._say("random", now)
