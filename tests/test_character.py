import json
import tempfile
import unittest
from pathlib import Path

from deskmate.character import DEFAULT_LINES, find_pack, format_report, load_pack, png_info

from .helpers import make_pack, write_png


class CharacterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def levels(self, pack, level):
        return [issue.message for issue in pack.issues if issue.level == level]

    def test_png_header_reader(self):
        path = write_png(self.root / "a.png", 33, 44, alpha=True)
        self.assertEqual(png_info(path), (33, 44, True))
        path = write_png(self.root / "b.png", 10, 12, alpha=False)
        self.assertEqual(png_info(path), (10, 12, False))
        (self.root / "c.png").write_bytes(b"not a png")
        with self.assertRaises(ValueError):
            png_info(self.root / "c.png")

    def test_good_pack(self):
        folder = make_pack(self.root / "yuki", ("idle", "happy", "sleep"), meta={"name": "Yuki"})
        pack = load_pack(folder)
        self.assertTrue(pack.ok, pack.issues)
        self.assertEqual(pack.name, "Yuki")
        self.assertEqual(pack.frame_size, (40, 60))
        self.assertEqual(pack.resolve("happy"), "happy")
        self.assertEqual(pack.resolve("pouty"), "idle")  # missing -> idle
        self.assertTrue(any("pouty" in m for m in self.levels(pack, "info")))
        self.assertIn("RESULT: OK", format_report(pack))

    def test_missing_idle_is_an_error(self):
        pack = load_pack(make_pack(self.root / "x", ("happy",), meta={}))
        self.assertFalse(pack.ok)
        self.assertTrue(any("idle" in m for m in self.levels(pack, "error")))

    def test_missing_folder_is_an_error(self):
        pack = load_pack(self.root / "does-not-exist")
        self.assertFalse(pack.ok)

    def test_size_mismatch_and_missing_alpha_are_warnings(self):
        folder = make_pack(self.root / "y", ("idle",), meta={})
        write_png(folder / "happy" / "happy_01.png", 80, 120)
        write_png(folder / "pouty" / "pouty_01.png", 40, 60, alpha=False)
        pack = load_pack(folder)
        self.assertTrue(pack.ok)
        warnings = " ".join(self.levels(pack, "warning"))
        self.assertIn("not 40x60", warnings)
        self.assertIn("no transparency", warnings)

    def test_junk_files(self):
        folder = make_pack(self.root / "z", ("idle",), meta={})
        (folder / "idle" / "notes.txt").write_text("hi")
        (folder / "idle" / "Thumbs.db").write_text("x")
        (folder / "happy").mkdir()
        (folder / "happy" / "happy_01.png").write_bytes(b"\x89PNG\r\n\x1a\nbroken")
        pack = load_pack(folder)
        self.assertNotIn("happy", pack.animations)
        self.assertTrue(any("notes.txt" in m for m in self.levels(pack, "warning")))
        self.assertTrue(any("happy_01.png" in m for m in self.levels(pack, "error")))

    def test_frames_play_in_number_order(self):
        folder = make_pack(self.root / "w", ("idle",), meta={})
        for n in (1, 2, 10):
            write_png(folder / "walk" / f"walk_{n}.png")
        pack = load_pack(folder)
        self.assertEqual([p.name for p in pack.animations["walk"].frames], ["walk_1.png", "walk_2.png", "walk_10.png"])

    def test_meta_lines_theme_and_head(self):
        meta = {
            "name": "Mochi",
            "fps": 8,
            "animations": {"idle": {"fps": 3}, "blink": {"loop": True}},
            "lines": {"pet": ["Nya~", 5, ""], "random": "not a list", "late": []},
            "theme": {"accent": "#123456", "bubble": "white"},
            "head": {"x": 0.4, "y": 0.25, "top": 0.05},
        }
        folder = make_pack(self.root / "m", ("idle", "blink"), meta=meta)
        pack = load_pack(folder)
        self.assertEqual(pack.lines["pet"], ["Nya~"])
        self.assertEqual(pack.lines["random"], DEFAULT_LINES["random"])
        self.assertEqual(pack.lines["late"], [])  # empty list switches that group off
        self.assertEqual(pack.theme["accent"], "#123456")
        self.assertEqual(pack.theme["bubble"], "#FFFFFF")
        self.assertEqual(pack.animations["idle"].fps, 3)
        self.assertEqual(pack.animations["blink"].fps, 8)
        self.assertTrue(pack.animations["blink"].loop)
        self.assertEqual(pack.head, (0.4, 0.25, 0.05))

    def test_broken_character_json_uses_defaults(self):
        folder = make_pack(self.root / "b", ("idle",))
        (folder / "character.json").write_text("{oops", encoding="utf-8")
        pack = load_pack(folder)
        self.assertTrue(pack.ok)
        self.assertEqual(pack.name, "B")

    def test_find_pack_falls_back(self):
        make_pack(self.root / "chars" / "alpha", ("idle",), meta={})
        make_pack(self.root / "chars" / "beta", ("idle",), meta={})
        chars = self.root / "chars"
        self.assertEqual(find_pack(chars, "BETA").name, "beta")
        self.assertEqual(find_pack(chars, "missing").name, "alpha")
        self.assertIsNone(find_pack(self.root / "nothing", "x"))


if __name__ == "__main__":
    unittest.main()
