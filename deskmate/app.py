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
from .paths import characters_dir, data_dir

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

    folders = [Path(target)] if target else available_packs(characters_dir())
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

    pack_folder = find_pack(characters_dir(), settings["character"])
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

        self.companion.clicked.connect(self._on_click)
        self.companion.dragStarted.connect(lambda: self._event(self.brain.on_drag_start))
        self.companion.dragEnded.connect(self._on_drag_end)
        self.companion.landed.connect(self._on_landed)
        self.companion.hoverChanged.connect(lambda inside: self.brain.on_hover(time.monotonic(), inside))
        self.companion.menuRequested.connect(self._show_menu)
        self.companion.moved.connect(self._on_moved)

        self.menu = self._build_menu()
        self.icon = self._make_icon(frames)
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

    # ------------------------------------------------------------------ loop
    def _tick(self) -> None:
        now = time.monotonic()
        try:
            self.brain.tick(now, self.idle.seconds())
        except Exception:  # never let one bad tick kill her; it's logged
            log.exception("Brain tick failed")
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
        from PySide6.QtGui import QAction, QActionGroup
        from PySide6.QtWidgets import QMenu

        from . import autostart
        from .settings import SIZES

        from PySide6.QtCore import Qt

        menu = QMenu()
        # She's always on top, so her menu must be too (or it could open behind her).
        menu.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        name = self.pack.name

        def action(text, slot, checkable=False, checked=False, parent=menu):
            act = QAction(text, parent)
            act.setCheckable(checkable)
            if checkable:
                act.setChecked(checked)
                act.toggled.connect(slot)
            else:
                act.triggered.connect(slot)
            parent.addAction(act)
            return act

        self.act_toggle = action(f"Hide {name}", self.toggle_visible)
        self.act_talk = action("Talk to me", lambda: self._event(self.brain.on_talk_request))
        self.act_walk = action("Take a walk", self.take_walk)
        self.act_sleep = action("Go to sleep", self._toggle_sleep)
        menu.addSeparator()

        self.character_menu = menu.addMenu("Character")
        self._fill_character_menu()
        size_menu = menu.addMenu("Size")
        group = QActionGroup(size_menu)
        group.setExclusive(True)
        for key in SIZES:
            act = QAction(key.title(), size_menu)
            act.setCheckable(True)
            act.setChecked(key == self.settings["size"])
            act.triggered.connect(functools.partial(self._set_size, key))
            group.addAction(act)
            size_menu.addAction(act)

        self.act_top = action("Always on top", self._set_on_top, True, self.settings["always_on_top"])
        self.act_chatty = action("Chit-chat now and then", self._set_chatty, True, self.settings["chatty"])
        self.act_gravity = action("Gravity (falls to the taskbar)", self._set_gravity, True, self.settings["gravity"])
        self.act_wander = action("Wander around", self._set_wander, True, self.settings["wander"])
        self.act_care = action("Care reminders (water && breaks)", self._set_reminders, True,
                               self.settings["reminders"])
        self.act_autostart = None
        if autostart.supported():
            self.act_autostart = action("Start with Windows", self._set_autostart, True, autostart.is_enabled())
        menu.addSeparator()
        action("Move back to the corner", self.companion.reset_position)
        action("Open settings && logs folder", self._open_data_folder)
        menu.addSeparator()
        action("Quit DeskMate", self.quit)
        menu.aboutToShow.connect(self._refresh_menu)
        return menu

    def _fill_character_menu(self) -> None:
        """List every character folder (re-read each time, so new ones show up without a restart)."""
        from PySide6.QtGui import QAction, QActionGroup

        self.character_menu.clear()
        old_group = getattr(self, "_character_group", None)
        if old_group is not None:
            old_group.deleteLater()
        group = self._character_group = QActionGroup(self.character_menu)
        group.setExclusive(True)
        for folder in available_packs(characters_dir()):
            if not (folder / "idle").is_dir():
                continue
            act = QAction(folder.name.replace("-", " ").replace("_", " ").title(), self.character_menu)
            act.setCheckable(True)
            act.setChecked(folder.name == self.pack.id)
            act.triggered.connect(functools.partial(self.switch_character, folder))
            group.addAction(act)
            self.character_menu.addAction(act)
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
        self._set("character", pack.id)
        self._event(self.brain.on_start)

    def _refresh_menu(self) -> None:
        from . import autostart

        self._fill_character_menu()
        self.act_toggle.setText(f"Hide {self.pack.name}" if self.companion.isVisible() else f"Show {self.pack.name}")
        self.act_sleep.setText("Wake up" if self.brain.asleep else "Go to sleep")
        if self.act_autostart is not None:
            self.act_autostart.blockSignals(True)
            self.act_autostart.setChecked(autostart.is_enabled())
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
        for size in (16, 20, 24, 32, 48, 64, 128, 256):
            icon.addPixmap(QPixmap.fromImage(face.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                                         Qt.TransformationMode.SmoothTransformation)))
        return icon
