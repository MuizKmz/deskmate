"""Phase 8's pure parts: focus timer, the day's log, special days, weather, stuck helper."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deskmate import days, focus, stuck, weather
from deskmate.activity import make_activity
from deskmate.daylog import DayLog, hours, label_for


def act(exe: str, title: str):
    return make_activity(exe, title)


class FocusTests(unittest.TestCase):
    def test_a_session_then_a_break(self):
        session = focus.Focus(25, started=1000.0)
        self.assertTrue(session.focusing)
        self.assertEqual(session.clock(1000.0), "25:00")
        self.assertEqual(session.clock(1000.0 + 60 * 24 + 47), "0:13")
        self.assertIsNone(session.step(1000.0 + 60 * 10))
        self.assertEqual(session.focused_minutes(1000.0 + 60 * 10 + 30), 10)
        self.assertEqual(session.step(1000.0 + 25 * 60), "done")
        self.assertEqual(session.phase, "break")
        self.assertEqual(session.clock(1000.0 + 25 * 60), f"{focus.BREAK_MINUTES}:00")
        self.assertIsNone(session.step(1000.0 + 26 * 60))
        self.assertEqual(session.step(1000.0 + 31 * 60), "break_over")
        self.assertEqual(session.phase, "over")
        self.assertEqual(session.focused_minutes(1000.0 + 99 * 60), 25)

    def test_what_counts_as_drifting(self):
        self.assertTrue(focus.is_distraction(act("chrome.exe", "lofi hip hop - YouTube - Google Chrome")))
        self.assertTrue(focus.is_distraction(act("steam.exe", "Steam")))
        self.assertTrue(focus.is_distraction(act("msedge.exe", "(3) Home / X - Microsoft Edge")))
        self.assertFalse(focus.is_distraction(act("chrome.exe", "Idol - YouTube Music - Google Chrome")))  # music is fine
        self.assertFalse(focus.is_distraction(act("chrome.exe", "Code review - GitHub - Google Chrome")))
        self.assertFalse(focus.is_distraction(act("chrome.exe", "An overview of reviews - Google Chrome")))
        self.assertFalse(focus.is_distraction(act("chrome.exe", "why is my eye twitching - Google Search - Google Chrome")))
        self.assertFalse(focus.is_distraction(act("code.exe", "app.py - deskmate - Visual Studio Code")))
        self.assertFalse(focus.is_distraction(None))

    def test_a_gentle_nudge_after_a_minute_not_more_often_than_every_few_minutes(self):
        session = focus.Focus(50, started=0.0)
        youtube, code = act("chrome.exe", "cats - YouTube - Google Chrome"), act("code.exe", "a.py - x - Visual Studio Code")
        self.assertFalse(session.observe(10, youtube))
        self.assertFalse(session.observe(40, youtube))  # a quick look is fine
        self.assertTrue(session.observe(75, youtube))
        self.assertFalse(session.observe(120, youtube))  # not again right away
        self.assertFalse(session.observe(130, code))  # back to work
        self.assertFalse(session.observe(140, youtube))
        self.assertFalse(session.observe(210, youtube))  # a minute again, but too soon after the last nudge
        self.assertTrue(session.observe(75 + focus.DRIFT_GAP + 1, youtube))
        self.assertEqual(session.nudges, 2)
        session.step(50 * 60)
        self.assertFalse(session.observe(50 * 60 + 500, youtube))  # on the break: watch what you like


class DayLogTests(unittest.TestCase):
    def test_labels_are_short_and_safe(self):
        self.assertEqual(label_for(act("code.exe", "app.py - deskmate - Visual Studio Code")), "VS Code")
        self.assertEqual(label_for(act("chrome.exe", "lofi hip hop radio - YouTube - Google Chrome")), "YouTube")
        self.assertEqual(label_for(act("chrome.exe", "Pull request #12 · MuizKmz/deskmate - Google Chrome")),
                         "Chrome")  # (not a site name: just the browser)
        self.assertEqual(label_for(act("chrome.exe", "Idol - YouTube Music - Google Chrome")), "YouTube Music")
        self.assertIsNone(label_for(act("chrome.exe", "Maybank2u - Login - Google Chrome")))  # private: never logged
        self.assertIsNone(label_for(None))

    def test_a_day(self):
        folder = Path(tempfile.mkdtemp())
        book = DayLog(folder / "daylog.json")
        today = date(2026, 11, 4)
        book.add_time(today, "VS Code", 3 * 3600)
        book.add_time(today, "YouTube", 40 * 60)
        book.add_time(today, "Notepad", 20)  # under a minute: not in the top list
        book.add_focus(today, 25, True)
        book.add_focus(today, 10, False)
        book.add_song(today, "YOASOBI - Idol")
        book.add_song(today, "YOASOBI - Idol")  # once is enough
        book.add_chat(today)
        book.mark(today, "wrapup")
        summary = book.summary(today)
        self.assertEqual(summary["minutes"], 220)
        self.assertEqual(summary["top"], [("VS Code", 180), ("YouTube", 40)])
        self.assertEqual((summary["focus_sessions"], summary["focus_minutes"]), (1, 35))
        self.assertEqual(summary["songs"], ["YOASOBI - Idol"])
        text = book.describe(today)
        self.assertIn("3 h 40 min", text)
        self.assertIn("VS Code (3 h)", text)
        self.assertIn("YOASOBI", text)
        self.assertTrue(book.save(today))
        again = DayLog(folder / "daylog.json")
        self.assertEqual(again.summary(today), summary)
        self.assertTrue(again.flag(today, "wrapup"))
        self.assertIsNone(again.flag(today, "weather"))
        again.add_chat(date(2026, 12, 1))
        again.save(date(2026, 12, 1))  # two weeks later: the old day is gone
        self.assertEqual(DayLog(folder / "daylog.json").summary(today)["minutes"], 0)
        self.assertEqual(DayLog(folder / "missing.json").describe(today), "Nothing logged today.")
        (folder / "broken.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(DayLog(folder / "broken.json").days, {})

    def test_hours(self):
        self.assertEqual((hours(40), hours(60), hours(95)), ("40 min", "1 h", "1 h 35 min"))


class SpecialDayTests(unittest.TestCase):
    def test_birthday_payday_friday(self):
        self.assertEqual(days.special_day(date(2026, 12, 31), birthday="12-31"),
                         days.SpecialDay("birthday", "your birthday"))
        self.assertEqual(days.special_day(date(2026, 11, 25), payday=25).kind, "payday")
        self.assertEqual(days.special_day(date(2026, 2, 28), payday=31).kind, "payday")  # the last day
        self.assertEqual(days.special_day(date(2026, 11, 6)).kind, "friday")
        self.assertIsNone(days.special_day(date(2026, 11, 4)))

    @unittest.skipUnless(__import__("importlib").util.find_spec("holidays"), "pip install holidays")
    def test_malaysian_holidays(self):
        self.assertEqual(days.special_day(date(2026, 8, 31), country="MY").name, "Merdeka Day")
        self.assertEqual(days.special_day(date(2026, 3, 21), country="MY").name, "Hari Raya Aidilfitri")
        self.assertEqual(days.special_day(date(2026, 11, 8), country="MY").name, "Deepavali")
        self.assertIsNone(days.special_day(date(2026, 11, 9), country="MY"))  # the day off in lieu isn't the festival
        self.assertEqual(days.special_day(date(2026, 3, 23), country="MY", subdiv="JHR").kind, "holiday")  # state
        self.assertIsNone(days.special_day(date(2026, 3, 23), country="MY", subdiv=""))

    def test_birthdays_people_type(self):
        for text, value in (("31/12", "12-31"), ("12-31", "12-31"), ("Dec 31", "12-31"), ("31 December", "12-31"),
                            ("5/3", "03-05"), ("29 feb", "02-29"), ("", ""), ("nope", None), ("13-13", None)):
            self.assertEqual(days.valid_birthday(text), value, text)


class _Opener:
    """Pretend internet: answers by URL."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.asked = []

    def __call__(self, request, timeout):
        self.asked.append(request.full_url)
        for start, payload in self.answers.items():
            if request.full_url.startswith(start):
                if isinstance(payload, Exception):
                    raise payload
                return io.BytesIO(json.dumps(payload).encode())
        raise OSError("no route")


