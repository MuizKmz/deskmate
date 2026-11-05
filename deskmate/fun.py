"""Phase 9, "more alive": she dances to your music, your bond grows, she wears outfits, and you
can play little games with her. The Controller calls ``FunHelper.tick()`` with her other ticks;
the rules live in small pure modules (dance, bond, outfits, games).
"""

from __future__ import annotations

import logging
import random
import time
from datetime import date

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .bond import Bond
from .dance import BeatTracker, Groove
from .games import EMOJI, RockPaperScissors, TicTacToe, winning_line
from .glass import GlassWindow, button_style, css, label_style
from .paths import data_dir

log = logging.getLogger(__name__)

MUSIC_POLL = 3.0        # seconds between "is music playing?" checks
METER_MS = 40           # how often the sound level is read while she dances (25 a second)
STOP_AFTER = 2          # music gone for this many checks in a row: stop dancing
DANCE_DEMO = 20.0       # "Dance!" from the menu, with no music: this many seconds
HIDE_SECONDS = 30.0     # hide and seek: how long you have to find her
CHIPS_SECONDS = 30.0
RPS_CHIPS = {"✊ Rock": "rock", "✋ Paper": "paper", "✌️ Scissors": "scissors"}


class TicTacToeWindow(GlassWindow):
    """Tic-tac-toe with her: you're ✕, she's ♡. She plays well, but not perfectly."""

    def __init__(self, controller, on_over):
        pack = controller.pack
        super().__init__("Tic-tac-toe", f"you ✕  vs  {pack.name} ♡", pack.theme, controller.icon.pixmap(96),
                         smooth=pack.meta.get("smooth", True), size=QSize(330, 420))
        self.c = controller
        self.on_over = on_over
        self.game = TicTacToe()
        column = QVBoxLayout(self.body)
        column.setContentsMargins(20, 8, 20, 16)
        self.status = QLabel("Your turn~")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(label_style(10.5, bold=True))
        column.addWidget(self.status)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.cells: list[QPushButton] = []
        font = QFont(self.font())
        font.setPointSize(26)
        font.setBold(True)
        for i in range(9):
            cell = QPushButton("")
            cell.setFixedSize(84, 84)
            cell.setFont(font)
            cell.setCursor(Qt.CursorShape.PointingHandCursor)
            cell.clicked.connect(lambda _=False, i=i: self.play(i))
            grid.addWidget(cell, i // 3, i % 3)
            self.cells.append(cell)
        column.addLayout(grid)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        again = QPushButton("Play again")
        again.setCursor(Qt.CursorShape.PointingHandCursor)
        again.setStyleSheet(button_style(self.accent, True))
        again.clicked.connect(self.restart)
        buttons.addWidget(again)
        column.addLayout(buttons)
        self._paint()

    def _paint(self) -> None:
        a = self.accent
        line = winning_line(self.game.board) or ()
        for i, cell in enumerate(self.cells):
            mark = self.game.board[i]
            cell.setText({"X": "✕", "O": "♡"}.get(mark, ""))
            highlight = i in line
            color = "#F4EEFA" if mark == "X" else css(a.lighter(140))
            cell.setStyleSheet(
                f"QPushButton {{ color: {color}; background: {css(a, 0.45 if highlight else 0.10)};"
                f" border: 1px solid {css(a, 0.55)}; border-radius: 14px; }}"
                f" QPushButton:hover {{ background: {css(a, 0.25)}; }}")
            cell.setEnabled(not mark and self.game.result is None)

    def play(self, cell: int) -> None:
        if self.game.board[cell] or self.game.result is not None:
            return
        self.game.play(cell)
        self._paint()
        result = self.game.result
        if result is None:
            self.status.setText("Your turn~")
            return
        self.status.setText({"X": "You win! 🎉", "O": f"{self.c.pack.name} wins~", "draw": "A draw!"}[result])
        self.on_over({"X": "win", "O": "lose", "draw": "draw"}[result])

    def restart(self) -> None:
        self.game = TicTacToe()
        self.status.setText("Your turn~")
        self._paint()


class FunHelper:
    def __init__(self, controller, folder=None):
        self.c = controller
        self.bond = Bond((folder or data_dir()) / "bond.json")
        self.meter = None  # audiometer.PeakMeter (made when first needed)
        self.read_level = None  # tests: a function returning the sound level (0..1) or None
        self.tracker = BeatTracker()
        self._music_polled = -1e9
        self._music = None
        self._no_music = 0
        self._song = None
        self._demo_until = 0.0
        self._meter_timer = QTimer()
        self._meter_timer.setInterval(METER_MS)
        self._meter_timer.timeout.connect(self._read_meter)
        self.chips = None
        self._chip_actions: dict = {}
        self._chips_until = 0.0
        self.rps: RockPaperScissors | None = None
        self.board: TicTacToeWindow | None = None
        self.hiding: dict | None = None  # hide and seek in progress: {"until", "home"}
        self._outfit_day: date | None = None
        self._visit_day: date | None = None
        self.rng = random.Random()

    # ----------------------------------------------------------------- helpers
    @property
    def character(self) -> str:
        return self.c.pack.id

    def today(self) -> date:
        return self.c.brain.wallclock().date()

    def _say(self, now: float, key: str, expression: str = "talk", hop: bool = False, **values) -> str:
        brain = self.c.brain
        text = brain._line(key, **values) or ""
        if text:
            if hop:
                brain._animations.append("hop")
            brain._say_text(text, now, expression)
            self.c._apply(now)
        return text

    def _offer(self, choices: dict) -> None:
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
        action = self._chip_actions.get(text)
        self._chip_actions = {}
        if action is not None:
            action()

    def windows(self) -> list:
        return [w for w in (self.chips, self.board) if w is not None]

    # -------------------------------------------------------------------- bond
    def level(self):
        return self.bond.level(self.character)

    def add_bond(self, kind: str) -> None:
        """Something you did together (a pat, a chat, a focus session, a game...)."""
        try:
            _gained, up = self.bond.add(self.character, kind, self.today())
        except Exception:
            log.exception("Bond failed")
            return
        self.c.brain.bond_level = self.level().number
        if up is not None:
            QTimer.singleShot(2500, lambda: self._level_up(up))

    def _level_up(self, level) -> None:
        from .outfits import newly_unlocked

        now = time.monotonic()
        log.info("Bond level up: %s", level.describe())
        brain = self.c.brain
        text = brain._line("bond_up", level=level.name) or ""
        new = newly_unlocked(level.number)
        if new:  # one bubble: the level-up and her new things together
            text += " I got something new to wear: " + ", ".join(f"{o.emoji} {o.name}" for o in new) + "!"
        if text:
            brain._animations.append("hop")
            brain._say_text(text.strip(), now, "blush")
            self.c._apply(now)
        self.c._settings_changed()

    def context(self) -> str:
        """For her chat brain."""
        return "\n" + self.bond.prompt(self.character, self.today())

    # ------------------------------------------------------------------ outfits
    def current_outfit(self) -> str | None:
        from .outfits import BY_KEY, seasonal

        s = self.c.settings
        if s["outfit_seasonal"]:
            special = seasonal(self.today(), s["birthday"])
            if special:
                return special
        key = s["outfit"]
        outfit = BY_KEY.get(key)
        if outfit is None or outfit.level == 0 or outfit.level > self.level().number:
            return None  # (not unlocked with this character yet)
        return key

    def apply_outfit(self) -> None:
        self.c.companion.set_outfit(self.current_outfit())
        self._outfit_day = self.today()

    def set_outfit(self, key: str) -> None:
        self.c._set("outfit", key)
        self.apply_outfit()
        if key:
            from .outfits import BY_KEY

            now = time.monotonic()
            self.c.brain._react("happy", now, 2.0)
            self.c.brain._animations.append("hop")
            self.c._apply(now)
            log.info("Outfit: %s", BY_KEY.get(key))

    # -------------------------------------------------------------------- dance
    def _level_now(self) -> float | None:
        if self.read_level is not None:
            return self.read_level()
        if self.meter is None:
            from .audiometer import PeakMeter

            self.meter = PeakMeter()
        return self.meter.level()

    def _read_meter(self) -> None:
        try:
            level = self._level_now()
        except Exception:
            level = None
        if level is not None:
            self.tracker.feed(time.monotonic(), level)

    def can_dance(self, now: float, check_call: bool = True) -> bool:
        """(``check_call``: also look at the window you're on, for a call; not needed every tick.)"""
        c, brain = self.c, self.c.brain
        return (c.companion.isVisible() and not brain.asleep and not brain._dragging
                and not getattr(c.day, "focusing", False) and self.hiding is None
                and not (check_call and c._in_a_call()))

    def dance(self, seconds: float = DANCE_DEMO) -> None:
        """Menu › Play › Dance! (even without music, for a little while)."""
        now = time.monotonic()
        self._demo_until = now + seconds
        if self.c.brain.asleep:
            self.c.brain._wake(now, quiet=True)
        self._start_dancing(now, announce=True)

    def _start_dancing(self, now: float, announce: bool = False) -> None:
        if self.c.companion.dancing:
            return
        self.tracker = BeatTracker()
        self._meter_timer.start()
        level = self._level_now()
        self.c.companion.set_groove(Groove(now, self.tracker if level is not None else None))
        self.c.brain._next_wander = max(self.c.brain._next_wander, now + 60)
        log.info("Dancing (%s)", "to the beat" if level is not None else "steady tempo")
        if announce or self.rng.random() < 0.5:
            self._say(now, "dance", "happy")

    def _stop_dancing(self) -> None:
        if self.c.companion.dancing:
            self.c.companion.set_groove(None)
            log.info("Stopped dancing")
        self._meter_timer.stop()

    def _tick_dance(self, now: float) -> None:
        dancing = self.c.companion.dancing
        if dancing and not self.can_dance(now, check_call=False):
            self._stop_dancing()
            return
        if now < self._demo_until:
            return
        if self._demo_until and now >= self._demo_until:
            self._demo_until = 0.0
            if self._music is None:
                self._stop_dancing()
                return
        if dancing:
            self.c.brain._next_wander = max(self.c.brain._next_wander, now + 30)  # no strolls mid-song
            if self.tracker.loud_at > 0 and not self.tracker.playing(now) and self._music is not None:
                self._stop_dancing()  # the music is paused (the title is still there)
                self._music = None
                return
        if now - self._music_polled < MUSIC_POLL:
            return
        self._music_polled = now
        if not self.c.settings["dance"]:
            if dancing:
                self._stop_dancing()
            return
        music = self.c._read_music()
        if music is None:
            self._no_music += 1
            if dancing and self._no_music >= STOP_AFTER:
                self._music = None
                self._stop_dancing()
            return
        self._no_music = 0
        self._music = music
        if dancing and self.c._in_a_call():
            self._stop_dancing()
            return
        if not dancing and self.can_dance(now):
            self._start_dancing(now)
            if music.title != self._song:
                self._song = music.title
                self.add_bond("dance")

    # -------------------------------------------------------------------- games
    def rock_paper_scissors(self) -> None:
        now = time.monotonic()
        self.rps = RockPaperScissors(self.rng)
        if self.c.brain.asleep:
            self.c.brain._wake(now, quiet=True)
        self._say(now, "rps_start", "happy", hop=True)
        self._offer({label: (lambda move=move: self._rps(move)) for label, move in RPS_CHIPS.items()})

    def _rps(self, move: str) -> None:
        game = self.rps
        if game is None or game.over:
            return
        now = time.monotonic()
        her, result = game.play(move)
        mood = {"win": "pouty", "lose": "happy", "draw": "surprised"}[result]
        text = self.c.brain._line(f"rps_{result}") or ""
        line = f"{EMOJI[her]} {her.title()}! {text} ({game.score()})"
        if game.over:
            won = game.winner == "you"
            line += " " + (self.c.brain._line("rps_you_won" if won else "rps_she_won") or "")
            self.add_bond("game")
            self.rps = None
        self.c.brain._say_text(line.strip(), now, mood)
        self.c._apply(now)
        if game.over:
            self._offer({"Again!": self.rock_paper_scissors, "That's enough": lambda: None})
        else:
            self._offer({label: (lambda m=m: self._rps(m)) for label, m in RPS_CHIPS.items()})

    def tic_tac_toe(self) -> None:
        if self.board is not None:
            self.board.close()
            self.board.deleteLater()
        self.board = TicTacToeWindow(self.c, self._ttt_over)
        self.board.open_near(self.c._body_rect(), self.c.companion.available_rect())
        self._say(time.monotonic(), "ttt_start", "happy")

    def _ttt_over(self, result: str) -> None:
        now = time.monotonic()
        mood = {"win": "pouty", "lose": "happy", "draw": "surprised"}[result]
        self._say(now, f"ttt_{result}", mood, hop=result != "win")
        self.add_bond("game")

    def hide_and_seek(self) -> None:
        """She hides at the edge of your screen, peeking out. Click her within 30 seconds!"""
        companion = self.c.companion
        if self.hiding is not None or not companion.isVisible():
            return
        now = time.monotonic()
        self._stop_dancing()
        self._say(now, "hide_start", "happy")
        home = companion.pos()
        self.hiding = {"until": now + HIDE_SECONDS + 2.5, "home": home, "hidden": False}
        self.c.brain._next_wander = max(self.c.brain._next_wander, now + HIDE_SECONDS + 30)
        QTimer.singleShot(2200, self._hide)

    def _hide(self) -> None:
        companion = self.c.companion
        if self.hiding is None:
            return
        self.c.bubble.dismiss()
        avail = companion.available_rect()
        sprite = companion._sprite_rect_local()  # her body inside the window
        side = self.rng.choice((-1, 1))
        peek = 0.38  # how much of her shows
        if side < 0:
            x = avail.left() - sprite.left() - int(sprite.width() * (1 - peek))
        else:
            x = avail.right() - sprite.left() - int(sprite.width() * peek)
        y = companion.ground_y() if hasattr(companion, "ground_y") else companion.pos().y()
        companion._stop_moving()
        self._fade(companion, 1.0, 0.0, lambda: (companion.move(QPoint(x, y)), self._fade(companion, 0.0, 1.0)))
        self.hiding["hidden"] = True
        log.info("Hide and seek: hiding on the %s", "left" if side < 0 else "right")

    @staticmethod
    def _fade(window, start: float, end: float, then=None) -> None:
        animation = QVariantAnimation(window)
        animation.setDuration(350)
        animation.setStartValue(float(start))
        animation.setEndValue(float(end))
        animation.valueChanged.connect(lambda v: window.setWindowOpacity(float(v)))
        if then is not None:
            animation.finished.connect(then)
        animation.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def on_click(self) -> bool:
        """She was clicked. True if that was for a game (so it isn't a pat)."""
        if self.hiding is None or not self.hiding.get("hidden"):
            return False
        self._found(True)
        return True

    def _found(self, found: bool) -> None:
        hiding, self.hiding = self.hiding, None
        if hiding is None:
            return
        now = time.monotonic()
        companion = self.c.companion
        companion.setWindowOpacity(1.0)
        companion._animate_to(companion.clamped_pos(hiding["home"]))
        if found:
            self._say(now, "hide_found", "blush", hop=True)
            self.add_bond("game")
        else:
            self._say(now, "hide_timeout", "happy", hop=True)
        self._offer({"Again!": self.hide_and_seek, "Later": lambda: None})

    # --------------------------------------------------------------------- tick
    def tick(self, now: float) -> None:
        for part in (self._tick_dance, self._tick_games, self._tick_daily):
            try:
                part(now)
            except Exception:
                log.exception("Fun helper %s failed", part.__name__)

    def _tick_games(self, now: float) -> None:
        if self.chips is not None and self.chips.isVisible() and (
                now > self._chips_until or not self.c.bubble.isVisible()):
            self.chips.hide()
        if self.hiding is not None and now > self.hiding["until"]:
            self._found(False)

    def _tick_daily(self, now: float) -> None:
        today = self.today()
        if self._visit_day != today:
            self._visit_day = today
            self.add_bond("visit")  # (once a day, the bond file knows)
        if self._outfit_day != today:
            self.apply_outfit()  # a new day may bring a party hat (or take it away)

    def switched_character(self) -> None:
        self._stop_dancing()
        self.hiding = None
        self.c.brain.bond_level = self.level().number
        self.apply_outfit()

    def shutdown(self) -> None:
        self._stop_dancing()
        if self.meter is not None:
            self.meter.close()
        if self.hiding is not None:
            self.c.companion.setWindowOpacity(1.0)
            self.c.companion.move(self.c.companion.clamped_pos(self.hiding["home"]))
            self.hiding = None
        for window in self.windows():
            window.hide()

