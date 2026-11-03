import unittest

from deskmate.updates import RELEASES_PAGE, Release, check, is_newer, version_tuple


class VersionTests(unittest.TestCase):
    def test_reading_versions(self):
        self.assertEqual(version_tuple("v0.6.1"), (0, 6, 1))
        self.assertEqual(version_tuple("1.2"), (1, 2))
        self.assertEqual(version_tuple("v2.0.0-beta"), (2, 0, 0))
        self.assertEqual(version_tuple("nonsense"), ())

    def test_comparing(self):
        self.assertTrue(is_newer("v0.6.1", "0.6.0"))
        self.assertTrue(is_newer("v0.10.0", "0.9.9"))  # numbers, not letters: 10 > 9
        self.assertTrue(is_newer("v1.0", "0.9.9"))
        self.assertFalse(is_newer("v0.6.0", "0.6"))     # same version
        self.assertFalse(is_newer("v0.5.0", "0.6.0"))   # older
        self.assertFalse(is_newer("garbage", "0.6.0"))


class CheckTests(unittest.TestCase):
    def test_newer_release_found(self):
        data = {"tag_name": "v0.7.0", "html_url": "https://github.com/MuizKmz/deskmate/releases/tag/v0.7.0"}
        self.assertEqual(check("0.6.0", fetch=lambda: data),
                         Release("0.7.0", "https://github.com/MuizKmz/deskmate/releases/tag/v0.7.0"))

    def test_up_to_date_drafts_and_odd_links(self):
        self.assertIsNone(check("0.6.0", fetch=lambda: {"tag_name": "v0.6.0"}))
        self.assertIsNone(check("0.6.0", fetch=lambda: {"tag_name": "v0.9.0", "prerelease": True}))
        odd = check("0.6.0", fetch=lambda: {"tag_name": "v0.9.0", "html_url": "https://evil.example/x"})
        self.assertEqual(odd.url, RELEASES_PAGE)  # only ever opens GitHub


if __name__ == "__main__":
    unittest.main()
