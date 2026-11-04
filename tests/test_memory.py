import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deskmate.activity import Activity
from deskmate.memory import MAX_FACTS, Memory, habit_of

TODAY = date(2026, 11, 4)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "memory.json"

    def test_facts_are_kept_updated_and_forgotten(self):
        memory = Memory(self.path)
        self.assertTrue(memory.empty)
        self.assertTrue(memory.remember("Likes YUI", TODAY))
        self.assertTrue(memory.remember("Likes YUI's songs, especially GLORIA.", TODAY))  # same thing, newer
        self.assertEqual([f["text"] for f in memory.facts], ["Likes YUI's songs, especially GLORIA"])
        memory.remember("Birthday is 12 May", TODAY)
        self.assertFalse(memory.remember("  a ", TODAY))  # nothing to keep
        again = Memory(self.path)  # it's on disk
        self.assertEqual(len(again.facts), 2)
        self.assertEqual(again.forget("birthday"), 1)
        self.assertEqual(again.forget("xy"), 0)  # too vague to forget anything
        self.assertEqual([f["text"] for f in Memory(self.path).facts], ["Likes YUI's songs, especially GLORIA"])
        for i in range(MAX_FACTS + 5):
            memory.remember(f"Fact number {i} about something", TODAY)
        self.assertEqual(len(memory.facts), MAX_FACTS)

    def test_diary_and_what_goes_in_her_prompt(self):
        memory = Memory(self.path)
        memory.remember("Is building DeskMate in Python", TODAY)
        memory.add_day(date(2026, 11, 3), "You fixed the perch bug late at night~")
        memory.add_day(date(2026, 11, 4), "Today's own line isn't in the prompt yet")
        self.assertTrue(memory.has_day(date(2026, 11, 3)))
        prompt = memory.prompt(TODAY)
        self.assertIn("<remember>", prompt)  # how to add memories
        self.assertIn("- Is building DeskMate in Python", prompt)
        self.assertIn("- yesterday: You fixed the perch bug late at night~", prompt)
        self.assertNotIn("Today's own line", prompt)
        for _ in range(3):
            memory.notice("music", "GLORIA", TODAY)
        memory.notice("site", "YouTube", TODAY)  # once isn't a habit yet
        memory.notice("project", "deskmate", date(2026, 10, 1))
        memory.notice("project", "deskmate", date(2026, 10, 1))  # long ago: not mentioned
        self.assertIn("listens to GLORIA (3x)", memory.prompt(TODAY))
        self.assertNotIn("YouTube", memory.prompt(TODAY))
        self.assertNotIn("deskmate", memory.prompt(TODAY))

    def test_deleting_from_the_window(self):
        memory = Memory(self.path)
        memory.remember("Likes cats", TODAY)
        memory.add_day(TODAY, "We talked about cats")
        memory.notice("music", "GLORIA", TODAY)
        memory.remove("facts", 0)
        memory.remove("days", 0)
        memory.remove("habits", "music|gloria")
        memory.remove("facts", 7)  # gone already: no error
        self.assertTrue(Memory(self.path).empty)
        memory.remember("Likes cats", TODAY)
        memory.clear()
        self.assertTrue(Memory(self.path).empty)

    def test_a_broken_file_is_not_fatal(self):
        self.path.write_text("{broken", encoding="utf-8")
        self.assertTrue(Memory(self.path).empty)
        self.path.write_text(json.dumps({"facts": [{"text": 5}, {"text": "Likes tea"}], "habits": []}), "utf-8")
        memory = Memory(self.path)
        self.assertEqual([f["text"] for f in memory.facts], ["Likes tea"])
        self.assertEqual(memory.habits, {})

    def test_what_counts_as_a_habit(self):
        self.assertEqual(habit_of(Activity("VS Code", "app.py - deskmate", "code")), ("project", "deskmate"))
        self.assertEqual(habit_of(Activity("Chrome", "lofi hip hop radio - YouTube", "chrome")), ("site", "YouTube"))
        self.assertEqual(habit_of(Activity("YouTube Music", "GLORIA", "chrome", kind="music")), ("music", "GLORIA"))
        self.assertEqual(habit_of(Activity("Excel", "budget.xlsx", "excel")), ("app", "Excel"))
        self.assertIsNone(habit_of(Activity("Chrome", "Maybank2u", "chrome")))  # private: never counted
        self.assertIsNone(habit_of(Activity("Chrome", "GLORIA - YouTube Music", "chrome")))  # songs count apart
        self.assertIsNone(habit_of(None))


if __name__ == "__main__":
    unittest.main()
