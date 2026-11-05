"""Start-up and wiring: connects the window, the brain, the bubble and the menus.

Run with ``python -m deskmate`` (or double-click run_deskmate.bat on Windows).

Options:
    --check [FOLDER]     check a character pack (or all of them) and exit
    --character NAME     use a different character folder
    --reset-position     put her back in the corner
    --debug              more detail in the log
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
import time

from . import APP_NAME, __version__
from .character import available_packs, find_pack, format_report, load_pack
from .logsetup import setup_logging
from .paths import character_dirs, characters_dir, data_dir

FOCUS_LENGTHS = (25, 50)  # minutes, in her Focus menu

log = logging.getLogger("deskmate")


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="deskmate", description="A little companion for your desktop.")
    parser.add_argument("--check", nargs="?", const="", metavar="FOLDER",
                        help="check a character pack (or all packs) and exit")
    parser.add_argument("--character", metavar="NAME", help="character folder to use")
    parser.add_argument("--reset-position", action="store_true", help="move her back to the corner")
    parser.add_argument("--debug", action="store_true", help="write more detail to the log")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser.parse_args(argv)


def _log_issues(pack) -> None:
    for issue in pack.issues:
        level = {"error": logging.ERROR, "warning": logging.WARNING}.get(issue.level, logging.INFO)
        log.log(level, "[%s] %s", pack.id, issue.message)


def _check(target: str) -> int:
    from pathlib import Path

    folders = [Path(target)] if target else available_packs(character_dirs())
    if not folders:
        print(f"No character folders found in {characters_dir()}")
        return 1
    worst = 0
    for folder in folders:
        pack = load_pack(folder)
        print(format_report(pack))
        print()
        worst = max(worst, 0 if pack.ok else 1)
    if not target:  # the whole app: are her special days there too? (the built .exe must include them)
        from datetime import date

        from .days import special_day

        merdeka = special_day(date(2026, 8, 31), country="MY")
        print(f"Holidays: {'OK (' + merdeka.name + ')' if merdeka and merdeka.kind == 'holiday' else 'MISSING'}")
        worst = max(worst, 0 if merdeka and merdeka.kind == "holiday" else 1)
    return worst


def native_message(text: str) -> None:
    """A message box that works even when Qt couldn't start."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10)
            return
        except Exception:
            pass
    if sys.stderr is not None:
        print(text, file=sys.stderr)


def safe_main(argv: list[str] | None = None) -> int:
    """main(), but an unexpected crash shows a message instead of vanishing silently."""
    try:
        return main(argv)
    except SystemExit:
        raise
    except Exception:
        logging.getLogger("deskmate").exception("DeskMate stopped because of an unexpected error")
        try:
            where = str(data_dir() / "deskmate.log")
        except Exception:
            where = "the DeskMate data folder"
        native_message(f"DeskMate hit an unexpected problem and had to stop.\n\nDetails are in the log:\n{where}")
        return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = _parse(argv[1:])
    if args.check is not None:
        return _check(args.check)

    data = data_dir()
    log_path = setup_logging(data, debug=args.debug)
    log.info("%s %s starting (Python %s, %s)", APP_NAME, __version__, sys.version.split()[0], sys.platform)

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import autostart
    from .brain import Brain
    from .companion import load_frames
    from .logsetup import install_qt_message_handler
    from .settings import Settings
    from .single_instance import SingleInstance
    from .sysidle import IdleTracker

    # Crisp rendering at 125% / 150% Windows scaling.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # hiding her must not quit the app
    install_qt_message_handler()

    guard = SingleInstance()
    if guard.notify_running_instance():
        log.info("DeskMate is already running; asked it to show itself")
        return 0
    guard.listen()

    settings_path = data / "settings.json"
    first_run = not settings_path.exists()
    settings = Settings(settings_path)
    if args.character:
        settings["character"] = args.character
    if args.reset_position:
        settings["position"] = None

    pack_folder = find_pack(character_dirs(), settings["character"])
    pack = load_pack(pack_folder if pack_folder else characters_dir() / settings["character"])
    _log_issues(pack)
    if pack_folder and pack.id != settings["character"]:
        # Keep the saved choice: if her folder appears later, she's used automatically.
        log.info("Character '%s' not found; using '%s' for now", settings["character"], pack.id)
    frames = load_frames(pack)

    if not pack.ok:
        errors = "\n".join(f"• {i.message}" for i in pack.issues if i.level == "error")
        QMessageBox.warning(
            None,
            APP_NAME,
            f"Some character images have problems:\n\n{errors}\n\n"
            f"DeskMate will still start. Details are in:\n{log_path}",
        )

    brain = Brain(pack.lines, now=time.monotonic(), chatty=settings["chatty"], reminders=settings["reminders"],
                  wander=settings["wander"])

    def cursor_pos() -> tuple[int, int]:
        from PySide6.QtGui import QCursor

        point = QCursor.pos()
        return point.x(), point.y()

    controller = Controller(app, settings, pack, frames, brain, IdleTracker(cursor_pos))
    guard.activated.connect(controller.show_companion)
    autostart.refresh_if_moved()

    # Let Ctrl+C in a console stop DeskMate cleanly.
    try:
        import signal

        signal.signal(signal.SIGINT, lambda *_: controller.quit())
        heartbeat = QTimer(app)
        heartbeat.timeout.connect(lambda: None)
        heartbeat.start(400)
    except (ValueError, OSError):
        pass

    controller.start(first_run=first_run)
    code = app.exec()
    log.info("DeskMate stopped (exit code %s)", code)
    return int(code)