class WeatherTests(unittest.TestCase):
    FORECAST = {
        "current": {"time": "2026-11-04T08:00", "temperature_2m": 27.4, "weather_code": 2},
        "hourly": {"time": [f"2026-11-04T{h:02d}:00" for h in range(24)],
                   "precipitation_probability": [10] * 15 + [80] * 9},
        "daily": {"time": ["2026-11-04"], "temperature_2m_max": [32.1], "temperature_2m_min": [24.0],
                  "precipitation_probability_max": [80]},
    }

    def test_city_then_forecast(self):
        opener = _Opener({weather.GEOCODE_URL: {"results": [{"name": "Johor Bahru", "latitude": 1.47,
                                                             "longitude": 103.76, "country": "Malaysia"}]},
                          weather.FORECAST_URL: self.FORECAST})
        place = weather.find_place("johor bahru", opener)
        self.assertEqual((place.name, place.country), ("Johor Bahru", "Malaysia"))
        today = weather.forecast(place, opener)
        self.assertEqual((today.temperature, today.words, today.high, today.rain_hour), (27.4, "partly cloudy", 32.1, 15))
        self.assertIn("latitude=1.47", opener.asked[-1])
        line = today.line()
        self.assertIn("27° and partly cloudy in Johor Bahru", line)
        self.assertIn("umbrella", line)  # 80% chance of rain later
        self.assertIn("3 pm", today.rain_line())

    def test_problems_become_messages(self):
        with self.assertRaises(weather.WeatherError) as caught:
            weather.find_place("Atlantis", _Opener({weather.GEOCODE_URL: {"results": []}}))
        self.assertIn("Atlantis", str(caught.exception))
        with self.assertRaises(weather.WeatherError):
            weather.find_place("x", _Opener({weather.GEOCODE_URL: OSError("offline")}))
        with self.assertRaises(weather.WeatherError):
            weather.forecast(weather.Place("x", 0, 0), _Opener({weather.FORECAST_URL: {"current": {}}}))

    def test_lines(self):
        hot = weather.Weather("KL", 31, 0, 35, 25, 10)
        self.assertIn("hot", hot.line())
        rainy = weather.Weather("KL", 24, 63, 27, 23, 90)
        self.assertTrue(rainy.raining)
        self.assertIn("Stay dry", rainy.line())
        self.assertEqual(rainy.emoji, "🌧️")


