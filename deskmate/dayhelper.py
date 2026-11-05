"""Phase 8, "she helps you through the day": focus timer, the day's wrap-up, special days,
the weather, and the stuck helper. The Controller calls ``DayHelper.tick()`` with her other
ticks; the rules themselves live in small pure modules (focus, daylog, days, weather, stuck).
"""

from __future__ import annotations

import logging
import time
from datetime import date

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .daylog import DayLog, hours, label_for
from .focus import Focus
from .glass import GlassWindow, button_style, css, label_style
from .paths import data_dir
from .stuck import StuckWatch

log = logging.getLogger(__name__)

POLL = 15.0           # seconds between looks at what you're on (for the day's log)
FAST_POLL = 5.0       # ...while you focus or she watches with you
SAVE_EVERY = 300.0    # the day's log is written to disk every 5 minutes (and when she quits)
ACTIVE = 60.0         # you touched mouse/keyboard within this many seconds: you're at the PC
GREET_AFTER = 25.0    # special-day / weather lines wait for her hello to finish
WEATHER_REFRESH = 2 * 3600.0
WEATHER_MORNING_UNTIL = 14  # the "today's weather" line only before 2 pm
WRAPUP_MIN_MINUTES = 60  # no wrap-up for a day you barely used the PC
CHIPS_SECONDS = 25.0


