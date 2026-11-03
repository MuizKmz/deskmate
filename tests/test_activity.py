import unittest

from deskmate.activity import Activity, Watcher, make_activity


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