class StuckTests(unittest.TestCase):
    def test_what_looks_stuck(self):
        self.assertTrue(stuck.looks_stuck(act("windowsterminal.exe", "Traceback (most recent call last) - Terminal")))
        self.assertTrue(stuck.looks_stuck(act("chrome.exe", "python - TypeError: x - Stack Overflow - Google Chrome")))
        self.assertTrue(stuck.looks_stuck(act("chrome.exe", "how to fix cors error - Google Search - Google Chrome")))
        self.assertFalse(stuck.looks_stuck(act("code.exe", "● errors.py - deskmate - Visual Studio Code")))  # a file name
        self.assertFalse(stuck.looks_stuck(act("chrome.exe", "lofi - YouTube - Google Chrome")))
        self.assertFalse(stuck.looks_stuck(None))

    def test_offers_after_a_while_then_rests(self):
        watch = stuck.StuckWatch(stuck_minutes=2, window_minutes=5, cooldown=600)
        error = act("windowsterminal.exe", "npm ERR! failed - Terminal")
        offered = [t for t in range(0, 300, 5) if watch.observe(float(t), error, active=True)]
        self.assertEqual(len(offered), 1)
        self.assertGreaterEqual(offered[0], 120)
        self.assertIs(watch.last_activity, error)
        away = stuck.StuckWatch(stuck_minutes=2)
        self.assertFalse(any(away.observe(float(t), error, active=False) for t in range(0, 600, 5)))  # not at the PC


if __name__ == "__main__":
    unittest.main()
