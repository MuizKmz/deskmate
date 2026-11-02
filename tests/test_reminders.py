import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from deskmate.reminders import ReminderBook, parse_request, parse_when

NOW = datetime(2026, 11, 2, 14, 30)


class ParseTests(unittest.TestCase):
    def test_clock_times_today_or_tomorrow(self):
        cases = {
            "15:00": datetime(2026, 11, 2, 15, 0), "3pm": datetime(2026, 11, 2, 15, 0),
            "3:30 PM": datetime(2026, 11, 2, 15, 30), "15.45": datetime(2026, 11, 2, 15, 45),
            "9am": datetime(2026, 11, 3, 9, 0),  # already past today -> tomorrow
            "at 9": datetime(2026, 11, 3, 9, 0), "12am": datetime(2026, 11, 3, 0, 0),
        }
        for text, expected in cases.items():
            self.assertEqual(parse_when(text, NOW), expected, text)

    def test_durations(self):
        cases = {"in 20 min": 20, "20m": 20, "in 2 hours": 120, "1h30": 90, "+45": 45, "in 45": 45,
                 "90 minutes": 90, "2h": 120}
        for text, minutes in cases.items():
            self.assertEqual(parse_when(text, NOW), NOW + timedelta(minutes=minutes), text)

    def test_not_times(self):
        for text in ("", "soon", "45", "25:00", "13pm", "in 0 min", "in 5 days", "tomorrow"):
            self.assertIsNone(parse_when(text, NOW), text)

    def test_requests_with_the_time_first_or_last(self):
        cases = {
            "15:00 meeting": (datetime(2026, 11, 2, 15, 0), "meeting"),
            "3:30 pm - submit report": (datetime(2026, 11, 2, 15, 30), "submit report"),
            "in 20 min stretch": (NOW + timedelta(minutes=20), "stretch"),
            "+45 to drink water": (NOW + timedelta(minutes=45), "drink water"),
            "meeting at 3pm": (datetime(2026, 11, 2, 15, 0), "meeting"),
            "call mom in 2 hours": (NOW + timedelta(hours=2), "call mom"),
            "20m": (NOW + timedelta(minutes=20), "your reminder"),
        }
        for text, expected in cases.items():
            self.assertEqual(parse_request(text, NOW), expected, text)
        self.assertIsNone(parse_request("10 push-ups", NOW))
        self.assertIsNone(parse_request("just words", NOW))


class BookTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "reminders.json"
        self.now = NOW

    def tearDown(self):
        self._tmp.cleanup()

    def book(self):
        return ReminderBook(self.path, clock=lambda: self.now)

    def test_add_list_fire_and_survive_a_restart(self):
        book = self.book()
        late = book.add(datetime(2026, 11, 2, 16, 0), "about the review")
        early = book.add(datetime(2026, 11, 2, 15, 0), "meeting")
        self.assertEqual(late.text, "the review")  # "about" is dropped
        self.assertEqual([r.text for r in self.book().upcoming()], ["meeting", "the review"])  # reloaded, sorted
        self.assertEqual(early.label(self.now), "15:00  meeting")
        self.now = datetime(2026, 11, 2, 15, 0, 5)
        book = self.book()
        self.assertEqual([r.text for r in book.pop_due()], ["meeting"])
        self.assertEqual(book.pop_due(), [])  # only once
        self.assertEqual([r.text for r in self.book().upcoming()], ["the review"])

    def test_cancel(self):
        book = self.book()
        reminder = book.add(NOW + timedelta(minutes=5), "tea")
        self.assertTrue(book.cancel(reminder.id))
        self.assertFalse(book.cancel(reminder.id))
        self.assertEqual(self.book().upcoming(), [])

    def test_missed_while_closed(self):
        book = self.book()
        book.add(NOW + timedelta(minutes=10), "recent")
        book.add(NOW + timedelta(minutes=1), "old")
        self.now = NOW + timedelta(hours=12, minutes=5)  # "old" is more than 12 h ago now
        self.assertEqual([r.text for r in self.book().pop_missed()], ["recent"])
        self.assertEqual(self.book().items, [])

    def test_labels_and_limits(self):
        book = self.book()
        tomorrow = book.add(datetime(2026, 11, 3, 9, 0), "standup")
        self.assertEqual(tomorrow.label(NOW), "tomorrow 09:00  standup")
        self.assertIsNone(book.add(NOW - timedelta(hours=1), "in the past"))
        self.assertEqual(book.add(NOW + timedelta(minutes=1), "x" * 500).text, "x" * 120)

    def test_broken_file_starts_empty(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.book().items, [])
        self.path.write_text(json.dumps({"reminders": [{"id": "a", "due": "garbage", "text": "x"}]}), encoding="utf-8")
        self.assertEqual(self.book().items, [])


if __name__ == "__main__":
    unittest.main()
