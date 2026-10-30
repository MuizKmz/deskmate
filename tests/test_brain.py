import random
import unittest
from datetime import datetime

from deskmate import brain as B
from deskmate.brain import Brain

LINES = {key: [f"<{key}>"] for key in (
    "intro", "greet_morning", "greet_afternoon", "greet_evening", "greet_night", "pet", "too_much",
    "drag", "drop", "sleepy", "goodnight", "wake", "ignored", "forgive", "late", "water", "break", "random",
    "fall", "wander",
)}


class Clock:
    """A pretend wall clock we can move around."""

    def __init__(self, hour=12):
        self.now = datetime(2026, 10, 30, hour, 0, 0)

    def __call__(self):
        return self.now


def make(hour=12, **kwargs) -> tuple[Brain, Clock]:
    clock = Clock(hour)
    brain = Brain(LINES, now=0.0, rng=random.Random(1), wallclock=clock, **kwargs)
    return brain, clock


def texts(brain: Brain) -> list[str]:
    return [speech.text for speech in brain.drain_speech()]


class StartTests(unittest.TestCase):
    def test_greets_by_time_of_day(self):
        for hour, key in ((9, "greet_morning"), (14, "greet_afternoon"), (19, "greet_evening"), (23, "greet_night")):
            brain, _ = make(hour)
            brain.on_start(0)
            self.assertEqual(texts(brain), [f"<{key}>"])
            self.assertEqual(brain.expression(0.1), "happy")
            self.assertIn("hop", brain.drain_animations())

    def test_first_run_introduces_herself(self):
        brain, _ = make()
        brain.on_first_run(0)
        self.assertEqual(texts(brain), ["<intro>"])


class PettingTests(unittest.TestCase):
    def test_pet_makes_her_happy_and_hop(self):
        brain, _ = make()
        brain.on_pet(10)
        self.assertEqual(brain.expression(10.5), "happy")
        self.assertEqual(texts(brain), ["<pet>"])
        self.assertEqual(brain.drain_animations(), ["hop"])
        # reaction wears off
        self.assertEqual(brain.expression(30), "idle")

    def test_no_speech_bubble_on_every_click(self):
        brain, _ = make()
        brain.on_pet(10)
        brain.on_pet(11)
        self.assertEqual(len(texts(brain)), 1)

    def test_too_many_pets_makes_her_pout(self):
        brain, _ = make()
        for t in (10, 10.5, 11, 11.5, 12):
            brain.on_pet(t)
        self.assertIn("<too_much>", texts(brain))
        self.assertEqual(brain.expression(12.1), "pouty")
        self.assertIn("shake", brain.drain_animations())

    def test_slow_pets_are_fine(self):
        brain, _ = make()
        for t in (10, 20, 30, 40, 50, 60):
            brain.on_pet(t)
        self.assertNotIn("<too_much>", texts(brain))


class SleepTests(unittest.TestCase):
    def test_sleepy_then_asleep_when_you_leave_and_wakes_when_back(self):
        brain, _ = make()
        brain.tick(100, user_idle=B.SLEEPY_AFTER + 1)
        self.assertEqual(brain.base, "sleepy")
        self.assertIn("<sleepy>", texts(brain))
        brain.tick(200, user_idle=B.SLEEP_AFTER + 1)
        self.assertTrue(brain.asleep)
        self.assertEqual(brain.expression(200), "sleep")
        brain.tick(300, user_idle=1)
        self.assertFalse(brain.asleep)
        self.assertEqual(texts(brain), ["<wake>"])
        self.assertEqual(brain.expression(300.5), "surprised")

    def test_short_pause_does_nothing(self):
        brain, _ = make()
        brain.tick(100, user_idle=120)
        self.assertEqual(brain.base, "idle")

    def test_menu_sleep_ignores_activity_until_petted(self):
        brain, _ = make()
        brain.set_manual_sleep(10, True)
        self.assertEqual(texts(brain), ["<goodnight>"])
        brain.tick(30, user_idle=0)
        self.assertTrue(brain.asleep)
        brain.on_pet(31)
        self.assertFalse(brain.asleep)
        self.assertEqual(texts(brain), ["<wake>"])

    def test_dragging_wakes_her_quietly(self):
        brain, _ = make()
        brain.set_manual_sleep(10, True)
        texts(brain)
        brain.on_drag_start(20)
        self.assertFalse(brain.asleep)
        self.assertEqual(brain.expression(20.5), "surprised")

    def test_unknown_idle_time_is_ok(self):
        brain, _ = make()
        for t in range(0, 600, 5):
            brain.tick(t, user_idle=None)
        self.assertFalse(brain.asleep)


class LateNightTests(unittest.TestCase):
    def test_sleepy_late_at_night_says_so_once(self):
        brain, clock = make(hour=1)
        brain.tick(10, user_idle=0)
        self.assertEqual(brain.base, "sleepy")
        self.assertEqual(texts(brain), ["<late>"])
        brain.base = "idle"
        brain.tick(20, user_idle=0)
        self.assertEqual(texts(brain), [])  # not again tonight
        clock.now = clock.now.replace(hour=9)
        brain.tick(30, user_idle=0)
        self.assertEqual(brain.base, "idle")


