import json
import tempfile
import unittest
from pathlib import Path

from deskmate.settings import SCHEMA, Settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "settings.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_defaults_when_there_is_no_file(self):
        settings = Settings(self.path)
        for key, (default, _valid) in SCHEMA.items():
            self.assertEqual(settings[key], default)

    def test_save_and_reload(self):
        settings = Settings(self.path)
        settings["size"] = "large"
        settings["position"] = [120, 340]
        settings["chatty"] = False
        self.assertTrue(settings.save())
        self.assertFalse((self.dir / "settings.json.tmp").exists())
        again = Settings(self.path)
        self.assertEqual(again["size"], "large")
        self.assertEqual(again["position"], [120, 340])
        self.assertFalse(again["chatty"])

    def test_broken_file_is_moved_aside_and_defaults_used(self):
        self.path.write_text("{ this is not json", encoding="utf-8")
        settings = Settings(self.path)
        self.assertEqual(settings["size"], "medium")
        self.assertFalse(self.path.exists())
        self.assertEqual(len(list(self.dir.glob("settings.broken-*.json"))), 1)

    def test_bad_values_are_ignored_one_by_one(self):
        self.path.write_text(json.dumps({
            "size": "gigantic", "position": [1, 2, 3], "chatty": "yes", "visible": False, "future_key": 5,
        }), encoding="utf-8")
        settings = Settings(self.path)
        self.assertEqual(settings["size"], "medium")
        self.assertIsNone(settings["position"])
        self.assertTrue(settings["chatty"])
        self.assertFalse(settings["visible"])  # the one valid value is kept

    def test_setting_a_bad_value_is_refused(self):
        settings = Settings(self.path)
        with self.assertRaises(ValueError):
            settings["size"] = "huge"
        with self.assertRaises(KeyError):
            settings["nope"] = 1

    def test_top_level_must_be_an_object(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        settings = Settings(self.path)
        self.assertEqual(settings["size"], "medium")


if __name__ == "__main__":
    unittest.main()
