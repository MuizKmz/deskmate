"""End-to-end checks of the real windows, run invisibly (Qt "offscreen" mode)."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
    from PySide6.QtWidgets import QApplication

    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


COLORS = {
    "idle": "#C9A0DC", "happy": "#F4A6C0", "sleepy": "#9FB4E8", "sleep": "#7F8FD0",
    "pouty": "#E88F8F", "surprised": "#F2D06B", "blush": "#F7B7D2", "talk": "#A6E0C8",
}


def draw_pack(root: Path) -> Path:
    """A fake character: a coloured blob per expression, on a transparent background."""
    for name, color in COLORS.items():
        image = QImage(300, 450, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(60, 20, 180, 180)  # head
        painter.drawRoundedRect(90, 190, 120, 255, 40, 40)  # body down to the feet
        painter.end()
        (root / name).mkdir(parents=True, exist_ok=True)
        image.save(str(root / name / f"{name}_01.png"))
    (root / "character.json").write_text(
        '{"name": "Testy", "head": {"x": 0.5, "y": 0.24, "top": 0.045}, '
        '"lines": {"intro": ["Hello from the test!"], "pet": ["Hehe"]}}',
        encoding="utf-8",
    )
    return root


def mouse(widget, kind, local, button=None, buttons=None):
    button = button if button is not None else Qt.MouseButton.LeftButton
    buttons = buttons if buttons is not None else Qt.MouseButton.LeftButton
    local = QPointF(local)
    event = QMouseEvent(kind, local, QPointF(widget.mapToGlobal(local.toPoint())), button, buttons,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def noon():
    """A pretend wall clock: always 12:00. The real time would make her say late-night lines
    when the tests happen to run at night (GitHub's machines run on UTC)."""
    from datetime import datetime

    return datetime(2026, 11, 3, 12, 0)


class ActiveUser:
    """Pretend someone is using the PC right now. (The real idle time on a CI machine is
    "nobody touched it for ages", which would make her yawn instead of saying hello.)"""

    source = "test"

    def seconds(self) -> float:
        return 0.0


def spin(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def opaque_pixels(image: QImage, step: int = 4) -> int:
    return sum(
        1
        for y in range(0, image.height(), step)
        for x in range(0, image.width(), step)
        if image.pixelColor(x, y).alpha() > 0
    )


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class QtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = draw_pack(Path(cls._tmp.name) / "testy")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def make_companion(self):
        from deskmate.character import load_pack
        from deskmate.companion import Companion, load_frames

        pack = load_pack(self.root)
        self.assertTrue(pack.ok, pack.issues)
        companion = Companion(pack, load_frames(pack), size="medium")
        companion.place(None)
        companion.show()
        spin(0.05)
        return companion

    def test_she_renders_with_a_transparent_background(self):
        companion = self.make_companion()
        image = companion.grab().toImage()
        self.assertGreater(opaque_pixels(image), 200)
        self.assertEqual(image.pixelColor(1, 1).alpha(), 0)  # corner stays see-through
        companion.close()

    def test_click_drag_and_screen_edges(self):
        companion = self.make_companion()
        events = []
        companion.clicked.connect(lambda: events.append("click"))
        companion.dragStarted.connect(lambda: events.append("drag"))
        companion.dragEnded.connect(lambda: events.append("drop"))
        body = companion._sprite_rect_local().center()

        mouse(companion, QEvent.Type.MouseButtonPress, body)
        mouse(companion, QEvent.Type.MouseButtonRelease, body, buttons=Qt.MouseButton.NoButton)
        self.assertEqual(events, ["click"])

        # A click on an empty corner is not a pet.
        mouse(companion, QEvent.Type.MouseButtonPress, QPoint(2, 2))
        mouse(companion, QEvent.Type.MouseButtonRelease, QPoint(2, 2), buttons=Qt.MouseButton.NoButton)
        self.assertEqual(events, ["click"])

        start = companion.pos()
        mouse(companion, QEvent.Type.MouseButtonPress, body)
        mouse(companion, QEvent.Type.MouseMove, body + QPoint(40, 0), button=Qt.MouseButton.NoButton)
        mouse(companion, QEvent.Type.MouseMove, body + QPoint(80, -10), button=Qt.MouseButton.NoButton)
        mouse(companion, QEvent.Type.MouseButtonRelease, body + QPoint(80, -10), buttons=Qt.MouseButton.NoButton)
        self.assertEqual(events, ["click", "drag", "drop"])
        self.assertNotEqual(companion.pos(), start)

        # Asking for a spot far off-screen gets pulled back onto the screen.
        far = companion.clamped_pos(QPoint(100000, 100000))
        avail = companion.screen_for(far).availableGeometry()
        sprite = companion._sprite_rect_local().translated(far)
        self.assertTrue(avail.contains(sprite), (avail, sprite))
        companion.close()

    def test_expressions_crossfade_and_effects(self):
        companion = self.make_companion()
        for name in ("happy", "sleep", "pouty", "unknown-face", "talk"):
            companion.set_expression(name)
            for effect in ("hop", "land", "shake"):
                companion.play(effect)
            spin(0.06)
            self.assertGreater(opaque_pixels(companion.grab().toImage()), 200)
        self.assertEqual(companion.expression, "talk")
        for size in ("small", "large", "medium"):
            companion.set_size(size)
            self.assertGreater(opaque_pixels(companion.grab().toImage()), 100)
        companion.set_on_top(False)
        self.assertTrue(companion.isVisible())
        companion.close()

    # ------------------------------------------------------------ Phase 2
    def physics_companion(self, with_blink=False):
        """A companion driven by a pretend clock, so physics can be stepped exactly."""
        import random

        from deskmate.character import load_pack
        from deskmate.companion import Companion, load_frames

        class Clock:
            t = 1000.0

            def __call__(self):
                return self.t

        clock = Clock()
        pack = load_pack(self.root)
        frames = load_frames(pack)
        if with_blink:
            frames["blink"] = [frames["happy"][0]]  # any different picture will do for the test
        companion = Companion(pack, frames, size="medium", clock=clock, rng=random.Random(7))
        companion.place(None)
        companion.show()
        companion._timer.stop()  # we step frames ourselves
        return companion, clock

    def step(self, companion, clock, seconds, until=None):
        frames = int(seconds * 30)
        for _ in range(frames):
            clock.t += 1 / 30
            companion._on_frame()
            if until is not None and until():
                return True
        return False

    def test_gravity_she_falls_to_the_floor_and_lands(self):
        companion, clock = self.physics_companion()
        landings = []
        companion.landed.connect(landings.append)
        floor = companion.floor_y()
        companion.move(companion.pos().x(), floor - 300)  # put her up in the air
        self.assertFalse(companion.on_floor())
        companion.settle()
        self.assertTrue(companion.falling)
        self.assertTrue(self.step(companion, clock, 3.0, until=lambda: not companion.falling))
        self.assertTrue(companion.on_floor())
        self.assertEqual(len(landings), 1)
        self.assertGreater(landings[0], 500)
        companion.close()

    def test_flinging_her_bounces_off_walls_and_stays_on_screen(self):
        companion, clock = self.physics_companion()
        body = companion._sprite_rect_local().center()
        start = body
        mouse(companion, QEvent.Type.MouseButtonPress, start)
        for i in range(1, 6):  # a fast swipe to the right and up
            clock.t += 0.016
            mouse(companion, QEvent.Type.MouseMove, start + QPoint(45 * i, -25 * i), button=Qt.MouseButton.NoButton)
        mouse(companion, QEvent.Type.MouseButtonRelease, start + QPoint(225, -125), buttons=Qt.MouseButton.NoButton)
        self.assertTrue(companion.falling)
        self.assertGreater(companion._fall_vx, 1000)
        self.assertTrue(self.step(companion, clock, 6.0, until=lambda: not companion.falling))
        min_x, max_x, _, floor = companion._limits(companion._ground_rect())
        self.assertTrue(min_x <= companion.pos().x() <= max_x)
        self.assertEqual(companion.pos().y(), int(floor))
        companion.close()

    def test_wander_walks_to_a_spot_and_stays_on_the_floor(self):
        companion, clock = self.physics_companion()
        start_x = companion.pos().x()
        self.assertTrue(companion.start_wander(target_x=start_x - 150))
        self.assertTrue(self.step(companion, clock, 10.0, until=lambda: not companion.walking))
        self.assertLessEqual(abs(companion.pos().x() - (start_x - 150)), 1)
        self.assertTrue(companion.on_floor())
        companion.set_gravity(False)
        self.assertFalse(companion.start_wander())  # no strolling without gravity
        companion.close()

    def test_perching_on_windows(self):
        from deskmate.perch import Ledge

        companion, clock = self.physics_companion()
        avail = companion.available_rect()
        feet_x = companion.pos().x() + companion._feet_local().x()

        class Windows:
            """Pretend open windows (what perch.WindowsLedges reads from Windows for real)."""

            def __init__(self):
                self.items = {}

            def ledges(self):
                return sorted(self.items.values(), key=lambda w: w.z)

            def ledge(self, window_id):
                return self.items.get(window_id)

        windows = Windows()
        top = avail.top() + avail.height() * 0.6
        windows.items[1] = Ledge(1, feet_x - 200, feet_x + 200, top, top + 300, z=1)
        companion.set_ledge_source(windows)
        landed = []
        companion.landed.connect(landed.append)

        # Dropped from above, she lands on the window, not the taskbar.
        companion.move(companion.pos().x(), int(avail.top() + 10))
        companion._start_fall(0.0, 0.0)
        self.assertTrue(self.step(companion, clock, 3.0, until=lambda: not companion.falling))
        self.assertTrue(companion.perched)
        self.assertAlmostEqual(companion.pos().y() + companion._feet_local().y(), top, delta=1)
        self.assertTrue(companion.on_floor())
        self.assertEqual(len(landed), 1)

        # The window moves: she rides along.
        old = companion.pos()
        windows.items[1] = Ledge(1, feet_x - 150, feet_x + 250, top - 40, top + 260, z=1)
        companion.check_perch()
        self.assertEqual((companion.pos().x() - old.x(), companion.pos().y() - old.y()), (50, -40))

        # She strolls, but only along the top of her window.
        self.assertTrue(companion.start_wander(target_x=companion.pos().x() + 2000))
        self.step(companion, clock, 15.0, until=lambda: not companion.walking)
        feet = companion.pos().x() + companion._feet_local().x()
        self.assertTrue(windows.items[1].left <= feet <= windows.items[1].right)
        self.assertTrue(companion.perched)

        # The window closes: she falls to the taskbar.
        del windows.items[1]
        companion.check_perch()
        self.assertTrue(companion.falling)
        self.assertTrue(self.step(companion, clock, 5.0, until=lambda: not companion.falling and companion.on_floor()))
        self.assertFalse(companion.perched)
        self.assertEqual(companion.pos().y(), companion.floor_y())
        companion.close()

    @unittest.skipUnless(sys.platform == "win32", "reads real windows, Windows only")
    def test_reading_real_windows(self):
        from deskmate.perch import WindowsLedges, qt_to_logical

        source = WindowsLedges(qt_to_logical())
        ledges = source.ledges()  # whatever happens to be open; it must simply work
        for ledge in ledges:
            self.assertLess(ledge.left, ledge.right)
            self.assertLess(ledge.top, ledge.bottom)
        if ledges:
            self.assertEqual(source.ledge(ledges[0].id).id, ledges[0].id)
        self.assertIsNone(source.ledge(0))

    def test_perching_skips_covered_and_too_high_window_tops(self):
        from deskmate.perch import Ledge

        companion, clock = self.physics_companion()
        avail = companion.available_rect()
        feet_x = companion.pos().x() + companion._feet_local().x()
        top = avail.top() + avail.height() * 0.6

        class Windows:
            def __init__(self, items):
                self.items = items

            def ledges(self):
                return self.items

            def ledge(self, window_id):
                return next((w for w in self.items if w.id == window_id), None)

        # Window 2's top is hidden behind window 1 (in front), and window 3 is too near the
        # top of the screen for her to fit above it: she ends up on the taskbar.
        front = Ledge(1, feet_x - 300, feet_x + 300, top - 100, top + 200, z=0)
        hidden = Ledge(2, feet_x - 100, feet_x + 100, top, top + 150, z=1)
        too_high = Ledge(3, feet_x - 100, feet_x + 100, avail.top() + 20, avail.top() + 400, z=2)
        companion.set_ledge_source(Windows([front, hidden, too_high]))
        companion.move(companion.pos().x(), int(avail.top()))
        companion._start_fall(0.0, 0.0)
        self.step(companion, clock, 3.0, until=lambda: not companion.falling)
        self.assertEqual(companion._perch.id, 1)  # lands on the front window, the only good seat
        # Grab her and drop her below every window: back to the taskbar.
        companion.set_ledge_source(None)
        self.step(companion, clock, 5.0, until=lambda: not companion.falling and companion.on_floor())
        self.assertFalse(companion.perched)
        self.assertEqual(companion.pos().y(), companion.floor_y())
        companion.close()

    def test_blinking(self):
        companion, clock = self.physics_companion(with_blink=True)
        companion.set_expression("idle")
        blinking = 0
        for _ in range(30 * 15):
            clock.t += 1 / 30
            companion._on_frame()
            blinking += companion.showing_blink()
        self.assertGreater(blinking, 0)  # she blinked...
        self.assertLess(blinking, 30)  # ...but only briefly
        companion.set_expression("happy")
        self.step(companion, clock, 8.0)
        self.assertFalse(companion.showing_blink())  # no blinking with other faces
        companion.close()

    def test_built_in_pixel_character(self):
        from deskmate.character import load_pack
        from deskmate.companion import Companion, load_frames

        piko = Path(__file__).resolve().parent.parent / "characters" / "piko"
        if not piko.exists():
            self.skipTest("characters/piko not present")
        pack = load_pack(piko)
        self.assertTrue(pack.ok, pack.issues)
        self.assertIs(pack.meta.get("smooth"), False)
        companion = Companion(pack, load_frames(pack), size="small")
        companion.place(None)
        companion.show()
        for name in ("idle", "happy", "sleep", "pouty", "surprised", "blush", "talk", "sleepy"):
            companion.set_expression(name)
            spin(0.03)
            self.assertGreater(opaque_pixels(companion.grab().toImage()), 200)
        companion.close()

    def test_speech_bubble(self):
        from deskmate.bubble import SpeechBubble

        companion = self.make_companion()
        bubble = SpeechBubble({"accent": "#C9A0DC"})
        bubble.say("Hi! This is a fairly long line to check that wrapping works.", 2.0,
                   companion.head_rect_global(), companion.available_rect())
        spin(0.3)
        self.assertTrue(bubble.isVisible())
        self.assertLessEqual(bubble.width(), SpeechBubble.MAX_TEXT_WIDTH + 2 * SpeechBubble.PAD_X + 40)
        self.assertGreater(opaque_pixels(bubble.grab().toImage(), step=2), 100)
        avail = companion.available_rect()
        self.assertTrue(avail.contains(bubble.geometry()), (avail, bubble.geometry()))
        bubble.fade_out()
        spin(0.4)
        self.assertFalse(bubble.isVisible())
        companion.close()

    def test_chat_from_the_menu_shows_her_reply(self):
        import random
        from unittest import mock

        from deskmate.app import Controller
        from deskmate.brain import Brain
        from deskmate.character import load_pack
        from deskmate.chatbox import ChatSettingsDialog
        from deskmate.companion import load_frames
        from deskmate.settings import Settings
        from tests.fake_openai import FakeOpenAI

        fake = FakeOpenAI()
        self.addCleanup(fake.close)
        fake.reply = "[blush] W-well... thank you~"
        with tempfile.TemporaryDirectory() as home, mock.patch("deskmate.app.data_dir", return_value=Path(home)):
            settings = Settings(Path(home) / "settings.json")
            settings["perch"] = False  # never sit on the test machine's real windows
            settings["update_check"] = False  # no real GitHub calls in tests
            pack = load_pack(self.root)
            brain = Brain(pack.lines, now=time.monotonic(), rng=random.Random(5), wallclock=noon)
            controller = Controller(self.app, settings, pack, load_frames(pack), brain, ActiveUser())
            controller.start()
            controller.chat.config.api_key = fake.key
            controller.chat.config.base_url = fake.url
            controller.chat.config.model = ""  # let it pick one
            controller.act_chat.trigger()
            box = controller._chat_box
            self.assertTrue(box.isVisible())
            box.edit.setText("you look cute today")
            box.edit.returnPressed.emit()
            self.assertEqual(controller.bubble.text, "...")  # thinking
            deadline = time.monotonic() + 10
            while controller.bubble.text != "W-well... thank you~" and time.monotonic() < deadline:
                spin(0.05)
            self.assertEqual(controller.bubble.text, "W-well... thank you~")
            self.assertEqual(brain.expression(time.monotonic()), "blush")
            self.assertEqual(settings["chat_model"], "gpt-5.4-mini")  # remembered for next time
            self.assertEqual(fake.requests[-1]["messages"][-1]["content"], "you look cute today")
            self.assertTrue((Path(home) / "chat_testy.json").exists())
            # A broken key: she says so in her own words instead of crashing.
            controller.chat.config.api_key = "sk-wrong-key-000"
            box.edit.setText("hello?")
            box.edit.returnPressed.emit()
            deadline = time.monotonic() + 10
            while controller.bubble.text == "..." and time.monotonic() < deadline:
                spin(0.05)
            self.assertIn("key", controller.bubble.text)
            # The settings dialog opens and hides the key field for Ollama.
            dialog = ChatSettingsDialog(settings, {"openai": fake.key, "anthropic": ""}, "Testy")
            self.assertIn("...", dialog.key.placeholderText())  # the saved OpenAI key, masked
            dialog.provider.setCurrentIndex(dialog.provider.findData("claude"))
            self.assertEqual(dialog.form.labelForField(dialog.key).text(), "Anthropic API key")
            self.assertIn("sk-ant-", dialog.key.placeholderText())  # no Claude key saved yet
            self.assertEqual(dialog.config().provider, "claude")
            dialog.provider.setCurrentIndex(dialog.provider.findData("ollama"))
            self.assertEqual(dialog.config().provider, "ollama")
            self.assertEqual(dialog.config().api_key, "")
            dialog.close()
            controller._forget_chat()
            self.assertEqual(controller.chat.history, [])
            box.hide()
            controller._on_about_to_quit()
            controller.companion.close()

    def test_update_notice(self):
        import random
        from unittest import mock

        from deskmate.app import Controller
        from deskmate.brain import Brain
        from deskmate.character import load_pack
        from deskmate.companion import load_frames
        from deskmate.settings import Settings
        from deskmate.updates import Release

        with tempfile.TemporaryDirectory() as home, mock.patch("deskmate.app.data_dir", return_value=Path(home)):
            settings = Settings(Path(home) / "settings.json")
            settings["perch"] = False  # never sit on the test machine's real windows
            settings["update_check"] = False  # the test asks by itself, with a pretend GitHub
            pack = load_pack(self.root)
            brain = Brain(pack.lines, now=time.monotonic(), rng=random.Random(5), wallclock=noon)
            controller = Controller(self.app, settings, pack, load_frames(pack), brain, ActiveUser())
            controller.start()
            self.assertFalse(controller.act_update.isVisible())

            def wait():
                deadline = time.monotonic() + 5
                while controller._update_worker.busy and time.monotonic() < deadline:
                    spin(0.02)

            controller.check_for_updates(manual=True, check=lambda current: None)
            wait()
            self.assertIn("newest", controller.bubble.text)

            newer = Release("9.9.9", "https://github.com/MuizKmz/deskmate/releases/tag/v9.9.9")
            controller.check_for_updates(check=lambda current: newer)
            wait()
            self.assertTrue(controller.act_update.isVisible())
            self.assertEqual(controller.act_update.text(), "Update to 9.9.9...")
            self.assertIn("v9.9.9", controller.bubble.text)
            self.assertEqual(settings["update_announced"], "9.9.9")
            with mock.patch.object(controller.bubble, "say") as say:
                controller.check_for_updates(check=lambda current: newer)  # the automatic check again
                wait()
            say.assert_not_called()  # announced only once per version

            def offline(current):
                raise OSError("no internet")

            controller.check_for_updates(manual=True, check=offline)
            wait()
            self.assertIn("GitHub", controller.bubble.text)
            controller._on_about_to_quit()
            controller.companion.close()

    def test_voice_settings_and_what_she_reads_out(self):
        import random
        from unittest import mock

        from deskmate.app import Controller
        from deskmate.brain import Brain
        from deskmate.character import load_pack
        from deskmate.companion import load_frames
        from deskmate.settings import Settings

        with tempfile.TemporaryDirectory() as home, mock.patch("deskmate.app.data_dir", return_value=Path(home)):
            settings = Settings(Path(home) / "settings.json")
            settings["perch"] = False  # never sit on the test machine's real windows
            settings["update_check"] = False  # no real GitHub calls in tests
            pack = load_pack(self.root)
            brain = Brain(pack.lines, now=time.monotonic(), rng=random.Random(5), wallclock=noon)
            controller = Controller(self.app, settings, pack, load_frames(pack), brain, ActiveUser())
            windows = mock.MagicMock()
            windows.available.return_value = True
            controller.speaker.windows = windows  # no real speech engine in tests
            controller.start()
            spin(0.2)
            windows.speak.assert_not_called()  # voice is off until you switch it on

            labels = [a.text() for a in controller._voice_actions.values()]
            self.assertEqual(labels, ["Off", "Windows voice (free)", "Natural voice (OpenAI)"])
            controller._voice_actions["windows"].trigger()
            self.assertEqual(settings["voice"], "windows")
            windows.speak.assert_called_once_with("Can you hear me now?")  # a quick sample

            controller._event(lambda now: brain.on_chat_reply(now, "happy", "Hehe~ hi!"))
            windows.speak.assert_called_with("Hehe hi!")
            calls = windows.speak.call_count
            controller._event(lambda now: brain.on_pet(now))  # an ordinary line: not read out by default
            self.assertEqual(windows.speak.call_count, calls)
            controller.act_voice_all.trigger()
            self.assertTrue(settings["voice_everything"])

            controller._voice_actions["openai"].trigger()  # no key saved: she asks for one instead
            self.assertIn("key", controller.bubble.text)
            controller._on_about_to_quit()
            controller.companion.close()

    def test_chat_log_window(self):
        import random
        from unittest import mock

        from deskmate.app import Controller
        from deskmate.brain import Brain
        from deskmate.character import load_pack
        from deskmate.companion import load_frames
        from deskmate.settings import Settings
        from tests.fake_openai import FakeOpenAI

        fake = FakeOpenAI()
        self.addCleanup(fake.close)
        with tempfile.TemporaryDirectory() as home, mock.patch("deskmate.app.data_dir", return_value=Path(home)):
            settings = Settings(Path(home) / "settings.json")
            settings["perch"] = False  # never sit on the test machine's real windows
            settings["update_check"] = False  # no real GitHub calls in tests
            pack = load_pack(self.root)
            brain = Brain(pack.lines, now=time.monotonic(), rng=random.Random(5), wallclock=noon)
            controller = Controller(self.app, settings, pack, load_frames(pack), brain, ActiveUser())
            controller.start()
            controller.chat.config.api_key = fake.key
            controller.chat.config.base_url = fake.url
            controller.chat.config.model = "gpt-5.4-mini"

            controller.act_chat_log.trigger()
            log = controller._chat_log
            self.assertTrue(log.isVisible())
            self.assertEqual(log.bubble_texts(), [])  # nothing yet today

            fake.reply = '[happy] Hi hi~ I\'ll remind you! <remind when="in 30 min">stretch</remind>'
            log.edit.setText("hello! remind me to stretch in 30 min")
            log.edit.returnPressed.emit()
            self.assertEqual(log.bubble_texts()[-2:], [("user", "hello! remind me to stretch in 30 min"),
                                                       ("assistant", "...")])  # sent + typing
            deadline = time.monotonic() + 10
            while log._waiting and time.monotonic() < deadline:
                spin(0.05)
            self.assertEqual(log.bubble_texts(), [("user", "hello! remind me to stretch in 30 min"),
                                                  ("assistant", "Hi hi~ I'll remind you!")])
            self.assertEqual([r.text for r in controller.reminders.upcoming()], ["stretch"])

            # "Chat with..." while the log is open just brings the log forward.
            controller.open_chat()
            self.assertTrue(controller._chat_box is None or not controller._chat_box.isVisible())

            # A failure shows as a faded note but isn't saved to the chat.
            controller.chat.config.api_key = "sk-wrong-key-000"
            log.edit.setText("are you there?")
            log.edit.returnPressed.emit()
            deadline = time.monotonic() + 10
            while log._waiting and time.monotonic() < deadline:
                spin(0.05)
            self.assertIn("key", log.bubble_texts()[-1][1])
            self.assertEqual(len(controller.chat.transcript()), 2)

            # Reopening reads today's chat back; forgetting clears the window too.
            log.hide()
            controller.open_chat_log()
            self.assertEqual(len(log.bubble_texts()), 2)
            controller._forget_chat()
            self.assertEqual(log.bubble_texts(), [])
            log.hide()
            controller._on_about_to_quit()
            controller.companion.close()

    def test_buddy_mode(self):
        import random
        from unittest import mock

        from PySide6.QtWidgets import QDialog, QPushButton

        from deskmate.activity import Activity
        from deskmate.app import Controller
        from deskmate.brain import Brain
        from deskmate.character import load_pack
        from deskmate.companion import load_frames
        from deskmate.look import MAX_SIDE, WatchDialog, snapshot_from
        from deskmate.settings import Settings
        from tests.fake_openai import FakeOpenAI

        # Big screens are shrunk before they're sent.
        big = QImage(3200, 1800, QImage.Format.Format_RGB32)
        big.fill(QColor("white"))
        snap = snapshot_from(big)
        self.assertEqual((snap.width, snap.height), (MAX_SIDE, 882))
        self.assertTrue(snap.data.startswith(b"\xff\xd8"))  # a JPEG

        fake = FakeOpenAI()
        self.addCleanup(fake.close)
        with tempfile.TemporaryDirectory() as home, mock.patch("deskmate.app.data_dir", return_value=Path(home)):
            settings = Settings(Path(home) / "settings.json")
            settings["perch"] = False  # never sit on the test machine's real windows
            settings["update_check"] = False  # no real GitHub calls in tests
            pack = load_pack(self.root)
            brain = Brain(pack.lines, now=time.monotonic(), rng=random.Random(5), wallclock=noon)
            controller = Controller(self.app, settings, pack, load_frames(pack), brain, ActiveUser())
            controller.start()
            controller.chat.config.api_key = fake.key
            controller.chat.config.base_url = fake.url
            controller.chat.config.model = "gpt-5.4-mini"
            now_on = [Activity("Chrome", "lofi hip hop radio - YouTube", "chrome", bounds=(100, 50, 500, 350))]
            controller._read_activity = lambda: now_on[0]
            song = [None]
            controller._read_music = lambda: song[0]
            shots = []

            def fake_screen(screen):
                shots.append(screen)
                image = QImage(screen.geometry().size(), QImage.Format.Format_RGB32)
                image.fill(QColor("gray"))
                return image

            controller._grab_screen = fake_screen

            # "Not now": nothing happens.
            with mock.patch.object(WatchDialog, "exec", return_value=QDialog.DialogCode.Rejected):
                controller.act_look.trigger()
            self.assertIsNone(controller.watch)

            # "Let her watch" for 30 minutes.
            def allow(dialog):
                dialog.duration.setCurrentIndex(dialog.duration.findData(30))
                return QDialog.DialogCode.Accepted

            with mock.patch.object(WatchDialog, "exec", allow):
                controller.act_look.trigger()
            watch = controller.watch
            self.assertIsNotNone(watch)
            self.assertEqual(settings["watch_minutes"], 30)
            self.assertIn("company", controller.bubble.text)
            controller._tick()
            self.assertTrue(watch.badge.isVisible())
            self.assertEqual(watch.left(time.monotonic()), "30 min left")

            # She reacts to what you opened (once you've stayed on it), with a picture of the screen.
            fake.reply = "[happy] Ooh, lo-fi~ is this your study playlist?"
            watch.watcher.settle = 0
            watch.watcher.hold(-1e9)
            controller._watch_tick(time.monotonic())        # first look: "you just switched"
            watch.polled = -1e9
            controller._watch_tick(time.monotonic() + 1)    # still there: time for a comment
            deadline = time.monotonic() + 10
            while controller.bubble.text != "Ooh, lo-fi~ is this your study playlist?" and time.monotonic() < deadline:
                spin(0.05)
            self.assertEqual(controller.bubble.text, "Ooh, lo-fi~ is this your study playlist?")
            sent = fake.requests[-1]["messages"]
            self.assertIn("buddy", sent[0]["content"])
            self.assertIn("lofi hip hop radio", sent[-1]["content"][0]["text"])
            url = sent[-1]["content"][1]["image_url"]["url"]
            self.assertTrue(url.startswith("data:image/jpeg;base64,"))
            import base64

            seen = QImage.fromData(base64.b64decode(url.split(",", 1)[1]))
            self.assertEqual((seen.width(), seen.height()), (400, 300))  # just the window you're using
            self.assertEqual(controller.chat.transcript()[-1]["about"], "Chrome: lofi hip hop radio - YouTube")
            # She asked something: answer chips appear by her bubble. Tap one and it's your answer.
            fake.reply = "[happy] Do you study with this on? <replies>Yes, every day!|Just today</replies>"
            self.assertEqual(watch.replies.answers(), ["Yes!", "Not really"])  # (her lo-fi question)
            watch.replies.hide()
            now_on[0] = Activity("Chrome", "Physics notes - Google Docs", "chrome")
            watch.watcher.hold(-1e9)
            watch.watcher._last_ask = -1e9
            brain._chatting_until = 0
            watch.polled = -1e9
            controller._watch_tick(time.monotonic() + 1.5)
            watch.polled = -1e9
            controller._watch_tick(time.monotonic() + 2)
            deadline = time.monotonic() + 10
            while not watch.replies.isVisible() and time.monotonic() < deadline:
                spin(0.05)
            self.assertEqual(watch.replies.answers(), ["Yes, every day!", "Just today"])
            fake.reply = "[happy] Hardworking~ I'm proud of you!"
            chip = [b for b in watch.replies.findChildren(QPushButton) if b.text() == "Yes, every day!"][0]
            chip.click()
            self.assertFalse(watch.replies.isVisible())
            deadline = time.monotonic() + 10
            while controller.bubble.text != "Hardworking~ I'm proud of you!" and time.monotonic() < deadline:
                spin(0.05)
            sent = fake.requests[-1]["messages"]
            self.assertEqual(sent[-1]["content"][0]["text"], "Yes, every day!")  # your answer, with the screen
            self.assertIn("Do you study with this on?", str(sent[1:-1]))  # ...right after her question

            # A new song starts in the background: she hears it (no picture needed for a song).
            fake.reply = "[happy] Ooh, Ado now? Villain hits hard~"
            song[0] = Activity("YouTube Music", "Villain", "chrome", kind="music")
            watch.music.hold(-1e9)
            watch.music.settle = 0
            brain._chatting_until = 0
            before = len(shots)
            watch.polled = -1e9
            controller._watch_tick(time.monotonic() + 3)
            watch.polled = -1e9
            controller._watch_tick(time.monotonic() + 4)
            deadline = time.monotonic() + 10
            while controller.bubble.text != "Ooh, Ado now? Villain hits hard~" and time.monotonic() < deadline:
                spin(0.05)
            self.assertEqual(controller.bubble.text, "Ooh, Ado now? Villain hits hard~")
            self.assertEqual(fake.requests[-1]["messages"][-1]["content"], "(Now playing: YouTube Music: Villain)")
            self.assertEqual(len(shots), before)
            now_on[0] = Activity("Chrome", "lofi hip hop radio - YouTube", "chrome", bounds=(100, 50, 500, 350))

            # You switch away while she's thinking: her late comment is dropped, not shown with the new thing.
            now_on[0] = Activity("Spotify", "Ado - Odo", "spotify")
            watch.watcher.hold(-1e9)
            watch.watcher._last_ask = -1e9
            watch.watcher._mentioned.clear()
            brain._chatting_until = 0  # (her last comment counts as chatting for a bit)
            watch.polled = -1e9
            controller._watch_tick(time.monotonic() + 3)
            watch.polled = -1e9
            fake.reply = "[happy] Ado! Great pick~"
            controller._watch_tick(time.monotonic() + 4)
            self.assertTrue(watch.reacting)
            now_on[0] = Activity("Chrome", "lofi hip hop radio - YouTube", "chrome")  # back already
            deadline = time.monotonic() + 10
            while watch.reacting and time.monotonic() < deadline:
                spin(0.05)
            self.assertNotEqual(controller.bubble.text, "Ado! Great pick~")
            self.assertNotIn("Great pick", str(controller.chat.transcript()))
            # Same thing again: she doesn't repeat herself.
            count = len(fake.requests)
            watch.polled = -1e9
            controller._watch_tick(time.monotonic() + 2)
            spin(0.2)
            self.assertEqual(len(fake.requests), count)

            # You answer her in Today's chat: she knows what you're on and sees the screen.
            controller.open_chat_log()
            log = controller._chat_log
            self.assertTrue(log.look_bar.isVisibleTo(log))
            fake.reply = "[blush] Ehehe, good taste~"
            log.edit.setText("yes I love it")
            log.edit.returnPressed.emit()
            deadline = time.monotonic() + 10
            while log._waiting and time.monotonic() < deadline:
                spin(0.05)
            sent = fake.requests[-1]["messages"]
            self.assertIn("lofi hip hop radio", sent[0]["content"])
            self.assertIsInstance(sent[-1]["content"], list)  # with the picture
            self.assertEqual(log.bubble_texts()[-1], ("assistant", "Ehehe, good taste~"))

            # Something private: no picture is taken.
            now_on[0] = Activity("Chrome", "Maybank2u", "chrome")
            before = len(shots)
            log.edit.setText("hmm")
            log.edit.returnPressed.emit()
            deadline = time.monotonic() + 10
            while log._waiting and time.monotonic() < deadline:
                spin(0.05)
            self.assertEqual(len(shots), before)
            self.assertIsInstance(fake.requests[-1]["messages"][-1]["content"], str)
            self.assertIn("private", fake.requests[-1]["messages"][0]["content"])

            # Clicking the badge stops it; time running out stops it too.
            watch.badge.clicked.emit()
            self.assertIsNone(controller.watch)
            self.assertFalse(log.look_bar.isVisibleTo(log))
            self.assertIn("stopped watching", controller.bubble.text)
            with mock.patch.object(WatchDialog, "exec", allow):
                controller.toggle_watching()
            controller.watch.until = time.monotonic() - 1
            controller._tick()
            self.assertIsNone(controller.watch)
            self.assertIn("Time's up", controller.bubble.text)

            # Where Windows can leave her out of a picture, it's only for the moment it's taken.
            calls = []

            def exclude(window, on):
                calls.append(on)
                return True

            with mock.patch("deskmate.look.exclude_from_capture", exclude), \
                    mock.patch.object(WatchDialog, "exec", allow):
                controller.start_watching()
                self.assertTrue(controller.watch.can_exclude)
                self.assertEqual(calls, [True, False])  # just the check: she's not hidden while you work
                calls.clear()
                got = []
                controller._capture(got.append)
                self.assertTrue(calls and all(calls))  # hidden from the picture...
                deadline = time.monotonic() + 3
                while not got and time.monotonic() < deadline:
                    spin(0.05)
                self.assertIsNotNone(got[0])
                self.assertEqual(calls.count(True), calls.count(False))  # ...and back right after
                self.assertFalse(calls[-1])
                controller.stop_watching()
            log.hide()
            controller._on_about_to_quit()
            controller.companion.close()

    def test_reminders_from_the_menu_from_chat_and_missed_ones(self):
        import json
        import random
        from datetime import datetime, timedelta
        from unittest import mock

        from deskmate.app import Controller
        from deskmate.brain import Brain
        from deskmate.character import load_pack
        from deskmate.companion import load_frames
        from deskmate.settings import Settings
        from tests.fake_openai import FakeOpenAI

        fake = FakeOpenAI()
        self.addCleanup(fake.close)
        with tempfile.TemporaryDirectory() as home, mock.patch("deskmate.app.data_dir", return_value=Path(home)):
            missed_at = (datetime.now() - timedelta(minutes=30)).replace(microsecond=0).isoformat()
            (Path(home) / "reminders.json").write_text(json.dumps(
                {"reminders": [{"id": "old1", "due": missed_at, "text": "water the plants"}]}), encoding="utf-8")
            settings = Settings(Path(home) / "settings.json")
            settings["perch"] = False  # never sit on the test machine's real windows
            settings["update_check"] = False  # no real GitHub calls in tests
            pack = load_pack(self.root)
            lines = dict(pack.lines, reminder=["Time: {what}!"], reminder_missed=["Missed: {what}"],
                         reminder_set=["Set for {time}"])
            brain = Brain(lines, now=time.monotonic(), rng=random.Random(5), wallclock=noon)
            controller = Controller(self.app, settings, pack, load_frames(pack), brain, ActiveUser())
            controller.MISSED_DELAY_MS = 0
            controller.start()
            spin(0.3)
            self.assertEqual(controller.bubble.text, "Missed: water the plants")

            # Menu: Reminders > Add reminder...
            self.assertFalse(controller.add_reminder_from_text("sometime later"))
            self.assertTrue(controller.add_reminder_from_text("in 20 min stretch"))
            self.assertTrue(controller.bubble.text.startswith("Set for "))
            controller._fill_reminders_menu()
            labels = [a.text() for a in controller.reminders_menu.actions()]
            self.assertEqual(labels[0], "Add reminder...")
            self.assertTrue(labels[-1].endswith("stretch"), labels)

            # It comes due: she says it.
            reminder = controller.reminders.items[0]
            reminder.due = (datetime.now() - timedelta(seconds=1)).replace(microsecond=0).isoformat()
            controller._tick()
            self.assertEqual(controller.bubble.text, "Time: stretch!")
            self.assertEqual(controller.reminders.upcoming(), [])

            # From chat: the model adds a tag, the app sets the reminder.
            controller.chat.config.api_key = fake.key
            controller.chat.config.base_url = fake.url
            controller.chat.config.model = "gpt-5.4-mini"
            fake.reply = '[happy] Okay~ <remind when="in 45 min">call mom</remind>'
            controller.open_chat()
            controller._on_chat_sent("remind me to call mom in 45 minutes")
            deadline = time.monotonic() + 10
            while not controller.reminders.upcoming() and time.monotonic() < deadline:
                spin(0.05)
            self.assertEqual([r.text for r in controller.reminders.upcoming()], ["call mom"])
            self.assertEqual(controller.bubble.text, "Okay~")
            controller._cancel_reminder(controller.reminders.upcoming()[0].id)
            self.assertEqual(controller.reminders.upcoming(), [])
            self.assertEqual(json.loads((Path(home) / "reminders.json").read_text())["reminders"], [])
            controller._chat_box.hide()
            controller._on_about_to_quit()
            controller.companion.close()

    def test_whole_app_wiring(self):
        import logging
        import random

        from deskmate.app import Controller
        from deskmate.brain import Brain
        from deskmate.character import load_pack
        from deskmate.companion import load_frames
        from deskmate.settings import Settings

        import shutil

        second = self.root.parent / "testy2"
        if not second.exists():
            shutil.copytree(self.root, second)
        os.environ["DESKMATE_CHARACTERS"] = str(self.root.parent)
        self.addCleanup(os.environ.pop, "DESKMATE_CHARACTERS", None)

        from unittest import mock

        with tempfile.TemporaryDirectory() as home, mock.patch("deskmate.app.data_dir", return_value=Path(home)):
            settings = Settings(Path(home) / "settings.json")
            settings["perch"] = False  # never sit on the test machine's real windows
            settings["update_check"] = False  # no real GitHub calls in tests
            pack = load_pack(self.root)
            brain = Brain(pack.lines, now=time.monotonic(), rng=random.Random(3), wallclock=noon)
            with self.assertLogs("deskmate", level="INFO") as captured:
                logging.getLogger("deskmate").info("test started")
                controller = Controller(self.app, settings, pack, load_frames(pack), brain,
                                        ActiveUser())
                controller.start(first_run=True)
                spin(0.4)
                self.assertTrue(controller.bubble.isVisible())
                self.assertEqual(controller.bubble.text, "Hello from the test!")
                controller._on_click()
                controller._tick()
                controller._set_size("large")
                controller._set_chatty(False)
                controller._set_wander(False)
                controller._set_gravity(False)
                controller.act_walk.trigger()  # no floor without gravity: she says so instead
                self.assertFalse(controller.companion.walking)
                self.assertIn("Gravity", controller.bubble.text)
                controller._set_gravity(True)
                mate = controller.companion
                mate._stop_moving()
                mate.move(mate.available_rect().center().x() - mate.width() // 2, mate.floor_y())
                controller.act_walk.trigger()  # "Take a walk" from the menu
                self.assertTrue(mate.walking)
                mate._stop_moving()
                controller.toggle_visible()
                self.assertFalse(controller.companion.isVisible())
                controller.toggle_visible()
                self.assertTrue(controller.companion.isVisible())
                controller._toggle_sleep()
                self.assertTrue(brain.asleep)
                controller._toggle_sleep()
                self.assertFalse(brain.asleep)
                controller._refresh_menu()
                names = [a.text() for a in controller.character_menu.actions()]
                self.assertEqual(names, ["Testy", "Testy2"])
                controller.switch_character(second)
                self.assertEqual(controller.pack.id, "testy2")
                self.assertTrue(controller.companion.isVisible())
                self.assertEqual(settings["character"], "testy2")
                spin(0.3)
                controller._on_about_to_quit()
            errors = [line for line in captured.output if line.startswith(("ERROR", "CRITICAL"))]
            self.assertEqual(errors, [])
            saved = Settings(Path(home) / "settings.json")
            self.assertEqual(saved["size"], "large")
            self.assertFalse(saved["chatty"])
            self.assertFalse(saved["wander"])
            self.assertTrue(saved["gravity"])
            self.assertIsNotNone(saved["position"])
            controller.companion.close()


if __name__ == "__main__":
    unittest.main()
