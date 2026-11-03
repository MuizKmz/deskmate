"""'A new me is out!': checks GitHub for a newer DeskMate release. Pure Python, no Qt.

It only asks GitHub's public API for the latest release of MuizKmz/deskmate (no account,
nothing about you is sent). DeskMate doesn't install anything by itself: she tells you, and
the menu opens the download page.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Callable

REPO = "MuizKmz/deskmate"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
CHECK_EVERY = 24 * 3600  # seconds


@dataclass(frozen=True)
class Release:
    version: str  # "0.6.1"
    url: str      # the release page


def version_tuple(text: str) -> tuple[int, ...]:
    """'v0.6.1' -> (0, 6, 1). Anything after the numbers (like '-beta') is ignored."""
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(n) for n in match.group(1).split(".")) if match else ()


def is_newer(candidate: str, current: str) -> bool:
    new, old = version_tuple(candidate), version_tuple(current)
    if not new or not old:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def fetch_latest(timeout: float = 10.0) -> dict:
    request = urllib.request.Request(LATEST, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": "DeskMate-update-check"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def check(current: str, fetch: Callable[[], dict] = fetch_latest) -> Release | None:
    """The newer release, or None if this is the latest (raises if GitHub can't be reached)."""
    data = fetch()
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name", ""))
    if not is_newer(tag, current):
        return None
    url = str(data.get("html_url") or RELEASES_PAGE)
    if not url.startswith("https://github.com/"):  # only ever open GitHub pages
        url = RELEASES_PAGE
    return Release(".".join(map(str, version_tuple(tag))), url)
