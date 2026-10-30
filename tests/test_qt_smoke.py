"""End-to-end checks of the real windows, run invisibly (Qt "offscreen" mode)."""

import os
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

    def test_whole_app_wiring(self):
        import logging
        import random

        from deskmate.app import Controller
        from deskmate.brain import Brain
        from deskmate.character import load_pack
        from deskmate.companion import load_frames
        from deskmate.settings import Settings
        from deskmate.sysidle import IdleTracker

        import shutil

        second = self.root.parent / "testy2"
        if not second.exists():
            shutil.copytree(self.root, second)
        os.environ["DESKMATE_CHARACTERS"] = str(self.root.parent)
        self.addCleanup(os.environ.pop, "DESKMATE_CHARACTERS", None)

        with tempfile.TemporaryDirectory() as home:
            settings = Settings(Path(home) / "settings.json")
            pack = load_pack(self.root)
            brain = Brain(pack.lines, now=time.monotonic(), rng=random.Random(3))
            with self.assertLogs("deskmate", level="INFO") as captured:
                logging.getLogger("deskmate").info("test started")
                controller = Controller(self.app, settings, pack, load_frames(pack), brain,
                                        IdleTracker(lambda: (0, 0)))
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
