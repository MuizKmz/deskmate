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
        self.bubble.set_on_top(settings["always_on_top"])
        self._tooltip = ""
        self._walk_after_landing = False
        self._chat_box = None
        self._chat_worker = None
        self.chat = self._make_chat()
        from .reminders import ReminderBook

        self.reminders = ReminderBook(data_dir() / "reminders.json")

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
        self.companion.place(self.settings["position"])
        if self.settings["visible"] or self.tray is None:
            self.companion.show()
            self.companion.settle()  # floating from an earlier session? she drops to the taskbar
        now = time.monotonic()
        if first_run:
            self.brain.on_first_run(now)  # one-time hello with instructions
        else:
            self.brain.on_start(now)
        self._tick_timer.start(self.TICK_MS)
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
        if self.tray is not None:
            tip = f"{self.pack.name} is {self.brain.label(now)}"
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
        self._event(lambda now: self.brain.on_landed(now, impact))
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
            self.bubble.say("Turn on Gravity first~ I need a floor to walk on!", 3.5,
                            self.companion.head_rect_global(), self.companion.available_rect())
            return
        if self.companion.falling or not self.companion.on_floor():
            self._walk_after_landing = True  # land first, then go
            self.companion.settle()
            return
        if self.companion.start_wander():
            self._event(self.brain.on_walk_request)

    # ------------------------------------------------------------------- chat
    def _make_chat(self):
        from .chat import ChatConfig, ChatSession, load_key, persona_prompt

        ollama = self.settings["chat_provider"] == "ollama"
        config = ChatConfig(
            provider=self.settings["chat_provider"],
            model=self.settings["ollama_model" if ollama else "chat_model"],
            api_key="" if ollama else load_key(data_dir() / "secrets.json"),
            base_url=self.settings["ollama_url"] if ollama else "",
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
        if not self.companion.isVisible():
            self.show_companion()
        if self._chat_box is None:
            self._chat_box = ChatBox(self.pack.name, self.pack.theme)
            self._chat_box.sent.connect(self._on_chat_sent)
        if self._chat_worker is None:
            self._chat_worker = Background()
        sprite = self.companion._sprite_rect_local()
        body = QRect(self.companion.mapToGlobal(sprite.topLeft()), sprite.size())
        self._chat_box.open_near(body, self.companion.available_rect())

    def _on_chat_sent(self, text: str) -> None:
        from datetime import datetime

        from .chat import situation

        now = time.monotonic()
        self.brain.on_chat_sent(now)
        self._apply(now)
        self.bubble.say("...", 60, self.companion.head_rect_global(), self.companion.available_rect())
        self._chat_box.set_waiting(True)
        worked = (now - self.brain._active_since) / 60.0
        context = situation(datetime.now(), self.brain.label(now), worked)
        session = self.chat
        self._chat_worker.run(lambda: session.ask(text, context), self._on_chat_reply)

    def _on_chat_reply(self, ok: bool, value) -> None:
        from .chat import OFFLINE_LINES, ChatError

        if self._chat_box is not None:
            self._chat_box.set_waiting(False)
        now = time.monotonic()
        if ok:
            mood, reply = value
            key = "ollama_model" if self.chat.config.provider == "ollama" else "chat_model"
            if not self.settings[key] and self.chat.config.model:
                self._set(key, self.chat.config.model)  # remember the model that was picked for you
            self._reminders_from_chat(now)
        else:
            kind = value.kind if isinstance(value, ChatError) else "server"
            log.warning("Chat failed (%s): %s", kind, getattr(value, "detail", value))
            mood, reply = ("pouty" if kind in ("no_key", "auth", "quota") else "sleepy"), OFFLINE_LINES[kind]
        self.bubble.dismiss()
        self.brain.on_chat_reply(now, mood, reply)
        self._apply(now)

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

    def open_chat_settings(self) -> bool:
        """Menu: the Chat settings dialog. Returns True if saved."""
        from .chat import load_key, save_key
        from .chatbox import ChatSettingsDialog

        secrets = data_dir() / "secrets.json"
        dialog = ChatSettingsDialog(self.settings, load_key(secrets), self.pack.name)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        provider = dialog.chosen_provider
        self._set("chat_provider", provider)
        if provider == "ollama":
            self._set("ollama_url", dialog.url.text().strip() or self.settings["ollama_url"])
            self._set("ollama_model", dialog.chosen_model)
        else:
            self._set("chat_model", dialog.chosen_model)
            if dialog.key.text().strip():
                save_key(secrets, dialog.key.text())
        self.settings.save()
        history = self.chat.history
        self.chat = self._make_chat()
        self.chat.history = history
        log.info("Chat settings saved (provider %s)", provider)
        return True

    def _forget_chat(self) -> None:
        self.chat.forget()
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
        from PySide6.QtGui import QAction, QActionGroup, QColor
        from PySide6.QtWidgets import QMenu

        from . import autostart
        from .menu_style import Header, accent_of, icon, style_menu, switch_icon
        from .settings import SIZES

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

        def toggle(text, slot, checked, parent):
            act = QAction(text, parent)
            act.setCheckable(True)
            act.setChecked(checked)
            act.setIcon(switch_icon(checked, accent))
            act.toggled.connect(lambda on: act.setIcon(switch_icon(on, accent)))
            act.toggled.connect(slot)
            parent.addAction(act)
            return act

        self.menu_header = Header(menu, self.icon.pixmap(96), name, accent, smooth=self.pack.meta.get("smooth", True))
        menu.addSeparator()
        self.act_chat = action(f"Chat with {name}...", self.open_chat, "chat")
        self.act_talk = action("Talk to me", lambda: self._event(self.brain.on_talk_request), "sparkle")
        self.act_walk = action("Take a walk", self.take_walk, "walk")
        self.act_sleep = action("Go to sleep", self._toggle_sleep, "moon")
        self.reminders_menu = submenu(menu, "Reminders", "bell")
        self._fill_reminders_menu()
        menu.addSeparator()

        self.character_menu = submenu(menu, "Character", "person")
        self._fill_character_menu()
        size_menu = submenu(menu, "Size", "size")
        group = QActionGroup(size_menu)
        group.setExclusive(True)
        self._size_actions = {}
        for key in SIZES:
            act = QAction(key.title(), size_menu)
            act.setCheckable(True)
            act.setChecked(key == self.settings["size"])
            act.triggered.connect(functools.partial(self._set_size, key))
            group.addAction(act)
            size_menu.addAction(act)
            self._size_actions[key] = act
        self._mark_choices(self._size_actions.values())

        settings = self.settings_menu = submenu(menu, "Settings", "settings")
        self.act_top = toggle("Always on top", self._set_on_top, self.settings["always_on_top"], settings)
        self.act_chatty = toggle("Chit-chat now and then", self._set_chatty, self.settings["chatty"], settings)
        self.act_gravity = toggle("Gravity (falls to the taskbar)", self._set_gravity, self.settings["gravity"],
                                  settings)
        self.act_wander = toggle("Wander around", self._set_wander, self.settings["wander"], settings)
        self.act_care = toggle("Care reminders (water, breaks, bedtime)", self._set_reminders,
                               self.settings["reminders"], settings)
        self.act_autostart = None
        if autostart.supported():
            self.act_autostart = toggle("Start with Windows", self._set_autostart, autostart.is_enabled(), settings)
        settings.addSeparator()
        action("Chat settings...", self.open_chat_settings, "key", settings)
        action("Forget today's chat", self._forget_chat, "eraser", settings)
        action("Move back to the corner", self.companion.reset_position, "corner", settings)
        action("Open settings && logs folder", self._open_data_folder, "folder", settings)
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
        self._set("character", pack.id)
        self.chat = self._make_chat()
        if self._chat_box is not None:
            self._chat_box.hide()
            self._chat_box.deleteLater()
            self._chat_box = None
        self._event(self.brain.on_start)

    def _refresh_menu(self) -> None:
        from . import autostart

        self._fill_character_menu()
        self._fill_reminders_menu()
        from PySide6.QtGui import QColor

        from .menu_style import icon

        ink = QColor(244, 238, 250, 220)
        visible = self.companion.isVisible()
        self.act_toggle.setText(f"Hide {self.pack.name}" if visible else f"Show {self.pack.name}")
        self.act_toggle.setIcon(icon("eye-off" if visible else "eye", ink))
        self.act_chat.setText(f"Chat with {self.pack.name}...")
        self.act_sleep.setText("Wake up" if self.brain.asleep else "Go to sleep")
        self.act_sleep.setIcon(icon("sun" if self.brain.asleep else "moon", ink))
        count = len(self.reminders.upcoming())
        status = self.brain.label(time.monotonic()) if visible else "hiding"
        if count:
            status += f"  ·  {count} reminder{'s' if count > 1 else ''}"
        self.menu_header.set_text(self.pack.name, status)
        self._mark_choices(self._size_actions.values())
        if self.act_autostart is not None:
            from .menu_style import switch_icon

            self.act_autostart.blockSignals(True)
            self.act_autostart.setChecked(autostart.is_enabled())
            self.act_autostart.setIcon(switch_icon(self.act_autostart.isChecked(), self._accent))
            self.act_autostart.blockSignals(False)

    def _show_menu(self, global_pos) -> None:
        self.menu.popup(global_pos)

    def _on_tray(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

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
        self._tick_timer.stop()
        self._save_timer.stop()
        self.settings.save()
        self.bubble.dismiss()
        if self._chat_box is not None:
            self._chat_box.hide()
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