class FocusPill(QWidget):
    """A small pill by her head while you focus: 🍅 24:13 (or ☕ 4:12 on the break). Click to stop."""

    clicked = Signal()
    HEIGHT = 24

    def __init__(self, accent: QColor):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accent = QColor(accent)
        self._text = ""
        self._font = QFont(self.font())
        self._font.setPointSizeF(9)
        self._font.setBold(True)
        self.setFixedSize(QSize(78, self.HEIGHT))

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str, tip: str) -> None:
        if text != self._text:
            self._text = text
            self.update()
        if tip != self.toolTip():
            self.setToolTip(tip)

    def place(self, head: QRect) -> None:
        """Just above the top-left of her head (the 👁 sign uses the top-right)."""
        self.move(QPoint(head.left() - self.width() // 3, head.top() - self.HEIGHT // 2))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(24, 19, 34, 225))
        painter.setPen(QPen(self._accent, 1.2))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setPen(QColor(244, 238, 250))
        painter.setFont(self._font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


class DayWindow(GlassWindow):
    """"My day": how long you were on the PC, what you were on, focus, songs, and her few words about it."""

    def __init__(self, controller, day: date, summary: dict, weather: str = ""):
        pack = controller.pack
        super().__init__("Your day", f"{day:%A, %d %B}", pack.theme, controller.icon.pixmap(96),
                         smooth=pack.meta.get("smooth", True), size=QSize(420, 520))
        column = QVBoxLayout(self.body)
        column.setContentsMargins(20, 8, 20, 16)
        column.setSpacing(6)
        a = self.accent

        self.words = QLabel("")
        self.words.setWordWrap(True)
        self.words.setStyleSheet(label_style(10) + f" background: {css(a, 0.16)}; border-radius: 12px;"
                                 " padding: 10px 12px; font-style: italic;")
        self.words.hide()
        column.addWidget(self.words)

        def stat(emoji: str, text: str) -> None:
            label = QLabel(f"{emoji}  {text}" if emoji else text)
            label.setWordWrap(True)
            label.setStyleSheet(label_style(10))
            column.addWidget(label)

        if not summary["minutes"]:
            stat("🌙", "Nothing logged yet today.")
        else:
            stat("⏱", f"On the PC for <b>{hours(summary['minutes'])}</b>")
            if summary["focus_minutes"]:
                n = summary["focus_sessions"]
                stat("🍅", f"Focused <b>{hours(summary['focus_minutes'])}</b> ({n} session{'s' if n != 1 else ''} "
                           "finished)")
            if summary["chats"]:
                n = summary["chats"]
                stat("💬", f"Chatted with {pack.name} {n} time{'s' if n != 1 else ''}")
        if weather:
            stat("", weather)  # (it starts with its own emoji: "⛅ 29° partly cloudy")

        if summary["top"]:
            heading = QLabel("Where your time went")
            heading.setStyleSheet(label_style(9.5, 0.7, bold=True) + " margin-top: 6px;")
            column.addWidget(heading)
            longest = max(m for _, m in summary["top"]) or 1
            for name, minutes in summary["top"]:
                column.addWidget(self._bar(name, minutes, minutes / longest))
        if summary["songs"]:
            heading = QLabel("Songs today")
            heading.setStyleSheet(label_style(9.5, 0.7, bold=True) + " margin-top: 6px;")
            column.addWidget(heading)
            songs = QLabel("\n".join(f"🎵 {song}" for song in summary["songs"][:5]))
            songs.setTextFormat(Qt.TextFormat.PlainText)
            songs.setWordWrap(True)
            songs.setStyleSheet(label_style(9, 0.85))
            column.addWidget(songs)
        column.addStretch(1)

        note = QLabel("Kept only on this PC: app names, never window titles.")
        note.setStyleSheet(label_style(8, 0.45))
        column.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Nice~")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(button_style(a, True))
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        column.addLayout(buttons)

    def _bar(self, name: str, minutes: int, share: float) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(name)
        label.setFixedWidth(120)
        label.setStyleSheet(label_style(9))
        bar = QWidget()
        bar.setFixedHeight(10)
        bar.setFixedWidth(max(6, int(150 * share)))
        bar.setStyleSheet(f"background: {css(self.accent, 0.75)}; border-radius: 5px;")
        amount = QLabel(hours(minutes))
        amount.setStyleSheet(label_style(8.5, 0.7))
        row.addWidget(label)
        row.addWidget(bar)
        row.addWidget(amount)
        row.addStretch(1)
        return holder

    def set_words(self, text: str) -> None:
        self.words.setText(text)
        self.words.setVisible(bool(text))
        if text:  # (a wrapped label doesn't grow by itself inside a fixed-size window)
            width = self.width() - 40
            self.words.setFixedWidth(width)
            self.words.setMinimumHeight(self.words.heightForWidth(width))


def system_country() -> str:
    """The country Windows is set to ("MY"), for the holidays; "" if unknown."""
    from PySide6.QtCore import QLocale

    name = QLocale.system().name()  # "en_MY", "ms_MY", "en_US"
    return name.split("_")[1].upper() if "_" in name else ""


class DayHelper:
    def __init__(self, controller):
        self.c = controller
        self.log = DayLog(data_dir() / "daylog.json")
        self.focus: Focus | None = None
        self.pill: FocusPill | None = None
        self.chips = None
        self._chip_actions: dict[str, callable] = {}
        self._chips_until = 0.0
        self.stuck = StuckWatch()
        self._started = time.monotonic()
        self._polled = -1e9
        self._saved = time.monotonic()
        self._song = None
        self.weather = None  # today's weather.Weather, once fetched
        self._weather_at = -1e9
        self._weather_busy = False
        self._weather_waiting = []  # callbacks for the answer on its way
        self._place = None  # (city, weather.Place)
        self._worker = None
        self.window: DayWindow | None = None
        self.read_weather = None  # tests: a function city -> Weather

    # ----------------------------------------------------------------- helpers
    @property
    def settings(self):
        return self.c.settings

    def today(self) -> date:
        return self.c.brain.wallclock().date()

    def _hour(self) -> int:
        return self.c.brain.wallclock().hour

    def _background(self):
        if self._worker is None:
            from .chatbox import Background

            self._worker = Background()
        return self._worker

    def _active(self) -> bool:
        idle = self.c.idle.seconds()
        return idle is None or idle < ACTIVE

    def _free(self, now: float) -> bool:
        """Can she say something on her own right now?"""
        c, brain = self.c, self.c.brain
        return (c.companion.isVisible() and not brain.asleep and not brain._speaking(now)
                and now >= brain._chatting_until and not brain._dragging and not c._in_a_call()
                and not (c._chat_worker is not None and c._chat_worker.busy))

    def _say(self, now: float, key: str, expression: str = "talk", hop: bool = False, **values) -> str:
        brain = self.c.brain
        text = brain._line(key, **values) or ""
        if text:
            if hop:
                brain._animations.append("hop")
            brain._say_text(text, now, expression)
            self.c._apply(now)
        return text

    def windows(self) -> list:
        """Her extra little windows (left out of screen pictures)."""
        return [w for w in (self.pill, self.chips, self.window) if w is not None]

    # ------------------------------------------------------------------- chips
    def _offer(self, choices: dict) -> None:
        """Answer chips under her bubble: {"Another round": callable, ...}."""
        from .look import QuickReplies

        if self.chips is None:
            self.chips = QuickReplies(self.c._accent)
            self.chips.chosen.connect(self._chose)
        self._chip_actions = dict(choices)
        bubble = self.c.bubble
        if bubble.isVisible():
            self.chips.offer(list(choices), bubble.geometry(), self.c.companion.available_rect(), chat=False)
            self._chips_until = time.monotonic() + CHIPS_SECONDS

    def _chose(self, text: str) -> None:
        action = self._chip_actions.pop(text, None)
        self._chip_actions = {}
        if action is not None:
            action()

    # ------------------------------------------------------------------- focus
    @property
    def focusing(self) -> bool:
        return self.focus is not None and self.focus.focusing

    def start_focus(self, minutes: int | None = None) -> None:
        minutes = int(minutes or self.settings["focus_minutes"])
        now = time.monotonic()
        if self.focus is not None:
            self._end_focus(now, finished=False)
        if self.chips is not None:
            self.chips.hide()
        self.c._set("focus_minutes", max(5, min(180, minutes)))
        self.focus = Focus(minutes, now)
        brain = self.c.brain
        if brain.asleep or brain.manual_sleep:
            brain._wake(now, quiet=True)
        brain.focus_until = self.focus.phase_end
        brain.last_interaction = now
        log.info("Focus: %d minutes", minutes)
        self._say(now, "focus_start", "happy", hop=True, minutes=str(minutes))
        self._show_pill(now)

    def stop_focus(self) -> None:
        """You stopped it (menu, or a click on the pill)."""
        if self.focus is None:
            return
        now = time.monotonic()
        focusing = self.focus.focusing
        self._end_focus(now, finished=False)
        if focusing:
            self._say(now, "focus_stopped", "talk")

    def _end_focus(self, now: float, finished: bool) -> None:
        focus, self.focus = self.focus, None
        if focus is not None and focus.focusing:
            self.log.add_focus(self.today(), focus.focused_minutes(now) if not finished else focus.minutes, finished)
        self.c.brain.focus_until = -1e9
        if self.pill is not None:
            self.pill.hide()

    def _focus_tick(self, now: float) -> None:
        focus = self.focus
        event = focus.step(now)
        if event == "done":
            self.log.add_focus(self.today(), focus.minutes, True)
            brain = self.c.brain
            brain.focus_until = -1e9
            brain._active_since = now  # the break counts as a break
            log.info("Focus done (%d min)", focus.minutes)
            self._say(now, "focus_done", "happy", hop=True, minutes=str(focus.minutes))
            self._offer({"Another round": lambda: self.start_focus(focus.minutes),
                         "I'm done": self._done_for_now})
        elif event == "break_over":
            self.focus = None
            minutes = focus.minutes
            self._say(now, "focus_break_over", "wave")
            self._offer({"Another round": lambda: self.start_focus(minutes), "Not now": lambda: None})
        self._show_pill(now)

    def _done_for_now(self) -> None:
        now = time.monotonic()
        self.focus = None
        if self.pill is not None:
            self.pill.hide()
        self._say(now, "focus_stopped", "happy")

    def _show_pill(self, now: float) -> None:
        focus = self.focus
        visible = self.c.companion.isVisible()
        if focus is None or focus.phase == "over" or not visible:
            if self.pill is not None and self.pill.isVisible():
                self.pill.hide()
            return
        if self.pill is None:
            self.pill = FocusPill(self.c._accent)
            self.pill.clicked.connect(self.stop_focus)
        if focus.focusing:
            self.pill.set_text(f"🍅 {focus.clock(now)}", f"Focusing · {focus.clock(now)} left\nClick to stop")
        else:
            self.pill.set_text(f"☕ {focus.clock(now)}", f"Break · {focus.clock(now)} left\nClick to end the break")
        self.pill.place(self.c.companion.head_rect_global())
        if not self.pill.isVisible():
            self.pill.show()

    # --------------------------------------------------------------------- tick
    def tick(self, now: float) -> None:
        for part in (self._tick_focus, self._tick_watching, self._tick_chips, self._tick_greetings,
                     self._tick_wrapup, self._tick_save):
            try:
                part(now)
            except Exception:  # one helper must never break the others (or her)
                log.exception("Day helper %s failed", part.__name__)

    def _tick_focus(self, now: float) -> None:
        if self.focus is not None:
            self._focus_tick(now)

    def _tick_watching(self, now: float) -> None:
        """Every so often: what are you on? (For the day's log, focus nudges and the stuck helper.)"""
        c, s = self.c, self.settings
        fast = self.focusing or c.watch is not None
        if now - self._polled < (FAST_POLL if fast else POLL):
            return
        elapsed = min(now - self._polled, 2 * POLL)
        self._polled = now
        logging_on = s["day_log"]
        stuck_on = c.watch is not None and s["stuck_help"]
        if not (logging_on or self.focusing or stuck_on):
            return
        active = self._active()
        activity = c._read_activity()
        today = self.today()
        if logging_on and active and elapsed > 0:
            label = label_for(activity)
            if label:
                self.log.add_time(today, label, elapsed)
            song = c._read_music()
            if song is not None and song.title != self._song:
                self._song = song.title
                self.log.add_song(today, song.title)
        if self.focusing and s["focus_nudge"] and self.focus.observe(now, activity) and self._free(now):
            left = max(1, int(self.focus.left(now) / 60 + 0.5))
            self._say(now, "focus_drift", "pouty", left=f"{left} min")
        if stuck_on and not self.focusing and self.stuck.observe(now, activity, active) and self._free(now):
            log.info("Stuck helper: offering to look")
            self._say(now, "stuck", "talk")
            self._offer({"Yes, take a look": self._look_at_problem, "I'm okay": lambda: None})

    def _look_at_problem(self) -> None:
        self.c.open_chat_log()
        self.c._on_chat_sent("I'm stuck on this. Can you look at my screen and help me figure out what's wrong "
                             "and what to try?")

    def _tick_chips(self, now: float) -> None:
        if self.chips is not None and self.chips.isVisible() and (
                now > self._chips_until or not self.c.bubble.isVisible()):
            self.chips.hide()

    # ---------------------------------------------------- special days, weather
    def _tick_greetings(self, now: float) -> None:
        s = self.settings
        if now - self._started < GREET_AFTER or self.focusing or not self._active():
            return
        today = self.today()
        if s["special_days"] and self.log.flag(today, "special") is None:
            if not self._free(now):
                return
            self.log.mark(today, "special", self._special_day(now, today) or "none")
            return  # one thing at a time
        city = s["weather_city"].strip()
        if not city:
            return
        if now - self._weather_at >= WEATHER_REFRESH:
            self.fetch_weather(city)
            return
        weather = self.weather
        if weather is None:
            return  # (couldn't get it: tried again in a while)
        if self.log.flag(today, "weather") is None and self._free(now):
            if self._hour() < WEATHER_MORNING_UNTIL:
                self._say_weather(now, weather.line())
            self.log.mark(today, "weather", f"{weather.emoji} {weather.temperature:.0f}° {weather.words}")
            return
        if (weather.rain_hour is not None and not weather.raining and self.log.flag(today, "rain") is None
                and 0 <= weather.rain_hour - self._hour() <= 1 and self._free(now)):
            self.log.mark(today, "rain", True)
            self._say_weather(now, weather.rain_line())

    def _special_day(self, now: float, today: date) -> str | None:
        from .days import special_day

        s = self.settings
        country = system_country() if s["country"] == "auto" else s["country"]
        found = special_day(today, s["birthday"], country, s["region"], s["payday"])
        if found is None:
            return None
        log.info("Special day: %s", found.name)
        if found.kind == "birthday":
            self._say(now, "birthday", "happy", hop=True)
        elif found.kind == "holiday":
            self._say(now, "holiday", "happy", hop=True, name=found.name)
        else:
            self._say(now, found.kind, "happy")
        return found.name

    def _say_weather(self, now: float, text: str) -> None:
        brain = self.c.brain
        brain._say_text(text, now, "talk")
        self.c._apply(now)

    def city_changed(self) -> None:
        self.weather, self._weather_at, self._place = None, -1e9, None

    def fetch_weather(self, city: str, then=None) -> None:
        """(Asks on a background thread.) ``then(ok, weather or error)`` afterwards, if given."""
        if then is not None:
            self._weather_waiting.append(then)
        if self._weather_busy:
            return  # (the answer on its way goes to everyone waiting)
        self._weather_busy = True
        self._weather_at = time.monotonic()
        from .weather import find_place, forecast

        cached = self._place

        def work():
            if self.read_weather is not None:
                return self.read_weather(city), None
            place = cached[1] if cached and cached[0] == city else find_place(city)
            return forecast(place), place

        def done(ok: bool, value) -> None:
            self._weather_busy = False
            if ok:
                self.weather, place = value
                if place is not None:
                    self._place = (city, place)
            else:
                log.info("No weather: %s", value)
            waiting, self._weather_waiting = self._weather_waiting, []
            for callback in waiting:
                callback(ok, value[0] if ok else value)

        self._background().run(work, done)

    # ------------------------------------------------------------------ wrap-up
    def _tick_wrapup(self, now: float) -> None:
        s = self.settings
        if not (s["wrapup"] and s["day_log"]) or self._hour() < s["wrapup_hour"] or self.focusing:
            return
        today = self.today()
        if self.log.flag(today, "wrapup") or not self._active() or not self._free(now):
            return
        if self.log.summary(today)["minutes"] < WRAPUP_MIN_MINUTES:
            return
        self.log.mark(today, "wrapup", True)
        self._say(now, "wrapup", "happy", hop=True)
        self._offer({"Show me": self.open_day, "Later": lambda: None})

    def open_day(self) -> None:
        """Menu › My day (or "Show me" at the wrap-up)."""
        today = self.today()
        summary = self.log.summary(today)
        weather = self.log.flag(today, "weather") or ""
        if self.window is not None:
            self.window.close()
            self.window.deleteLater()
        self.window = DayWindow(self.c, today, summary, weather if weather != "none" else "")
        self.window.open_near(self.c._body_rect(), self.c.companion.available_rect())
        words = self.log.flag(today, "words")
        if words:
            self.window.set_words(words)
        elif summary["minutes"] >= 30:
            self._write_words(today)

    def _write_words(self, today: date) -> None:
        """Her few words about your day (from the chat brain), shown at the top and kept in her diary."""
        c = self.c
        if c.chat.config.needs_key and not c.chat.config.api_key:
            return
        window = self.window
        window.set_words("✍️ Writing about your day...")
        description = self.log.describe(today)
        session = c.chat

        def done(ok: bool, value) -> None:
            if not ok or not value:
                log.info("No wrap-up words: %s", value)
                if window is self.window and window is not None:
                    window.set_words("")
                return
            self.log.mark(today, "words", value)
            if window is self.window and window is not None:
                window.set_words(value)
            if self.settings["remember"] and not c.memory.has_day(today):
                c.memory.add_day(today, value)  # in her diary too

        self._background().run(lambda: session.wrap_up(today, description), done)

    # ---------------------------------------------------------------- bookkeeping
    def note_chat(self) -> None:
        if self.settings["day_log"]:
            self.log.add_chat(self.today())

    def _tick_save(self, now: float) -> None:
        if now - self._saved >= SAVE_EVERY:
            self._saved = now
            self.log.save(self.today())

    def clear_log(self) -> None:
        self.log.clear()
        self.log.save(self.today())

    def shutdown(self) -> None:
        if self.focus is not None and self.focus.focusing:
            self.log.add_focus(self.today(), self.focus.focused_minutes(time.monotonic()), False)
        self.log.save(self.today())
        for window in self.windows():
            window.hide()
