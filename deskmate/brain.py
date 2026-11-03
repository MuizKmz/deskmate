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
WANDER_MIN, WANDER_MAX = 45, 140  # she strolls along the taskbar now and then
WANDER_LINE_CHANCE = 0.25
BIG_FALL = 1500.0  # landing speed (px/s) that earns an "ouch"
LATE_HOURS = range(0, 5)  # midnight to 5 am counts as "late"
BEDTIME_FROM = 23  # from 11 pm, if you're still working, she nudges you to sleep...
BEDTIME_EVERY = 45 * 60  # ...every 45 minutes

LABELS = {
    "idle": "chilling",
    "happy": "happy",
    "sleepy": "sleepy",
    "sleep": "sleeping",
    "pouty": "pouting",
    "surprised": "surprised",
    "blush": "flustered",
    "talk": "talking",
    "wave": "waving",
    "stretch": "stretching",
    "yawn": "yawning",
}
POSE_SECONDS = {"wave": 2.6, "stretch": 2.6, "yawn": 2.2}  # a gesture, not a face for the whole bubble


@dataclass
class Speech:
    text: str
    duration: float
    kind: str = "line"  # "chat" for her chat replies (the voice can be set to read only those)


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
        wander: bool = True,
    ):
        self.lines = lines
        self.rng = rng or random.Random()
        self.wallclock = wallclock
        self.chatty = chatty
        self.reminders = reminders
        self.wander = wander

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
        self._next_wander = now + self.rng.uniform(WANDER_MIN, WANDER_MAX)
        self._late_day = None
        self._last_bedtime = -1e9
        self._speech_until = -1e9
        self._chatting_until = -1e9  # quiet time while you're chatting with her
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

    def _say_text(self, text: str, now: float, expression: str, duration: float | None = None) -> None:
        duration = duration or speech_duration(text)
        self._speech.append(Speech(text, duration))
        self._speech_until = now + duration
        self._react(expression, now, duration)

    def _line(self, key: str, **values: str) -> str | None:
        """A random line from group ``key`` with {placeholders} filled in."""
        options = self.lines.get(key) or []
        if not options:
            return None
        line = self.rng.choice(options)
        for name, value in values.items():
            line = line.replace("{" + name + "}", value)
        return line

    def _say(self, key: str, now: float, expression: str | None = None) -> bool:
        """Queue a random line from group ``key``. The face matches while she talks."""
        options = self.lines.get(key) or []
        if not options:
            return False
        text = self.rng.choice(options)
        duration = speech_duration(text)
        self._speech.append(Speech(text, duration))
        self._speech_until = now + duration
        face = expression or "talk"
        self._react(face, now, min(duration, POSE_SECONDS.get(face, duration)))
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
        if not self._say("wake", now, "wave"):  # you're back: she waves hello
            self._react("wave", now, POSE_SECONDS["wave"])

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
        if not self._say(key, now, "wave"):  # hello!
            self._react("wave", now, POSE_SECONDS["wave"])

    def on_first_run(self, now: float) -> None:
        """The very first launch: introduce herself (falls back to a normal greeting)."""
        self._animations.append("hop")
        if not self._say("intro", now, "wave"):
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

    def on_walk_request(self, now: float) -> None:
        """'Take a walk' from the menu (the window does the walking)."""
        if self.base in ("sleep", "sleepy"):
            self._wake(now, quiet=True)
            self.base = "idle"
        if self._touch(now):
            return
        if not self._speaking(now) and self._say("wander", now, "happy"):
            return
        self._react("happy", now, 1.5)

    # --------------------------------------------------------------- reminders
    def on_reminder(self, now: float, what: str, missed: bool = False) -> None:
        """A reminder is due: wake up, hop, and tell the user (the bubble stays up a bit longer)."""
        if self.base == "sleep" or self.manual_sleep:
            self._wake(now, quiet=True)
        if self.base in ("pouty", "sleepy"):
            self.base = "idle"
        self.last_interaction = now
        text = self._line("reminder_missed" if missed else "reminder", what=what) or what
        self._animations.append("hop")
        self._say_text(text, now, "surprised" if not missed else "talk", max(6.0, speech_duration(text) + 2.0))

    def say(self, now: float, text: str, expression: str = "talk") -> None:
        """Say a fixed sentence (for app messages that aren't in her lines)."""
        self._say_text(text, now, expression)

    def on_reminder_set(self, now: float, time_text: str) -> None:
        text = self._line("reminder_set", time=time_text)
        if text:
            self._say_text(text, now, "happy")

    # -------------------------------------------------------------------- chat
    def on_chat_sent(self, now: float) -> None:
        """You wrote to her. She wakes up, stops pouting (talking to her counts as saying hi) and listens."""
        if self.base == "sleep" or self.manual_sleep:
            self._wake(now, quiet=True)
        if self.base in ("pouty", "sleepy"):
            self.base = "idle"
        self.last_interaction = now
        self._ignored_said = False
        self._chatting_until = now + 90
        self._react("blush" if self.rng.random() < 0.3 else "happy", now, 1.2)

    def on_chat_reply(self, now: float, mood: str, text: str) -> None:
        """Her answer from the chat model: show it in the bubble with the mood it came with."""
        duration = min(14.0, speech_duration(text) + 0.04 * max(0, len(text) - 90))
        self._speech.append(Speech(text, duration, "chat"))
        self._speech_until = now + duration
        self._react(mood or "talk", now, duration)
        self.last_interaction = now
        self._chatting_until = now + 90

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

    def on_landed(self, now: float, impact: float, perched: bool = False) -> None:
        """She touched down: ``impact`` is her landing speed (0 when simply put down).
        ``perched``: she landed on top of a window."""
        self.last_interaction = now
        if perched and impact < BIG_FALL:
            if self.rng.random() < 0.6 and self._say("perch", now, "happy"):
                return
            self._react("happy", now, 1.5)
            return
        if impact >= BIG_FALL:
            if not self._say("fall", now, "surprised"):
                self._react("surprised", now, 1.2)
            return
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
                self._say("sleepy", now, "yawn")

        # Late at night she gets sleepy too (and says so once per night).
        if self.base == "idle" and late:
            self.base = "sleepy"
            today = self.wallclock().date()
            if self._late_day != today:
                self._late_day = today
                self._say("late", now, "yawn")
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
        chatting = now < self._chatting_until
        if self.reminders and awake and user_active and not chatting and not self._speaking(now):
            if now - self._last_water >= WATER_EVERY:
                self._last_water = now
                self._say("water", now)
            elif now - self._active_since >= BREAK_AFTER:
                self._active_since = now
                self._say("break", now, "stretch")

        # Still working late at night? A gentle "go to bed" now and then.
        hour = self.wallclock().hour
        if (self.reminders and awake and user_active and not chatting and not self._speaking(now)
                and (hour >= BEDTIME_FROM or hour in LATE_HOURS) and now - self._last_bedtime >= BEDTIME_EVERY):
            self._last_bedtime = now
            self._say("bedtime", now, "yawn")

        # Random chit-chat.
        if self.chatty and self.base == "idle" and user_active and not chatting and now >= self._next_chatter:
            self._next_chatter = now + self.rng.uniform(CHATTER_MIN, CHATTER_MAX)
            if not self._speaking(now) and not self._dragging:
                self._say("random", now)

        # A little stroll along the taskbar (the window decides if it's possible right now).
        if self.wander and self.base == "idle" and user_active and not chatting and now >= self._next_wander:
            self._next_wander = now + self.rng.uniform(WANDER_MIN, WANDER_MAX)
            if not self._speaking(now) and not self._dragging:
                self._animations.append("wander")
                if self.rng.random() < WANDER_LINE_CHANCE:
                    self._say("wander", now, "happy")
