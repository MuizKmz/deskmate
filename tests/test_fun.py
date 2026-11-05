"""Phase 9's pure parts: dancing on the beat, the bond, outfits, and the games' rules."""

from __future__ import annotations


import random
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deskmate import bond, dance, games, outfits


class DanceTests(unittest.TestCase):
    def test_finds_the_beat_and_the_tempo(self):
        tracker = dance.BeatTracker()
        beat = 60.0 / 120  # a song at 120 BPM: a loud kick every half second
        beats = 0
        for i in range(0, 400):  # 16 s of readings, 25 a second
            t = i * 0.04
            level = 0.8 if (t % beat) < 0.04 else 0.12
            beats += tracker.feed(t, level)
        self.assertGreater(beats, 25)
        self.assertAlmostEqual(tracker.bpm, 120, delta=8)
        self.assertTrue(tracker.playing(16.0))
        self.assertFalse(tracker.playing(16.0 + dance.SILENCE_STOP + 0.1))  # paused: the dance stops

    def test_silence_is_not_a_beat(self):
        tracker = dance.BeatTracker()
        self.assertFalse(any(tracker.feed(i * 0.04, 0.0) for i in range(100)))
        self.assertFalse(tracker.playing(4.0))

    def test_groove_moves(self):
        groove = dance.Groove(start=0.0, bpm=120)
        self.assertEqual(groove.phase(0.0), 0.0)
        self.assertAlmostEqual(groove.phase(0.25), 0.5)
        down, _ = groove.pose(0.0)
        up, _ = groove.pose(0.25)
        self.assertAlmostEqual(down, 0.0)  # on the beat
        self.assertGreater(up, 0.6)  # between beats: up
        leans = [groove.pose(t / 10)[1] for t in range(0, 20)]
        self.assertGreater(max(leans), 0.5)
        self.assertLess(min(leans), -0.5)  # left and right
        quiet = dance.BeatTracker()
        quiet.level = 0.0
        self.assertAlmostEqual(dance.Groove(0.0, quiet).energy(), 0.35)  # small moves when it's quiet


class BondTests(unittest.TestCase):
    def test_grows_with_daily_limits_and_levels_up(self):
        book = bond.Bond(Path(tempfile.mkdtemp()) / "bond.json")
        today = date(2026, 11, 5)
        self.assertEqual(book.level("yuki").number, 1)
        gained = sum(book.add("yuki", "pet", today)[0] for _ in range(50))
        self.assertEqual(gained, bond.DAILY_CAP["pet"])  # 50 pats count as 10
        self.assertEqual(book.add("yuki", "pet", date(2026, 11, 6))[0], 1)  # a new day
        levels = []
        for _ in range(4):
            levels.append(book.add("yuki", "chat", today)[1])
        self.assertEqual(book.level("yuki").points, 11 + 12)
        up = book.add("yuki", "visit", today)[1]
        self.assertIsNotNone(up)
        self.assertEqual((up.number, up.name), (2, "Getting to know you"))
        self.assertEqual(book.level("piko").number, 1)  # each character her own bond
        self.assertEqual(book.add("yuki", "nonsense", today), (0, None))
        again = bond.Bond(book.path)
        self.assertEqual(again.level("yuki").points, 27)
        self.assertEqual(again.days_together("yuki", date(2026, 11, 14)), 10)
        self.assertIn("Getting to know you", again.prompt("yuki", today))

    def test_levels(self):
        self.assertEqual(bond.level_for(0).name, "Just met")
        top = bond.level_for(10_000)
        self.assertIsNone(top.next_at)
        self.assertEqual(top.progress, 1.0)
        middle = bond.level_for(110)
        self.assertEqual(middle.number, 3)
        self.assertAlmostEqual(middle.progress, (110 - 70) / (150 - 70))
        self.assertIn("40 to the next level", middle.describe())


class OutfitTests(unittest.TestCase):
    def test_unlocks_and_seasons(self):
        self.assertEqual([o.key for o in outfits.unlocked(1)], ["bow"])
        self.assertIn("crown", [o.key for o in outfits.unlocked(8)])
        self.assertNotIn("party_hat", [o.key for o in outfits.unlocked(8)])  # seasonal only
        self.assertEqual([o.key for o in outfits.newly_unlocked(3)], ["cat_ears"])
        self.assertEqual(outfits.seasonal(date(2026, 12, 25)), "santa_hat")
        self.assertEqual(outfits.seasonal(date(2026, 10, 31)), "witch_hat")
        self.assertEqual(outfits.seasonal(date(2026, 3, 9), birthday="03-09"), "party_hat")
        self.assertIsNone(outfits.seasonal(date(2026, 11, 5)))


class GameTests(unittest.TestCase):
    def test_rock_paper_scissors(self):
        self.assertEqual(games.judge("rock", "scissors"), "win")
        self.assertEqual(games.judge("rock", "paper"), "lose")
        self.assertEqual(games.judge("paper", "paper"), "draw")
        game = games.RockPaperScissors(random.Random(3))
        rounds = 0
        while not game.over:
            game.play("rock")
            rounds += 1
            self.assertLess(rounds, 50)
        self.assertIn(game.winner, ("you", "her"))
        self.assertEqual(max(game.you, game.her), 2)

    def test_she_never_misses_a_win_or_a_block_when_playing_her_best(self):
        board = ["X", "X", "", "O", "O", "", "", "", ""]
        self.assertEqual(games.best_move(board, "O"), 5)  # her win first
        board = ["X", "X", "", "", "O", "", "", "", ""]
        self.assertEqual(games.best_move(board, "O"), 2)  # block yours
        self.assertEqual(games.winner(["X", "X", "X", "", "", "", "", "", ""]), "X")
        self.assertEqual(games.winner(list("XOXXOOOXX")), "draw")
        self.assertEqual(games.winning_line(["", "", "O", "", "O", "", "O", "", ""]), (2, 4, 6))

    def test_a_perfect_her_never_loses(self):
        rng = random.Random(7)
        for _ in range(30):
            game = games.TicTacToe(rng, mistakes=0.0)
            while game.result is None:
                game.play(rng.choice([i for i in range(9) if not game.board[i]]))
            self.assertIn(game.result, ("O", "draw"))

    def test_but_she_does_make_mistakes(self):
        rng = random.Random(11)
        results = set()
        for _ in range(200):
            game = games.TicTacToe(rng, mistakes=0.5)
            while game.result is None:
                game.play(rng.choice([i for i in range(9) if not game.board[i]]))
            results.add(game.result)
        self.assertIn("X", results)  # you can beat her
        self.assertIsNone(games.TicTacToe().play(42))  # not a cell


class PixelBlockTests(unittest.TestCase):
    def test_finds_the_size_of_art_pixels(self):
        from PySide6.QtGui import QColor, QImage

        from deskmate.companion import pixel_block

        image = QImage(60, 60, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        for x in range(0, 60, 12):
            for y in range(0, 60, 12):
                if (x + y) // 12 % 2:
                    for dx in range(12):
                        for dy in range(12):
                            image.setPixelColor(x + dx, y + dy, QColor(200, 50, 50))
        self.assertEqual(pixel_block(image), 12)



if __name__ == "__main__":
    unittest.main()