class Controller:
    """Owns the windows and menus, and passes events between them and the brain."""

    TICK_MS = 250
    MISSED_DELAY_MS = 6000  # mention missed reminders after her hello
    UPDATE_FIRST_MS = 20000  # first update check a little after start-up
    DIARY_FIRST_MS = 12000   # yesterday's diary line, a little after start-up
    SETUP_MS = 2500          # first run: the setup window, right after her hello
    WHATS_NEW_MS = 4000      # after an update: what's new, after her hello

    def __init__(self, app, settings, pack, frames, brain, idle):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QSystemTrayIcon

        from .bubble import SpeechBubble
        from .companion import Companion

        self.app = app
        self.settings = settings
        self.pack = pack
        self.brain = brain
        self.idle = idle
        self.companion = Companion(pack, frames, size=settings["size"], on_top=settings["always_on_top"],
                                   gravity=settings["gravity"])
        self.bubble = SpeechBubble(pack.theme)
        self.bubble.keep_while = lambda: self.speaker.talking()  # the words stay while she's still saying them
        self.bubble.set_on_top(settings["always_on_top"])
        self._tooltip = ""
        self._walk_after_landing = False
        self._chat_box = None
        self._chat_log = None
        self._chat_worker = None
        self.watch = None  # buddy mode: set while she watches your screen with you (see start_watching)
        from .activity import foreground, playing
        from .look import grab_screen

        self._read_activity = foreground  # tests swap these three for pretend ones
        self._read_music = playing
        self._grab_screen = grab_screen
        self.chat = self._make_chat()
        from .reminders import ReminderBook

        self.reminders = ReminderBook(data_dir() / "reminders.json")
        from .memory import Memory

        self.memory = Memory(data_dir() / "memory.json")  # about you, so every character shares it
        self._memory_window = None
        self._settings_window = None  # Settings, first-run setup and What's new windows (made when needed)
        self._setup = None
        self._whats_new = None
        self._diary_busy = False
        self.speaker = self._make_speaker()
        from .dayhelper import DayHelper

        self.day = DayHelper(self)  # focus timer, wrap-up, special days, weather, stuck helper
        self._update = None  # a newer release, if GitHub has one
        self._update_worker = None

        self.companion.clicked.connect(self._on_click)
        self.companion.dragStarted.connect(lambda: self._event(self.brain.on_drag_start))
        self.companion.dragEnded.connect(self._on_drag_end)
        self.companion.landed.connect(self._on_landed)
        self.companion.hoverChanged.connect(lambda inside: self.brain.on_hover(time.monotonic(), inside))
        self.companion.menuRequested.connect(self._show_menu)
        self.companion.moved.connect(self._on_moved)

        self.icon = self._make_icon(frames)
        self.menu = self._build_menu()
        app.setWindowIcon(self.icon)
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.icon)
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(self._on_tray)
            self.tray.setToolTip(f"{APP_NAME} - {pack.name}")
            self.tray.show()

        self._tick_timer = QTimer()
        self._tick_timer.timeout.connect(self._tick)
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.settings.save)
        app.aboutToQuit.connect(self._on_about_to_quit)
        # Unplugging a monitor must never strand her off-screen.
        app.screenRemoved.connect(lambda *_: QTimer.singleShot(600, self._rescue))
        app.screenAdded.connect(lambda *_: QTimer.singleShot(600, self._rescue))

    # ----------------------------------------------------------------- start
    def start(self, first_run: bool = False) -> None:
        self._apply_perch()
        self.companion.place(self.settings["position"])
        if self.settings["visible"] or self.tray is None:
            self.companion.show()
            self.companion.settle()  # floating from an earlier session? she drops to the taskbar
        now = time.monotonic()
        from PySide6.QtCore import QTimer

        from . import __version__

        if first_run:
            self.brain.on_first_run(now)  # one-time hello with instructions
            if not self.settings["setup_done"]:
                QTimer.singleShot(self.SETUP_MS, self.start_setup)
        else:
            self.brain.on_start(now)
            seen = self.settings["seen_version"]
            # After an update (not on a brand-new install): what's new. ("" = updated from before 0.7.0.)
            if seen != __version__ and (seen or self.settings["position"] is not None):
                QTimer.singleShot(self.WHATS_NEW_MS, self._announce_update)
        self._set("seen_version", __version__)
        self._tick_timer.start(self.TICK_MS)
        from PySide6.QtCore import QTimer

        self._update_timer = QTimer()
        self._update_timer.setInterval(3600 * 1000)  # look every hour whether a day has passed
        self._update_timer.timeout.connect(self._maybe_check_updates)
        self._update_timer.start()
        QTimer.singleShot(self.UPDATE_FIRST_MS, self._maybe_check_updates)
        QTimer.singleShot(self.DIARY_FIRST_MS, self._write_diary)
        self._apply(now)
        missed = self.reminders.pop_missed()
        if missed:
            from PySide6.QtCore import QTimer

            what = ", ".join(r.text for r in missed[:3]) + (" ..." if len(missed) > 3 else "")
            QTimer.singleShot(self.MISSED_DELAY_MS, lambda: self._event(
                lambda t: self.brain.on_reminder(t, what, missed=True)))

    # ------------------------------------------------------------------ loop
    def _tick(self) -> None:
        now = time.monotonic()
        try:
            self.brain.tick(now, self.idle.seconds())
        except Exception:  # never let one bad tick kill her; it's logged
            log.exception("Brain tick failed")
        self._check_reminders(now)
        if self.chat.previous is not None and not self._diary_busy:
            self._write_diary()  # midnight passed while she was running
        if self.watch is not None:
            try:
                self._watch_tick(now)
            except Exception:  # buddy mode must never break her
                log.exception("Watching failed")
        self.day.tick(now)
        self._apply(now)

    def _apply(self, now: float) -> None:
        visible = self.companion.isVisible()
        self.companion.set_expression(self.brain.expression(now))
        for effect in self.brain.drain_animations():
            if visible:
                self.companion.play(effect)
        for speech in self.brain.drain_speech():
            if visible:
                self.bubble.say(speech.text, speech.duration,
                                self.companion.head_rect_global(), self.companion.available_rect())
                try:
                    spoken = self.speaker.say(speech.text, speech.kind, speech.spoken)
                except Exception:  # her voice must never break her
                    log.exception("Voice failed")
                    spoken = False
                if not spoken:  # no voice: her lips move while the bubble types the words
                    self.companion.set_mouth(self._typing_mouth(speech.text))
        if self.tray is not None:
            tip = f"{self.pack.name} is {self.brain.label(now)}" + (" · watching with you" if self.watch else "")
            if tip != self._tooltip:
                self._tooltip = tip
                self.tray.setToolTip(tip)

    def _event(self, handler) -> None:
        now = time.monotonic()
        handler(now)
        self._apply(now)

    # ------------------------------------------------------------- reactions
    def _on_click(self) -> None:
        self._event(self.brain.on_pet)

    def _on_drag_end(self) -> None:
        self._event(self.brain.on_drag_end)

    def _on_landed(self, impact: float) -> None:
        self._event(lambda now: self.brain.on_landed(now, impact, self.companion.perched))
        self._remember_position()
        if self._walk_after_landing:
            self._walk_after_landing = False
            from PySide6.QtCore import QTimer

            QTimer.singleShot(600, self.take_walk)

    def take_walk(self) -> None:
        """Menu: walk along the taskbar right now."""
        if not self.companion.isVisible():
            self.show_companion()
        if not self.companion.gravity:
            self._say_now("Turn on Gravity first~ I need a floor to walk on!", 3.5)
            return
        if self.companion.falling or not self.companion.on_floor():
            self._walk_after_landing = True  # land first, then go
            self.companion.settle()
            return
        if self.companion.start_wander():
            self._event(self.brain.on_walk_request)

    # ------------------------------------------------------------------- chat
    def _make_chat(self):
        from .chat import KEY_NAMES, MODEL_SETTINGS, ChatConfig, ChatSession, load_key, persona_prompt

        provider = self.settings["chat_provider"]
        config = ChatConfig(
            provider=provider,
            model=self.settings[MODEL_SETTINGS[provider]],
            api_key=load_key(data_dir() / "secrets.json", KEY_NAMES[provider]) if provider in KEY_NAMES else "",
            base_url=self.settings["ollama_url"] if provider == "ollama" else "",
        )
        return ChatSession(config, persona_prompt(self.pack.meta, self.pack.name),
                           path=data_dir() / f"chat_{self.pack.id}.json")

    def open_chat(self) -> None:
        """Menu: open the little chat box next to her."""
        from PySide6.QtCore import QRect

        from .chatbox import Background, ChatBox

        if self.chat.config.needs_key and not self.chat.config.api_key:
            if not self.open_chat_settings():
                return
        if self._chat_log is not None and self._chat_log.isVisible():
            self._chat_log.raise_()
            self._chat_log.activateWindow()
            self._chat_log.edit.setFocus()
            return
        if not self.companion.isVisible():
            self.show_companion()
        if self._chat_box is None:
            self._chat_box = ChatBox(self.pack.name, self.pack.theme)
            self._chat_box.sent.connect(self._on_chat_sent)
            self._chat_box.history_requested.connect(self.open_chat_log)
            self._chat_box.look_requested.connect(self.toggle_watching)
        self._chat_box.set_looking(self.watch is not None)
        if self._chat_worker is None:
            self._chat_worker = Background()
        sprite = self.companion._sprite_rect_local()
        body = QRect(self.companion.mapToGlobal(sprite.topLeft()), sprite.size())
        self._chat_box.open_near(body, self.companion.available_rect())

    def _on_chat_sent(self, text: str) -> None:
        from datetime import datetime

        from .chat import LOOK_TEXT, situation

        watch = self.watch
        activity = self._read_activity() if watch is not None else None
        private = activity is not None and activity.private
        with_picture = watch is not None and watch.picture and not private
        text = text.strip() or (LOOK_TEXT if watch is not None else "")
        if not text:
            return
        now = time.monotonic()
        if watch is not None:
            watch.watcher.hold(now)  # you're talking: no buddy comments for a while
            watch.music.hold(now)
            watch.replies.hide()
        self.brain.on_chat_sent(now)
        self.day.note_chat()
        self._apply(now)
        self.bubble.say("...", 60, self.companion.head_rect_global(), self.companion.available_rect())
        self._set_chat_waiting(True)
        if self._chat_log is not None:
            self._chat_log.add_pending(text, datetime.now().strftime("%H:%M"), image=with_picture)
        worked = (now - self.brain._active_since) / 60.0
        context = situation(datetime.now(), self.brain.label(now), worked) + self._memory_context() + self._voice_context()
        if watch is not None:
            context += "\n" + self._watch_context(activity)
        session = self.chat
        if self._chat_worker is None:  # (e.g. an answer chip tapped before any chat window was opened)
            from .chatbox import Background

            self._chat_worker = Background()

        def ask(image) -> None:
            from .look import snapshot_from

            snapshot = snapshot_from(image) if image is not None else None
            self._chat_worker.run(lambda: session.ask(text, context, snapshot), self._on_chat_reply)

        if with_picture:
            self._capture(ask, activity)
        else:
            ask(None)

    def _on_chat_reply(self, ok: bool, value) -> None:
        from .chat import OFFLINE_LINES, ChatError

        self._set_chat_waiting(False)
        now = time.monotonic()
        if ok:
            mood, reply = value
            from .chat import MODEL_SETTINGS

            key = MODEL_SETTINGS[self.chat.config.provider]
            if not self.settings[key] and self.chat.config.model:
                self._set(key, self.chat.config.model)  # remember the model that was picked for you
            self._reminders_from_chat(now)
            self._memories_from_chat()
        else:
            kind = value.kind if isinstance(value, ChatError) else "server"
            log.warning("Chat failed (%s): %s", kind, getattr(value, "detail", value))
            mood, reply = ("pouty" if kind in ("no_key", "auth", "quota") else "sleepy"), OFFLINE_LINES[kind]
        if ok and self.chat.last_details and (self._chat_log is None or not self._chat_log.isVisible()):
            self.open_chat_log()  # she has steps / an example for you: show them
        elif self._chat_log is not None:
            if ok:
                self._chat_log.set_lines(self.chat.transcript())
            else:  # keep your unanswered message on screen, with her explanation under it
                self._chat_log.add_note(reply)
        self.bubble.dismiss()
        self.brain.on_chat_reply(now, mood, reply, self.chat.last_spoken if ok else "")
        self._apply(now)

    # ---------------------------------------------------------------- memory
    def _memory_context(self) -> str:
        from datetime import date

        return "\n" + self.memory.prompt(date.today()) if self.settings["remember"] else ""

    def _memories_from_chat(self) -> None:
        from datetime import date

        if not self.settings["remember"]:
            return
        for words in self.chat.last_forget:
            log.info("Forgot %d memories (asked in chat)", self.memory.forget(words))
        for fact in self.chat.last_remember:
            if self.memory.remember(fact, date.today()):
                log.info("Remembered something new from chat")
        if (self.chat.last_remember or self.chat.last_forget) and self._memory_window is not None \
                and self._memory_window.isVisible():
            self._refresh_memory_window()

    def _write_diary(self) -> None:
        """One diary line about an earlier day you chatted (yesterday, usually). Quietly does nothing if it can't."""
        from .chatbox import Background

        previous, self.chat.previous = self.chat.previous, None
        if previous is None or self._diary_busy or not self.settings["remember"]:
            return
        day, messages = previous
        if self.memory.has_day(day) or (self.chat.config.needs_key and not self.chat.config.api_key):
            return
        self._diary_busy = True
        if self._chat_worker is None:
            self._chat_worker = Background()
        session = self.chat

        def done(ok: bool, value) -> None:
            self._diary_busy = False
            if ok and value:
                self.memory.add_day(day, value)
                log.info("Diary line written for %s", day)
                if self._memory_window is not None and self._memory_window.isVisible():
                    self._refresh_memory_window()
            elif not ok:
                log.warning("Couldn't write the diary line: %s", value)

        self._chat_worker.run(lambda: session.summarize_day(day, messages), done)

    def _notice_habit(self, slot: str, activity, now: float) -> None:
        """Buddy mode: once you've stayed on something for a while, count it as a habit."""
        from datetime import date

        from .memory import habit_of

        watch = self.watch
        key = activity.key if activity is not None else None
        seen = watch.habits.get(slot)
        if seen is None or seen[0] != key:
            watch.habits[slot] = [key, now, False]
            return
        if not seen[2] and now - seen[1] >= self.HABIT_SECONDS and self.settings["remember"]:
            seen[2] = True
            habit = habit_of(activity)
            if habit is not None:
                self.memory.notice(*habit, date.today())

    def open_memory(self) -> None:
        """Menu: 'What I remember about you'."""
        from .chatbox import MemoryWindow

        if self._memory_window is None:
            self._memory_window = MemoryWindow(self.pack.name, self.pack.theme, self.icon.pixmap(96),
                                               smooth=self.pack.meta.get("smooth", True))
            self._memory_window.removed.connect(self._remove_memory)
            self._memory_window.cleared.connect(self._clear_memory)
        if not self.companion.isVisible():
            self.show_companion()
        self._refresh_memory_window()
        self._memory_window.open_near(self._body_rect(), self.companion.available_rect())

    def _refresh_memory_window(self) -> None:
        from datetime import date

        self._memory_window.show_memory(self.memory, date.today(), self.settings["remember"])

    def _remove_memory(self, section: str, key) -> None:
        self.memory.remove(section, key)
        self._refresh_memory_window()

    def _clear_memory(self) -> None:
        self.memory.clear()
        self._refresh_memory_window()
        self._event(lambda t: self.brain.say(t, "...Huh? Who are you? Ehehe, just kidding~ but it's all gone.",
                                             "surprised"))

    def _set_remember(self, on: bool) -> None:
        self._set("remember", on)
        if self._memory_window is not None and self._memory_window.isVisible():
            self._refresh_memory_window()

    # ------------------------------------------------------------- reminders
    def _check_reminders(self, now: float) -> None:
        due = self.reminders.pop_due()
        if not due:
            return
        what = ", ".join(r.text for r in due)
        log.info("Reminder due: %s", what)
        self.brain.on_reminder(now, what)
        if self.tray is not None and (not self.companion.isVisible() or not self.settings["always_on_top"]):
            self.tray.showMessage(f"{self.pack.name} reminds you", what)

    def _reminders_from_chat(self, now: float) -> None:
        from datetime import datetime

        from .reminders import parse_when

        for when, what in self.chat.last_reminders:
            due = parse_when(when, datetime.now())
            reminder = self.reminders.add(due, what) if due else None
            if reminder is None:
                log.warning("Chat asked for a reminder I couldn't understand: %r %r", when, what)
                self.brain.say(now, "Hmm, I couldn't catch the time for that reminder... "
                                    "could you add it from Reminders in my menu?", "pouty")
            else:
                log.info("Reminder set from chat: %s", reminder.label(datetime.now()))

    def add_reminder_from_text(self, text: str) -> bool:
        """'15:00 meeting', 'in 20 min stretch', 'call mom at 3pm'. Returns False if the time wasn't understood."""
        from datetime import datetime

        from .reminders import parse_request

        now_dt = datetime.now()
        parsed = parse_request(text, now_dt)
        reminder = self.reminders.add(*parsed) if parsed else None
        if reminder is None:
            return False
        when = reminder.label(now_dt).rsplit("  ", 1)[0]
        self._event(lambda now: self.brain.on_reminder_set(now, when))
        return True

    def ask_for_reminder(self) -> None:
        """Menu: Reminders > Add reminder..."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QInputDialog, QLineEdit

        hint = "When, and what?\n\nExamples:   15:00 meeting   ·   in 20 min stretch   ·   call mom at 3pm"
        text = ""
        while True:
            dialog = QInputDialog()
            dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            dialog.setWindowTitle(f"{self.pack.name}: add a reminder")
            dialog.setLabelText(hint)
            dialog.setTextEchoMode(QLineEdit.EchoMode.Normal)
            dialog.setTextValue(text)
            dialog.resize(420, dialog.sizeHint().height())
            if dialog.exec() != QInputDialog.DialogCode.Accepted or not dialog.textValue().strip():
                return
            text = dialog.textValue()
            if self.add_reminder_from_text(text):
                return
            hint = "Hmm, I didn't understand the time. Try like:   15:00 meeting   ·   in 20 min tea   ·   9am standup"

    def _cancel_reminder(self, reminder_id: str, _checked: bool = False) -> None:
        if self.reminders.cancel(reminder_id):
            self._event(lambda now: self.brain.say(now, "Okay, I won't remind you about that.", "talk"))

    def _fill_reminders_menu(self) -> None:
        from datetime import datetime

        from PySide6.QtGui import QAction

        from PySide6.QtGui import QColor

        from .menu_style import icon, style_menu

        ink = QColor(244, 238, 250, 220)
        menu = self.reminders_menu
        menu.clear()
        add = QAction(icon("plus", ink), "Add reminder...", menu)
        add.triggered.connect(self.ask_for_reminder)
        menu.addAction(add)
        menu.addSeparator()
        upcoming = self.reminders.upcoming()
        if not upcoming:
            empty = QAction("No reminders yet (or ask me in chat!)", menu)
            empty.setEnabled(False)
            menu.addAction(empty)
        now = datetime.now()
        for reminder in upcoming:
            sub = menu.addMenu(icon("clock", ink), reminder.label(now))
            style_menu(sub, self.pack.theme, data_dir() / "ui")
            cancel = QAction(icon("eraser", ink), "Cancel this reminder", sub)
            cancel.triggered.connect(functools.partial(self._cancel_reminder, reminder.id))
            sub.addAction(cancel)

    def _set_chat_waiting(self, waiting: bool) -> None:
        for window in (self._chat_box, self._chat_log):
            if window is not None:
                window.set_waiting(waiting)

    def open_chat_log(self) -> None:
        """Menu: today's chat, to scroll back through (and keep chatting in)."""
        from PySide6.QtCore import QRect

        from .chatbox import Background, ChatLogWindow

        if self._chat_log is None:
            self._chat_log = ChatLogWindow(self.pack.name, self.pack.theme, self.icon.pixmap(96),
                                           smooth=self.pack.meta.get("smooth", True))
            self._chat_log.sent.connect(self._on_chat_log_sent)
            self._chat_log.look_requested.connect(self.toggle_watching)
            self._chat_log.look_stopped.connect(self.stop_watching)
        self._chat_log.set_watching(self.watch is not None, self.watch.left(time.monotonic()) if self.watch else "")
        if self._chat_worker is None:
            self._chat_worker = Background()
        if not self.companion.isVisible():
            self.show_companion()
        self._chat_log.set_lines(self.chat.transcript())
        if self._chat_box is not None:
            self._chat_box.hide()  # one chat window at a time
        sprite = self.companion._sprite_rect_local()
        body = QRect(self.companion.mapToGlobal(sprite.topLeft()), sprite.size())
        self._chat_log.open_near(body, self.companion.available_rect())

    def _on_chat_log_sent(self, text: str) -> None:
        if self.chat.config.needs_key and not self.chat.config.api_key and not self.open_chat_settings():
            return
        self._on_chat_sent(text)

    # ---------------------------------------------------- buddy mode (watching)
    WATCH_POLL = 2.0     # seconds between "what are you on?" checks (free: just a window title)
    HABIT_SECONDS = 60   # stay on something this long and it counts toward "what you often do"
    AWAY_SECONDS = 120   # no comments while you're away from the PC

    def toggle_watching(self) -> None:
        """Menu / 👁 button: start watching (asks permission first) or stop."""
        if self.watch is not None:
            self.stop_watching()
        else:
            self.start_watching()

    def start_watching(self) -> bool:
        """Ask permission, then she watches what you do and reacts like a buddy."""
        from .activity import Watcher
        from .look import QuickReplies, WatchBadge, WatchDialog, exclude_from_capture

        if self.watch is not None:
            return True
        if self.chat.config.needs_key and not self.chat.config.api_key and not self.open_chat_settings():
            return False
        dialog = WatchDialog(self.pack.name, self.settings)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        self._set("watch_minutes", dialog.minutes)
        self._set("watch_picture", dialog.with_picture)
        self._set("watch_level", dialog.chattiness)
        now = time.monotonic()
        badge = WatchBadge(self.pack.name, self._accent)
        badge.clicked.connect(self.stop_watching)
        replies = QuickReplies(self._accent)
        replies.chosen.connect(self._on_chat_sent)
        replies.chat_requested.connect(self.open_chat)
        self.watch = _Watch(until=now + dialog.minutes * 60 if dialog.minutes else None,
                            picture=dialog.with_picture, watcher=Watcher.with_chattiness(dialog.chattiness),
                            music=Watcher.for_music(dialog.chattiness), badge=badge, replies=replies)
        self.watch.watcher.hold(now - self.watch.watcher.gap + 45)  # first comment after ~45 s at the earliest
        self.watch.music.hold(now - self.watch.music.gap + 90)
        # Can Windows leave her out of a screen picture? (Checked once; used only while a picture is taken.)
        self.watch.can_exclude = exclude_from_capture(self.companion, True) and exclude_from_capture(self.companion,
                                                                                                    False)
        log.info("Buddy mode on (%s, picture %s, %s; can hide from capture: %s)", dialog.minutes or "no limit",
                 dialog.with_picture, dialog.chattiness, self.watch.can_exclude)
        self._show_watching(now)
        self._event(lambda t: self.brain.say(t, "Yay~ I'll keep you company! Just do your thing, "
                                                "I'll say something if I see something fun.", "happy"))
        return True

    def stop_watching(self, reason: str = "manual") -> None:
        from .look import exclude_from_capture

        watch, self.watch = self.watch, None
        if watch is None:
            return
        for window in self._our_windows() + [watch.badge, watch.replies]:
            exclude_from_capture(window, False)  # (in case it stopped in the middle of a picture)
        for window in (watch.badge, watch.replies):
            window.hide()
            window.deleteLater()
        self._show_watching(time.monotonic())
        log.info("Buddy mode off (%s)", reason)
        if reason == "manual":
            self._event(lambda t: self.brain.say(t, "Okay~ I stopped watching your screen.", "talk"))
        elif reason == "expired":
            self._event(lambda t: self.brain.say(t, "Time's up~ I stopped watching your screen. Call me again anytime!",
                                                 "happy"))

    def _our_windows(self) -> list:
        windows = [self.companion, self.bubble, self._chat_box, self._chat_log] + self.day.windows()
        if self.watch is not None:
            windows += [self.watch.badge, self.watch.replies]
        return [w for w in windows if w is not None]

    def _show_watching(self, now: float) -> None:
        on = self.watch is not None
        left = self.watch.left(now) if on else ""
        if self._chat_log is not None:
            self._chat_log.set_watching(on, left)
        if self._chat_box is not None:
            self._chat_box.set_looking(on)

    def _body_rect(self):
        from PySide6.QtCore import QRect

        sprite = self.companion._sprite_rect_local()
        return QRect(self.companion.mapToGlobal(sprite.topLeft()), sprite.size())

    def _watch_context(self, activity) -> str:
        if activity is None:
            return "They're letting you watch their screen with them."
        if activity.private:
            return "They're letting you watch their screen, but right now it's something private: don't ask about it."
        return f"They're letting you watch their screen with them. Right now they're on: {activity.describe()}."

    def _watch_tick(self, now: float) -> None:
        watch = self.watch
        if watch.until is not None and now >= watch.until:
            self.stop_watching("expired")
            return
        visible = self.companion.isVisible()
        if visible and self.settings["watch_badge"]:
            watch.badge.place(self.companion.head_rect_global())
            watch.badge.set_left(watch.left(now))
            if not watch.badge.isVisible():
                watch.badge.show()
        elif watch.badge.isVisible():
            watch.badge.hide()
        if now - watch.polled < self.WATCH_POLL:
            return
        watch.polled = now
        if self._chat_log is not None and self._chat_log.isVisible():
            self._chat_log.set_watching(True, watch.left(now))
        if watch.replies.isVisible() and (not self.bubble.isVisible() or now > watch.replies_until):
            watch.replies.hide()  # her question is gone: so are the answer chips
        activity = self._read_activity()
        playing = self._read_music()
        target = watch.watcher.observe(now, activity)
        song = watch.music.observe(now, playing)
        self._notice_habit("app", activity, now)
        self._notice_habit("music", playing, now)
        busy = (watch.reacting or (self._chat_worker is not None and self._chat_worker.busy)
                or now < getattr(self.brain, "_chatting_until", 0) or self.day.focusing)
        if busy or not visible or self.brain.asleep or self.idle.seconds() > self.AWAY_SECONDS:
            return
        if target is not None:
            self._react_to(target)
        elif song is not None and not (activity is not None and activity.quiet):
            self._react_to(song)

    def _react_to(self, activity) -> None:
        from datetime import datetime

        from .chat import situation
        from .chatbox import Background
        from .look import snapshot_from

        watch = self.watch
        watch.reacting = True
        if self._chat_worker is None:
            self._chat_worker = Background()
        now = time.monotonic()
        context = (situation(datetime.now(), self.brain.label(now), (now - self.brain._active_since) / 60.0)
                   + self._memory_context() + self._voice_context())
        session = self.chat
        music = activity.kind == "music"
        log.info("Buddy mode: asking her about %s", "the song" if music else activity.app)

        def go(image) -> None:
            snapshot = snapshot_from(image, 1280) if image is not None else None
            self._chat_worker.run(lambda: session.react(activity.describe(), context, snapshot, music),
                                  lambda ok, value: self._on_react(activity, ok, value))

        if watch.picture and not music:  # a song is just its title: no picture needed
            self._capture(go, activity)
        else:
            go(None)

    def _on_react(self, activity, ok: bool, value) -> None:
        from .chat import OFFLINE_LINES, ChatError

        watch = self.watch
        if watch is None:
            return  # stopped while she was thinking
        watch.reacting = False
        now = time.monotonic()
        music = activity.kind == "music"
        watcher, other = (watch.music, watch.watcher) if music else (watch.watcher, watch.music)
        current = self._read_music() if music else self._read_activity()
        if ok and value and (current is None or current.key != activity.key):
            # You've moved on while she was thinking: a comment about the old thing would sound
            # like it's about the new one. Drop it (she'll get a chance to talk about the new one).
            log.info("Buddy mode: dropped a late comment about %s", activity.app)
            watcher.mentioned(now, activity, spoke=False)
            return
        watcher.mentioned(now, activity, spoke=bool(ok and value))
        if not ok:
            kind = value.kind if isinstance(value, ChatError) else "server"
            log.warning("Buddy comment failed (%s): %s", kind, getattr(value, "detail", value))
            if kind == "vision":  # this model can't see: carry on with app names only
                watch.picture = False
                self._event(lambda t: self.brain.say(t, "My eyes don't work with this chat model... "
                                                        "I'll just go by the app names~", "pouty"))
            elif kind in ("no_key", "auth", "quota"):
                self.stop_watching("error")
                self._event(lambda t: self.brain.say(t, OFFLINE_LINES[kind], "pouty"))
            return
        if not value:
            return  # nothing worth saying: she stays quiet
        mood, reply = value
        other.hold(now)  # one comment at a time: the song and the app don't both get one
        self.chat.remember_reaction(activity.describe(), mood, reply, music)
        if self._chat_log is not None and self._chat_log.isVisible():
            self._chat_log.set_lines(self.chat.transcript())
        self.brain.on_buddy_line(now, mood, reply, self.chat.last_spoken)  # not "chatting": she keeps being herself
        self._apply(now)
        if self.chat.last_replies and self.bubble.isVisible():
            from .look import REPLIES_SECONDS

            watch.replies.offer(self.chat.last_replies, self.bubble.geometry(), self.companion.available_rect())
            watch.replies_until = now + REPLIES_SECONDS

    def _capture(self, then, activity=None) -> None:
        """Take a picture of the window you're using (without her in it), then call ``then(image or None)``.

        With the window's position (``activity.bounds``) it's the screen that window is on, cut to
        the window: what you're looking at, not another monitor. Otherwise the screen under the mouse.
        """
        from PySide6.QtCore import QPoint, QRect, QTimer
        from PySide6.QtGui import QCursor, QGuiApplication

        from .look import EXCLUDE_MS, HIDE_MS, crop_to_window, exclude_from_capture
        from .perch import qt_to_logical

        target = None  # the window you're using, in Qt's pixels
        if activity is not None and activity.bounds:
            to_logical = qt_to_logical()
            left, top = to_logical(activity.bounds[0], activity.bounds[1])
            right, bottom = to_logical(activity.bounds[2] - 1, activity.bounds[3] - 1)
            target = QRect(QPoint(round(left), round(top)), QPoint(round(right), round(bottom)))
        screen = ((QGuiApplication.screenAt(target.center()) if target is not None else None)
                  or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen())

        def grab():
            try:
                image = self._grab_screen(screen)
                if image is None or image.isNull():
                    return None
                return crop_to_window(image, screen.geometry(), target) if target is not None else image
            except Exception:
                log.exception("Couldn't take a screen picture")
                return None

        if self.watch is not None and self.watch.can_exclude:
            # Windows leaves her out of screen pictures, but only for this moment: your own
            # screenshots and recordings still show her.
            ours = self._our_windows()
            for window in ours:
                exclude_from_capture(window, True)

            def taken() -> None:
                image = grab()
                for window in ours:
                    exclude_from_capture(window, False)
                then(image)

            QTimer.singleShot(EXCLUDE_MS, taken)
            return
        hidden = [w for w in self._our_windows() if w.isVisible()]
        for window in hidden:
            window.setWindowOpacity(0.0)  # not hide(): she keeps her place, she's just not in the photo

        def later() -> None:
            image = grab()
            for window in hidden:
                window.setWindowOpacity(1.0)
            then(image)

        QTimer.singleShot(HIDE_MS, later)

    # ------------------------------------------------------- settings & welcome
    def open_settings(self, tab: str = "") -> None:
        """Menu: Settings... (one window with tabs)."""
        from .settings_window import SettingsWindow

        if self._settings_window is None:
            self._settings_window = SettingsWindow(self)
        if not self.companion.isVisible():
            self.show_companion()
        self._settings_window.refresh()
        if tab:
            self._settings_window.show_tab(tab)
        self._settings_window.open_near(self._body_rect(), self.companion.available_rect())

    def _settings_changed(self) -> None:
        """Something changed outside the Settings window: show it there too."""
        window = getattr(self, "_settings_window", None)
        if window is not None and window.isVisible():
            window.refresh()

    def start_setup(self) -> None:
        """First run (or Settings › About › Run setup again): the 'let's set me up' window."""
        from .welcome import SetupWizard

        if getattr(self, "_setup", None) is not None and self._setup.isVisible():
            self._setup.raise_()
            return
        if not self.companion.isVisible():
            self.show_companion()
        self._setup = SetupWizard(self)
        self._setup.open_near(self._body_rect(), self.companion.available_rect())

    def show_whats_new(self) -> None:
        from .welcome import WhatsNewWindow

        if not self.companion.isVisible():
            self.show_companion()
        self._whats_new = WhatsNewWindow(self)
        self._whats_new.open_near(self._body_rect(), self.companion.available_rect())

    def _announce_update(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._event(lambda now: self.brain.say(now, "Ehehe~ I got an update! Look what's new~", "happy"))
        self.show_whats_new()

    def open_chat_settings(self) -> bool:
        """Menu: the Chat settings dialog. Returns True if saved."""
        from .chat import KEY_NAMES, MODEL_SETTINGS, load_key, save_key
        from .chatbox import ChatSettingsDialog

        secrets = data_dir() / "secrets.json"
        keys = {name: load_key(secrets, name) for name in KEY_NAMES.values()}
        dialog = ChatSettingsDialog(self.settings, keys, self.pack.name)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        provider = dialog.chosen_provider
        self._set("chat_provider", provider)
        self._set(MODEL_SETTINGS[provider], dialog.chosen_model)
        if provider == "ollama":
            self._set("ollama_url", dialog.url.text().strip() or self.settings["ollama_url"])
        elif dialog.key.text().strip():
            save_key(secrets, dialog.key.text(), KEY_NAMES[provider])
        self.settings.save()
        history = self.chat.history
        self.chat = self._make_chat()
        self.chat.history = history
        self._refresh_voice_key()
        log.info("Chat settings saved (provider %s)", provider)
        return True

    def _forget_chat(self) -> None:
        self.chat.forget()
        if self._chat_log is not None:
            self._chat_log.set_lines([])
        self._event(lambda now: self.brain.on_chat_reply(now, "surprised", "Huh? What were we talking about?"))

    def _on_moved(self) -> None:
        if self.bubble.isVisible():
            self.bubble.reposition(self.companion.head_rect_global(), self.companion.available_rect())
        self._remember_position()

    def _rescue(self) -> None:
        target = self.companion.clamped_pos(self.companion.pos())
        if target != self.companion.pos():
            log.info("Screens changed; moving her back into view")
            self.companion.move(target)

    def _remember_position(self) -> None:
        pos = self.companion.pos()
        self.settings["position"] = [pos.x(), pos.y()]
        self._save_timer.start()

    def _set(self, key: str, value) -> None:
        self.settings[key] = value
        self._save_timer.start()

    # ------------------------------------------------------------------ menu
    def _build_menu(self):
        from PySide6.QtGui import QAction, QColor
        from PySide6.QtWidgets import QMenu

        from .menu_style import Header, accent_of, icon, style_menu

        theme, cache = self.pack.theme, data_dir() / "ui"
        accent = accent_of(theme)
        ink = QColor(244, 238, 250, 220)
        self._accent = accent
        name = self.pack.name

        menu = QMenu()  # also always on top: she is, so her menu must not open behind her
        style_menu(menu, theme, cache)

        def submenu(parent, text, icon_name):
            sub = parent.addMenu(icon(icon_name, ink), text)
            style_menu(sub, theme, cache)
            return sub

        def action(text, slot, icon_name=None, parent=menu):
            act = QAction(text, parent)
            if icon_name:
                act.setIcon(icon(icon_name, ink))
            act.triggered.connect(slot)
            parent.addAction(act)
            return act

        self.menu_header = Header(menu, self.icon.pixmap(96), name, accent, smooth=self.pack.meta.get("smooth", True))
        menu.addSeparator()
        self.act_update = action("Update available...", self.open_update_page, "sparkle")
        self.act_update.setVisible(self._update is not None)
        if self._update is not None:
            self.act_update.setText(f"Update to {self._update.version}...")
        self.act_chat = action(f"Chat with {name}...", self.open_chat, "chat")
        self.act_chat_log = action("Today's chat", self.open_chat_log, "clock")
        self.act_look = action("Watch with me...", self.toggle_watching, "eye")
        self.act_memory = action("What I remember about you", self.open_memory, "heart")
        self.act_talk = action("Talk to me", lambda: self._event(self.brain.on_talk_request), "sparkle")
        self.act_walk = action("Take a walk", self.take_walk, "walk")
        self.focus_menu = submenu(menu, "Focus", "timer")
        self.act_focus = [action(f"Focus {m} minutes", functools.partial(self._start_focus, m), parent=self.focus_menu)
                          for m in FOCUS_LENGTHS]
        self.act_focus_stop = action("Stop focusing", lambda: self.day.stop_focus(), parent=self.focus_menu)
        self.act_day = action("My day", lambda: self.day.open_day(), "chart")
        self.act_sleep = action("Go to sleep", self._toggle_sleep, "moon")
        self.reminders_menu = submenu(menu, "Reminders", "bell")
        self._fill_reminders_menu()
        menu.addSeparator()

        self.character_menu = submenu(menu, "Character", "person")
        self._fill_character_menu()
        self.act_settings = action("Settings...", self.open_settings, "settings")
        menu.addSeparator()

        self.act_toggle = action(f"Hide {name}", self.toggle_visible, "eye-off")
        action("Quit DeskMate", self.quit, "power")
        menu.aboutToShow.connect(self._refresh_menu)
        return menu

    def _mark_choices(self, actions) -> None:
        """A small dot in front of the chosen option (radio-style submenus)."""
        from PySide6.QtGui import QIcon

        from .menu_style import icon

        blank = QIcon()
        for act in actions:
            act.setIcon(icon("dot", self._accent) if act.isChecked() else blank)

    def _rebuild_menu(self) -> None:
        """New character, new colours: build the menu again (after the old one has closed)."""
        old = self.menu
        self.menu = self._build_menu()
        if self.tray is not None:
            self.tray.setContextMenu(self.menu)
        old.deleteLater()

    def _fill_character_menu(self) -> None:
        """List every character folder (re-read each time, so new ones show up without a restart)."""
        from PySide6.QtGui import QAction, QActionGroup

        self.character_menu.clear()
        old_group = getattr(self, "_character_group", None)
        if old_group is not None:
            old_group.deleteLater()
        group = self._character_group = QActionGroup(self.character_menu)
        group.setExclusive(True)
        for folder in available_packs(character_dirs()):
            if not (folder / "idle").is_dir():
                continue
            act = QAction(folder.name.replace("-", " ").replace("_", " ").title(), self.character_menu)
            act.setCheckable(True)
            act.setChecked(folder.name == self.pack.id)
            act.triggered.connect(functools.partial(self.switch_character, folder))
            group.addAction(act)
            self.character_menu.addAction(act)
        self._mark_choices(self.character_menu.actions())
        self.character_menu.setEnabled(bool(self.character_menu.actions()))

    def switch_character(self, folder, _checked: bool = True) -> None:
        from PySide6.QtWidgets import QMessageBox

        from .companion import load_frames

        if folder.name == self.pack.id:
            return
        pack = load_pack(folder)
        _log_issues(pack)
        if not pack.has("idle"):
            QMessageBox.warning(None, APP_NAME, f"{folder.name} has no idle picture, so it can't be used yet.")
            self._fill_character_menu()
            return
        frames = load_frames(pack)
        log.info("Switching character to %s", pack.name)
        self.pack = pack
        self.bubble.dismiss()
        self.bubble.set_theme(pack.theme)
        self.companion.set_pack(pack, frames)
        self.brain.lines = pack.lines
        self.icon = self._make_icon(frames)
        self.app.setWindowIcon(self.icon)
        if self.tray is not None:
            self.tray.setIcon(self.icon)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._rebuild_menu)
        self.stop_watching("switch")  # a new character asks for her own permission
        self._set("character", pack.id)
        self.chat = self._make_chat()
        for attr in ("_chat_box", "_chat_log", "_memory_window", "_settings_window"):
            window = getattr(self, attr)
            if window is not None:
                window.hide()
                window.deleteLater()
                setattr(self, attr, None)
        self._event(self.brain.on_start)

    def _refresh_menu(self) -> None:
        self._fill_character_menu()
        self._fill_reminders_menu()
        from PySide6.QtGui import QColor

        from .menu_style import icon

        ink = QColor(244, 238, 250, 220)
        visible = self.companion.isVisible()
        self.act_toggle.setText(f"Hide {self.pack.name}" if visible else f"Show {self.pack.name}")
        self.act_toggle.setIcon(icon("eye-off" if visible else "eye", ink))
        self.act_chat.setText(f"Chat with {self.pack.name}...")
        self.act_look.setText("Stop watching my screen" if self.watch else "Watch with me...")
        self.act_sleep.setText("Wake up" if self.brain.asleep else "Go to sleep")
        focus = self.day.focus
        self.act_focus_stop.setVisible(focus is not None)
        if focus is not None:
            left = focus.clock(time.monotonic())
            self.act_focus_stop.setText(f"Stop focusing ({left} left)" if focus.focusing else f"End the break ({left})")
        self.act_sleep.setIcon(icon("sun" if self.brain.asleep else "moon", ink))
        count = len(self.reminders.upcoming())
        status = self.brain.label(time.monotonic()) if visible else "hiding"
        if self.day.focusing:
            status = "focusing with you"
        if count:
            status += f"  ·  {count} reminder{'s' if count > 1 else ''}"
        self.menu_header.set_text(self.pack.name, status)

    def _show_menu(self, global_pos) -> None:
        self.menu.popup(global_pos)

    def _on_tray(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

    def _start_focus(self, minutes: int, _checked: bool = False) -> None:
        self.day.start_focus(minutes)

    def _toggle_sleep(self) -> None:
        now = time.monotonic()
        self.brain.set_manual_sleep(now, not self.brain.asleep)
        self._apply(now)

    def _set_size(self, size: str, _checked: bool = True) -> None:
        self.companion.set_size(size)
        self._set("size", size)
        self._remember_position()

    def _set_on_top(self, on: bool) -> None:
        self.companion.set_on_top(on)
        self.bubble.set_on_top(on)
        self._set("always_on_top", bool(on))

    def _set_chatty(self, on: bool) -> None:
        self.brain.chatty = bool(on)
        self._set("chatty", bool(on))

    def _set_gravity(self, on: bool) -> None:
        self.companion.set_gravity(bool(on))
        self._set("gravity", bool(on))

    def _set_wander(self, on: bool) -> None:
        self.brain.wander = bool(on)
        self._set("wander", bool(on))

    def _make_speaker(self):
        from .chat import ChatConfig, load_key
        from .chatbox import Background
        from .voice import OpenAIVoice, PackVoice, Speaker, WindowsVoice

        self._voice_worker = Background()
        if self.settings["tts_source"] == "builtin":  # the voice pack, started when she first speaks
            natural = PackVoice(self.voice_pack(), voice=self.settings["openai_voice"])
        else:
            if self.settings["tts_source"] == "local":  # your own server (e.g. Kokoro): no key, its own voices
                config = ChatConfig(provider="local", base_url=self.settings["tts_url"])
                model = ""
            else:
                config = ChatConfig(provider="openai", api_key=load_key(data_dir() / "secrets.json"))
                model = self.settings["tts_model"]
            natural = OpenAIVoice(config, voice=self.settings["openai_voice"], model=model)
            if getattr(self, "_voice_pack", None) is not None:
                self._voice_pack.stop()  # not using the pack any more
        return Speaker(WindowsVoice(name=self.settings["windows_voice"]), natural, self._voice_worker.run,
                       mode=self.settings["voice"], everything=self.settings["voice_lines"] == "all",
                       hush=self._in_a_call, language=self._spoken_language, translate=self._translate_line,
                       on_mouth=lambda mouth: self.companion.set_mouth(mouth))

    def voice_pack(self):
        """The built-in voice pack (made when first needed; it only *runs* while she uses it)."""
        from .voicepack import VoicePack

        if getattr(self, "_voice_pack", None) is None:
            self._voice_pack = VoicePack(data_dir() / "voicepack")
        return self._voice_pack

    def _natural_label(self) -> str:
        return {"local": "Natural voice (your own server)", "builtin": "Natural voice (built-in voice pack)"}.get(
            self.settings["tts_source"], "Natural voice (OpenAI)")

    def _refresh_voice_key(self) -> None:
        from .chat import load_key

        if self.speaker.openai is not None and not self.speaker.openai.own_server:
            self.speaker.openai.config.api_key = load_key(data_dir() / "secrets.json")

    def open_voice_settings(self) -> bool:
        """Menu: Voice › Voice settings. Pick a Windows voice, and where the Natural voice comes from."""
        from .chat import load_key
        from .chatbox import VoiceSettingsDialog

        dialog = VoiceSettingsDialog(self.settings, load_key(data_dir() / "secrets.json"), self.pack.name,
                                     voice_pack=self.voice_pack())
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        if dialog.chosen_source != self.settings["tts_source"] or dialog.chosen_url != self.settings["tts_url"]:
            self._set("tts_model", "")  # a different server has different models
        self._set("windows_voice", dialog.chosen_windows_voice)
        self._set("windows_voice_lang", dialog.chosen_windows_culture)
        self._set("voice_translate", dialog.translate.isChecked())
        self._set("tts_source", dialog.chosen_source)
        if dialog.chosen_url:
            self._set("tts_url", dialog.chosen_url)
        if dialog.chosen_voice:
            self._set("openai_voice", dialog.chosen_voice[:79])
        self.settings.save()
        self.speaker.stop()
        self.speaker = self._make_speaker()
        self._settings_changed()
        log.info("Voice settings saved (natural voice from %s)", dialog.chosen_source)
        if self.settings["voice"] != "off":
            self.speaker.say("Hehe, how do I sound now~?", "chat")
        return True

    def _set_voice(self, mode: str, _checked: bool = True) -> None:
        self._set("voice", mode)
        self.speaker.stop()
        self.speaker.mode = mode
        self._refresh_voice_key()
        self._settings_changed()
        if mode == "openai" and not self.speaker.openai.own_server and not self.speaker.openai.config.api_key:
            self._event(lambda now: self.brain.say(now, "I need your OpenAI key for that voice... "
                                                        "add it in Settings, Chat settings~", "pouty"))
            return
        if mode != "off":
            lines = {"windows": "Can you hear me now?", "openai": "Hehe, how do I sound~?"}
            self.speaker.say(lines[mode], "chat")  # a quick sample, even if she only reads chat

    def _set_voice_lines(self, which: str, _checked: bool = True) -> None:
        self._set("voice_lines", which)
        self.speaker.everything = which == "all"
        self._settings_changed()

    def _spoken_language(self) -> str:
        """The language her voice speaks, if she should say her lines in it ("" = just say the English)."""
        from .voice import culture_language, voice_language

        if not self.settings["voice_translate"]:
            return ""
        mode = self.settings["voice"]
        if mode == "openai" and self.settings["tts_source"] in ("local", "builtin"):
            language = voice_language(self.settings["openai_voice"])
        elif mode == "windows":
            language = culture_language(self.settings["windows_voice_lang"])
        else:
            language = ""
        return "" if "English" in language else language

    def _translate_line(self, text: str, language: str) -> str:
        """(Background thread.) One of her lines in her voice's language; each line is translated only once."""
        import json
        import threading

        if not hasattr(self, "_translations"):
            self._translations_lock = threading.Lock()
            path = data_dir() / "voice_lines.json"
            try:
                self._translations = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            except (OSError, ValueError):
                self._translations = {}
        kana = self._kana_only()
        key = f"{language}{' (kana)' if kana else ''}|{text}"
        with self._translations_lock:
            if key in self._translations:
                return self._translations[key]
        line = self.chat.translate(text, language, kana)
        if line:
            with self._translations_lock:
                self._translations[key] = line
                if len(self._translations) > 800:  # keep it small: forget the oldest
                    self._translations = dict(list(self._translations.items())[-600:])
                try:
                    (data_dir() / "voice_lines.json").write_text(
                        json.dumps(self._translations, ensure_ascii=False, indent=0), encoding="utf-8")
                except OSError:
                    log.warning("Couldn't save the translated lines", exc_info=True)
        return line

    def _voice_context(self) -> str:
        from .chat import spoken_prompt

        language = self._spoken_language()
        return "\n" + spoken_prompt(language, self._kana_only()) if language else ""

    def _kana_only(self) -> bool:
        """The voice pack reads Japanese kana only (no kanji): ask her brain for kana."""
        return self.settings["voice"] == "openai" and self.settings["tts_source"] == "builtin"

    def _in_a_call(self) -> bool:
        """You're in a Teams / Zoom / Meet call right now: she doesn't talk out loud (just shows the text)."""
        activity = self._read_activity()
        return activity is not None and activity.quiet

    def _say_now(self, text: str, seconds: float) -> None:
        """A quick line from the app itself (not from her brain): bubble and voice, like her other lines."""
        self.bubble.say(text, seconds, self.companion.head_rect_global(), self.companion.available_rect())
        try:
            spoken = self.speaker.say(text, "line")
        except Exception:
            log.exception("Voice failed")
            spoken = False
        if not spoken:
            self.companion.set_mouth(self._typing_mouth(text))

    @staticmethod
    def _typing_mouth(text: str):
        from .bubble import SpeechBubble
        from .voice import Mouth

        return Mouth(until=time.monotonic() + len(text) * SpeechBubble.TYPE_MS / 1000.0 + 0.1)

    # --------------------------------------------------------------- updates
    def _maybe_check_updates(self) -> None:
        from .updates import CHECK_EVERY

        if getattr(self, "_closed", False):
            return
        if self.settings["update_check"] and time.time() - self.settings["last_update_check"] >= CHECK_EVERY:
            self.check_for_updates()

    def check_for_updates(self, manual: bool = False, check=None) -> None:
        """Ask GitHub (on a thread) whether a newer DeskMate is out."""
        from . import __version__
        from .chatbox import Background
        from .updates import check as default_check

        if self._update_worker is None:
            self._update_worker = Background()
        ask = check or default_check
        self._update_worker.run(lambda: ask(__version__), lambda ok, value: self._on_update_checked(ok, value, manual))

    def _on_update_checked(self, ok: bool, value, manual: bool) -> None:
        if not ok:
            log.info("Update check failed: %s", value)
            if manual:
                self._event(lambda now: self.brain.say(now, "I couldn't reach GitHub... let's try again later?", "pouty"))
            return
        self._set("last_update_check", time.time())
        if value is None:
            if manual:
                self._event(lambda now: self.brain.say(now, "I'm already the newest me~", "happy"))
            return
        self._update = value
        self.act_update.setText(f"Update to {value.version}...")
        self.act_update.setVisible(True)
        log.info("A newer DeskMate is out: %s", value.version)
        if manual or self.settings["update_announced"] != value.version:
            self._set("update_announced", value.version)
            self._event(lambda now: self.brain.say(
                now, f"A new me is out! (v{value.version}) Right-click me and pick Update to get it~", "wave"))

    def open_update_page(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from .updates import RELEASES_PAGE

        QDesktopServices.openUrl(QUrl(self._update.url if self._update else RELEASES_PAGE))

    def _set_update_check(self, on: bool) -> None:
        self._set("update_check", bool(on))

    def _set_perch(self, on: bool) -> None:
        self._set("perch", bool(on))
        self._apply_perch()

    def _apply_perch(self) -> None:
        """Let her sit on window tops (Windows only, and only if switched on)."""
        from . import perch

        source = None
        if perch.supported() and self.settings["perch"]:
            try:
                source = perch.WindowsLedges(perch.qt_to_logical())
            except Exception:
                log.exception("Can't read the window list; she'll stay on the taskbar")
        self.companion.set_ledge_source(source)

    def _set_reminders(self, on: bool) -> None:
        self.brain.reminders = bool(on)
        self._set("reminders", bool(on))

    def _set_autostart(self, on: bool) -> None:
        from . import autostart

        if not autostart.set_enabled(bool(on)):
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(None, APP_NAME, "Couldn't change 'Start with Windows'. Details are in the log.")

    def _open_data_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))

    # ------------------------------------------------------------ visibility
    def toggle_visible(self) -> None:
        if self.companion.isVisible():
            self.bubble.dismiss()
            self.companion.hide()
            self._set("visible", False)
        else:
            self.show_companion()

    def show_companion(self) -> None:
        if not self.companion.isVisible():
            self.companion.move(self.companion.clamped_pos(self.companion.pos()))
            self.companion.show()
            self.companion.settle()
            self._set("visible", True)
        self.companion.raise_()
        self._event(self.brain.on_talk_request if not self.brain.asleep else self.brain.on_pet)

    # ------------------------------------------------------------------ quit
    def quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.quit()

    def _on_about_to_quit(self) -> None:
        self._closed = True
        if getattr(self, "_update_timer", None) is not None:
            self._update_timer.stop()
        self._tick_timer.stop()
        self._save_timer.stop()
        self.settings.save()
        self.bubble.dismiss()
        self.stop_watching("quit")
        try:
            self.day.shutdown()  # (writes the day's log)
        except Exception:
            log.exception("Couldn't save the day's log")
        for window in (self._chat_box, self._chat_log, self._memory_window, getattr(self, "_settings_window", None),
                       getattr(self, "_setup", None), getattr(self, "_whats_new", None)):
            if window is not None:
                window.hide()
        if getattr(self, "_voice_pack", None) is not None:
            self._voice_pack.stop()
        try:
            self.speaker.stop()
            if (self.speaker.openai is not None and not self.speaker.openai.own_server and self.speaker.openai.model
                    and not self.settings["tts_model"]):
                self.settings["tts_model"] = self.speaker.openai.model
                self.settings.save()
        except Exception:
            log.exception("Couldn't stop her voice")
        if self.tray is not None:
            self.tray.hide()

    # ------------------------------------------------------------------ icon
    def _make_icon(self, frames):
        from PySide6.QtCore import QRect, Qt
        from PySide6.QtGui import QIcon, QPixmap

        image = frames["idle"][0]
        hx, hy, top = self.pack.head
        cx, cy = hx * image.width(), hy * image.height()
        half = max(8.0, (cy - top * image.height()) * 1.25)
        box = QRect(int(cx - half), int(cy - half), int(2 * half), int(2 * half)).intersected(image.rect())
        face = image.copy(box)
        if face.isNull() or face.width() < 4:
            face = image
        icon = QIcon()
        how = (Qt.TransformationMode.SmoothTransformation if self.pack.meta.get("smooth", True)
               else Qt.TransformationMode.FastTransformation)  # pixel art: keep the pixels sharp
        for size in (16, 20, 24, 32, 48, 64, 128, 256):
            icon.addPixmap(QPixmap.fromImage(face.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, how)))
        return icon


class _Watch:
    """Buddy mode's state while it's on."""

    def __init__(self, until, picture: bool, watcher, music, badge, replies):
        self.until = until          # time.monotonic() when it ends, or None (until you stop it)
        self.picture = picture      # may she see the screen itself, or only app names?
        self.watcher = watcher      # activity.Watcher: decides when a comment about what you do is due
        self.music = music          # ...and one for the songs that play
        self.badge = badge          # the little 👁 sign by her head
        self.replies = replies      # answer chips under her questions
        self.replies_until = 0.0
        self.can_exclude = False    # Windows can leave her out of a screen picture
        self.reacting = False       # waiting for her brain's comment
        self.polled = -1e9
        self.habits = {}            # "app" / "music" -> [key, since, counted]

    def left(self, now: float) -> str:
        if self.until is None:
            return ""
        minutes = max(0, int((self.until - now) / 60 + 0.99))
        return f"{minutes} min left"
