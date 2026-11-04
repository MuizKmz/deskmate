import unittest

from deskmate.activity import Activity, Watcher, make_activity, music_from, now_playing


class ActivityTests(unittest.TestCase):
    def test_what_youre_on(self):
        yt = make_activity(r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           "(3) lofi hip hop radio - beats to relax - YouTube - Google Chrome")
        self.assertEqual((yt.app, yt.title), ("Chrome", "(3) lofi hip hop radio - beats to relax - YouTube"))
        self.assertEqual(yt.describe(), "Chrome: (3) lofi hip hop radio - beats to relax - YouTube")
        same = make_activity("chrome.exe", "(4) lofi hip hop radio - beats to relax - YouTube - Google Chrome")
        self.assertEqual(yt.key, same.key)  # a new notification count isn't "something new"
        code = make_activity(r"C:\Users\me\AppData\Local\Programs\Microsoft VS Code\Code.exe",
                             "app.py - deskmate - Visual Studio Code")
        self.assertEqual(code.app, "VS Code")
        self.assertEqual(make_activity("spotify.exe", "Ado - Odo").app, "Spotify")
        self.assertEqual(make_activity("mygame.exe", "Level 3").app, "Mygame")
        for exe, title in (("explorer.exe", "Program Manager"), ("chrome.exe", ""), ("DeskMate.exe", "Chat with Yuki"),
                           ("pythonw.exe", "Yuki")):
            self.assertIsNone(make_activity(exe, title))

    def test_private_and_quiet(self):
        self.assertTrue(make_activity("msedge.exe", "New InPrivate tab - Microsoft\u200b Edge").private)
        self.assertTrue(make_activity("chrome.exe", "Maybank2u - Google Chrome").private)
        self.assertTrue(make_activity("KeePass.exe", "Database.kdbx").private)
        self.assertFalse(make_activity("chrome.exe", "YouTube - Google Chrome").private)
        self.assertTrue(make_activity("ms-teams.exe", "Standup | Microsoft Teams").quiet)
        self.assertTrue(make_activity("chrome.exe", "Meet - abc-defg-hij - meet.google.com - Google Chrome").quiet)


class MusicTests(unittest.TestCase):
    def test_she_hears_whats_playing_even_in_the_background(self):
        windows = [(r"C:\Code\Code.exe", "app.py - deskmate - Visual Studio Code"),
                   (r"C:\Chrome\chrome.exe", "GLORIA (NATURAL Ver.) - YouTube Music - Google Chrome")]
        song = now_playing(windows)
        self.assertEqual((song.app, song.title, song.kind), ("YouTube Music", "GLORIA (NATURAL Ver.)", "music"))
        spotify = now_playing([(r"C:\Spotify\Spotify.exe", "Ado - Villain")])
        self.assertEqual((spotify.app, spotify.title), ("Spotify", "Ado - Villain"))
        for paused in ("Spotify Premium", "Spotify", "Spotify Free"):
            self.assertIsNone(now_playing([("Spotify.exe", paused)]))
        self.assertIsNone(now_playing([("chrome.exe", "YouTube Music - Google Chrome")]))  # just the home page
        self.assertIsNone(now_playing([("chrome.exe", "lofi - YouTube - Google Chrome")]))  # a video, not a song
        self.assertIsNone(music_from(None))

    def test_a_new_song_is_not_a_new_app(self):
        a = make_activity("chrome.exe", "GLORIA - YouTube Music - Google Chrome")
        b = make_activity("chrome.exe", "Villain - YouTube Music - Google Chrome")
        self.assertEqual(a.key, b.key)  # the app Watcher stays quiet; the music Watcher notices
        self.assertNotEqual(music_from(a).key, music_from(b).key)
        self.assertNotEqual(make_activity("chrome.exe", "A - YouTube - Google Chrome").key,
                            make_activity("chrome.exe", "B - YouTube - Google Chrome").key)  # new video: new
        music = Watcher.for_music("normal")
        self.assertGreater(music.gap, Watcher.with_chattiness("normal").gap)  # songs: rarer comments


class CropTests(unittest.TestCase):
    def test_her_picture_is_cut_to_your_window(self):
        try:
            from PySide6.QtCore import QRect
            from PySide6.QtGui import QImage
        except ImportError:  # pragma: no cover
            self.skipTest("PySide6 is not installed")
        from deskmate.look import crop_to_window

        shot = QImage(3000, 1500, QImage.Format.Format_RGB32)  # a 2000 x 1000 screen at 150 %, right of the main one
        screen = QRect(1920, 0, 2000, 1000)
        part = crop_to_window(shot, screen, QRect(2020, 100, 800, 600))
        self.assertEqual((part.width(), part.height()), (1200, 900))
        part = crop_to_window(shot, screen, QRect(3700, 900, 800, 600))  # mostly off this screen
        self.assertEqual(part.width(), 3000)
        self.assertEqual(make_activity("chrome.exe", "YouTube - Google Chrome", (0, 0, 10, 10)),
                         make_activity("chrome.exe", "YouTube - Google Chrome", (5, 5, 50, 50)))  # moving isn't new


class WatcherTests(unittest.TestCase):
    YT = Activity("Chrome", "lofi hip hop radio - YouTube", "chrome")
    CODE = Activity("VS Code", "app.py - deskmate", "code")

    def test_only_after_you_settle_on_something(self):
        w = Watcher(gap=100, per_hour=5, settle=8)
        self.assertIsNone(w.observe(0, self.YT))  # just switched
        self.assertIsNone(w.observe(5, self.YT))  # still Alt+Tabbing?
        self.assertEqual(w.observe(9, self.YT), self.YT)
        w.mentioned(9, self.YT, spoke=True)
        self.assertIsNone(w.observe(12, self.YT))  # never twice about the same thing
        self.assertIsNone(w.observe(13, self.CODE))
        self.assertIsNone(w.observe(30, self.CODE))  # too soon after her last comment
        self.assertEqual(w.observe(110, self.CODE), self.CODE)

    def test_skips_count_too_but_not_toward_the_hourly_limit(self):
        w = Watcher(gap=100, per_hour=1, settle=0, ask_gap=60)
        w.observe(0, self.YT)
        w.mentioned(0, w.observe(1, self.YT), spoke=False)  # she had nothing to say
        w.observe(10, self.CODE)
        self.assertIsNone(w.observe(30, self.CODE))  # doesn't ask her brain again so soon
        self.assertEqual(w.observe(61, self.CODE), self.CODE)
        w.mentioned(61, self.CODE, spoke=True)
        other = Activity("Spotify", "Ado - Odo", "spotify")
        w.observe(200, other)
        self.assertIsNone(w.observe(300, other))  # 1 comment an hour already used
        self.assertEqual(w.observe(3700, other), other)

    def test_never_private_never_in_calls_and_holds_while_chatting(self):
        w = Watcher(settle=0)
        bank = Activity("Chrome", "Maybank2u", "chrome")
        call = Activity("Teams", "Standup | Microsoft Teams", "ms-teams")
        for thing in (bank, call):
            w.observe(0, thing)
            self.assertIsNone(w.observe(500, thing))
        w.hold(1000)  # you're chatting with her
        w.observe(1000, self.YT)
        self.assertIsNone(w.observe(1100, self.YT))
        self.assertEqual(w.observe(1000 + w.gap, self.YT), self.YT)
        self.assertEqual(Watcher.with_chattiness("chatty").gap, 90)


if __name__ == "__main__":
    unittest.main()