class PoutTests(unittest.TestCase):
    def test_pouts_when_ignored_while_you_work_and_forgives_on_pet(self):
        brain, _ = make(chatty=False, reminders=False)
        brain.tick(B.IGNORED_AFTER + 1, user_idle=2)
        self.assertEqual(brain.base, "pouty")
        self.assertEqual(texts(brain), ["<ignored>"])
        self.assertIn("shake", brain.drain_animations())
        brain.on_pet(B.IGNORED_AFTER + 10)
        self.assertEqual(brain.base, "idle")
        self.assertEqual(texts(brain), ["<forgive>"])
        self.assertEqual(brain.expression(B.IGNORED_AFTER + 10.5), "blush")

    def test_does_not_pout_when_you_are_away(self):
        brain, _ = make(chatty=False, reminders=False)
        brain.tick(B.IGNORED_AFTER + 1, user_idle=B.SLEEPY_AFTER + 1)
        self.assertNotEqual(brain.base, "pouty")


class CareTests(unittest.TestCase):
    def test_water_reminder_every_hour_of_activity(self):
        brain, _ = make(chatty=False)
        brain.on_pet(0)
        texts(brain)
        brain.last_interaction = B.WATER_EVERY  # you said hi recently, so no pouting
        brain.tick(B.WATER_EVERY + 1, user_idle=1)
        self.assertEqual(texts(brain), ["<water>"])
        brain.tick(B.WATER_EVERY + 100, user_idle=1)
        self.assertNotIn("<water>", texts(brain))  # not again so soon (a break reminder may follow)

    def test_no_reminders_while_asleep_or_when_switched_off(self):
        brain, _ = make(chatty=False)
        brain.set_manual_sleep(0, True)
        texts(brain)
        brain.tick(B.WATER_EVERY + 1, user_idle=1)
        self.assertEqual(texts(brain), [])
        brain, _ = make(chatty=False, reminders=False)
        brain.tick(B.WATER_EVERY + 1, user_idle=1)
        self.assertNotIn("<water>", texts(brain))

    def test_break_reminder_after_a_long_streak(self):
        brain, _ = make(chatty=False)
        brain._last_water = 1e9  # keep the water reminder out of the way
        for t in range(0, B.BREAK_AFTER + 10, 30):
            brain.on_hover(t, False)
            brain.last_interaction = t  # keep her from pouting
            brain.tick(t, user_idle=1)
        self.assertIn("<break>", texts(brain))


class ChatterTests(unittest.TestCase):
    def test_random_chatter_only_when_chatty(self):
        quiet, _ = make(chatty=False, reminders=False)
        chatty, _ = make(chatty=True, reminders=False)
        for t in range(0, B.CHATTER_MAX + 60, 30):
            for brain in (quiet, chatty):
                brain.last_interaction = t
                brain.tick(t, user_idle=1)
        self.assertNotIn("<random>", texts(quiet))
        self.assertIn("<random>", texts(chatty))


class DragAndHoverTests(unittest.TestCase):
    def test_surprised_while_dragged_then_calm_after_a_soft_landing(self):
        brain, _ = make()
        brain.on_drag_start(5)
        self.assertEqual(brain.expression(9), "surprised")
        brain.on_drag_end(10)
        brain.on_landed(10.2, impact=0.0)
        self.assertNotEqual(brain.expression(10.3), "surprised")
        self.assertNotIn("<fall>", texts(brain))

    def test_a_big_fall_hurts_a_little(self):
        brain, _ = make()
        brain.on_drag_start(5)
        brain.on_drag_end(6)
        brain.on_landed(7, impact=2400.0)
        self.assertIn("<fall>", texts(brain))  # (a "drag" line may come first)
        self.assertEqual(brain.expression(7.2), "surprised")

    def test_mouse_resting_on_her_makes_her_blush(self):
        brain, _ = make()
        brain.on_hover(0, True)
        brain.tick(0.5, user_idle=0)
        self.assertEqual(brain.expression(0.5), "idle")
        brain.tick(2.0, user_idle=0)
        self.assertEqual(brain.expression(2.0), "blush")


class WanderTests(unittest.TestCase):
    def tick_through(self, brain, seconds, step=10):
        for t in range(0, seconds, step):
            brain.last_interaction = t  # keep her from pouting
            brain.tick(t, user_idle=1)
        return brain.drain_animations()

    def test_she_strolls_now_and_then(self):
        brain, _ = make(chatty=False, reminders=False)
        self.assertIn("wander", self.tick_through(brain, B.WANDER_MAX + 20))

    def test_no_strolling_when_switched_off_or_asleep(self):
        brain, _ = make(chatty=False, reminders=False, wander=False)
        self.assertNotIn("wander", self.tick_through(brain, B.WANDER_MAX * 3))
        brain, _ = make(chatty=False, reminders=False)
        brain.set_manual_sleep(0, True)
        self.assertNotIn("wander", self.tick_through(brain, B.WANDER_MAX * 3))


class DurationTests(unittest.TestCase):
    def test_bubble_time_grows_with_text_but_is_capped(self):
        self.assertAlmostEqual(B.speech_duration("hi"), 2.4)
        self.assertLess(B.speech_duration("a" * 20), B.speech_duration("a" * 60))
        self.assertEqual(B.speech_duration("a" * 500), 7.0)


if __name__ == "__main__":
    unittest.main()
