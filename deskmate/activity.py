"""What are you doing right now? (Buddy mode.) Pure Python; asks Windows through ctypes.

``foreground()`` reads the window you're using: the program (``chrome.exe``) and the window
title ("lofi hip hop radio - YouTube - Google Chrome"). That's often enough to know what you're
up to, and it's free and stays on your PC.

``now_playing()`` looks through *all* open windows for music: Spotify shows "Artist - Song" as
its window title, and a YouTube Music tab shows "Song - YouTube Music". So she knows the song
even while it plays in the background behind your code.

``Watcher`` decides *when* she says something: only after you've stayed on something new for
a few seconds (not while you Alt+Tab around), not too often, never twice about the same thing
in a row, and never about private things (incognito windows, password managers, banking) or
while you're in a call. There's one Watcher for what you're doing and one for the music.
"""

from __future__ import annotations

import ctypes
import re
import sys
from dataclasses import dataclass, field
from pathlib import PurePath

APPS = {  # program file -> a name she'd use
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "brave": "Brave", "opera": "Opera",
    "code": "VS Code", "cursor": "Cursor", "idea64": "IntelliJ IDEA", "pycharm64": "PyCharm",
    "devenv": "Visual Studio", "studio64": "Android Studio", "windowsterminal": "Terminal",
    "spotify": "Spotify", "vlc": "VLC", "steam": "Steam", "discord": "Discord", "whatsapp": "WhatsApp",
    "telegram": "Telegram", "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint",
    "outlook": "Outlook", "olk": "Outlook", "notion": "Notion", "figma": "Figma", "obsidian": "Obsidian",
    "explorer": "File Explorer", "notepad": "Notepad", "postman": "Postman", "photoshop": "Photoshop",
    "resolve": "DaVinci Resolve", "obs64": "OBS",
}
BROWSERS = ("Chrome", "Edge", "Firefox", "Brave", "Opera")
# Never looked at, never sent anywhere: she doesn't even mention them.
PRIVATE_WORDS = ("incognito", "inprivate", "private browsing", "password", "1password", "bitwarden", "keepass",
                 "lastpass", "bank", "maybank", "cimb", "paypal", "wallet", "login", "sign in", "log in")
PRIVATE_APPS = ("keepass", "1password", "bitwarden", "lastpass")
# She stays quiet while you're in a call.
QUIET_APPS = ("teams", "ms-teams", "zoom", "webex", "skype")
QUIET_WORDS = ("meet.google.com", "google meet", "zoom meeting", "microsoft teams", "| microsoft teams")
MUSIC_APPS = {"spotify": "Spotify", "applemusic": "Apple Music", "amazon music": "Amazon Music"}
IGNORED_APPS = ("deskmate", "python", "pythonw", "shellexperiencehost", "searchhost", "startmenuexperiencehost",
                "lockapp", "applicationframehost", "textinputhost", "snippingtool", "screenclippinghost")


@dataclass(frozen=True)
class Activity:
    app: str    # "Chrome"
    title: str  # "lofi hip hop radio - YouTube" (browser name taken off)
    exe: str = ""
    # Where the window is on screen, in Windows' (physical) pixels: left, top, right, bottom.
    # Her picture is cut to this window, so she sees what you're using (not another monitor).
    bounds: tuple[int, int, int, int] | None = field(default=None, compare=False)
    kind: str = "app"  # "app": what you're doing; "music": the song that's playing

    @property
    def key(self) -> str:
        """What counts as 'something new': the app plus the title, without counters like '(3)'."""
        if self.kind == "app" and self.music_player:
            return f"{self.app.lower()}|music"  # a new song isn't a new app: the music Watcher handles songs
        title = re.sub(r"^\(\d+\)\s*", "", self.title.lower())  # "(3) YouTube" -> "youtube"
        return f"{self.kind}|{self.app.lower()}|{title.strip()}"

    @property
    def music_player(self) -> bool:
        return self.exe in MUSIC_APPS or self.title.endswith("YouTube Music")

    def describe(self) -> str:
        return f"{self.app}: {self.title}" if self.title else self.app

    @property
    def private(self) -> bool:
        text = f"{self.exe} {self.title}".lower()
        return self.exe in PRIVATE_APPS or any(word in text for word in PRIVATE_WORDS)

    @property
    def quiet(self) -> bool:
        text = self.title.lower()
        return self.exe in QUIET_APPS or any(word in text for word in QUIET_WORDS)


def make_activity(exe_path: str, title: str, bounds: tuple[int, int, int, int] | None = None) -> Activity | None:
    """Turn a program path + window title into an Activity (None for things not worth a word)."""
    exe = PurePath(exe_path.replace("\\", "/")).stem.lower() if exe_path else ""
    title = re.sub(r"\s+", " ", title or "").strip()
    if not title or exe in IGNORED_APPS or title in ("Program Manager", "Task Switching", "Task View"):
        return None
    app = APPS.get(exe, exe.replace("-", " ").title() if exe else "an app")
    if app in BROWSERS:  # "... - YouTube - Google Chrome" -> "... - YouTube"
        title = re.sub(r"\s+[-—–]\s+(Google Chrome|Microsoft​? Edge|Mozilla Firefox|Brave|Opera)$", "", title)
        title = re.sub(r"\s+and \d+ more pages?$", "", title)  # Edge: "X and 3 more pages"
    elif title.endswith(f" - {app}"):
        title = title[: -len(app) - 3]
    return Activity(app, title[:160], exe, bounds)


def music_from(activity: Activity | None) -> Activity | None:
    """The song in a window, if it's a music player that's playing something (else None)."""
    if activity is None or activity.private:
        return None
    title = re.sub(r"^\(\d+\)\s*", "", activity.title).strip()
    if activity.exe in MUSIC_APPS:
        # Spotify: "Artist - Song" while playing; just "Spotify" / "Spotify Premium" when paused.
        if " - " not in title or title.lower().startswith(("spotify", "apple music", "amazon music")):
            return None
        return Activity(MUSIC_APPS[activity.exe], title, activity.exe, kind="music")
    if activity.app in BROWSERS and title.endswith(" - YouTube Music"):
        song = title[: -len(" - YouTube Music")].strip()
        return Activity("YouTube Music", song, activity.exe, kind="music") if song else None
    return None


def now_playing(windows: list[tuple[str, str]]) -> Activity | None:
    """The song playing, from all open windows' (program path, title). Pure, so it's easy to test."""
    for exe_path, title in windows:
        song = music_from(make_activity(exe_path, title))
        if song is not None:
            return song
    return None


def playing() -> Activity | None:
    """The song playing right now in Spotify / YouTube Music (Windows only), or None."""
    if sys.platform != "win32":
        return None
    try:
        return now_playing(_windows_titles())
    except Exception:
        return None


def _windows_titles() -> list[tuple[str, str]]:
    """(program path, title) of every visible top-level window."""
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            found.append(hwnd)
        return True

    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows(callback_type(collect), 0)
    return [(_exe_of(hwnd), _title_of(hwnd)) for hwnd in found]


def _title_of(hwnd) -> str:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _exe_of(hwnd) -> str:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        path = ctypes.create_unicode_buffer(size.value)
        return path.value if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)) else ""
    finally:
        kernel32.CloseHandle(handle)


def foreground() -> Activity | None:
    """The window you're using right now (Windows only; None elsewhere or if it can't tell)."""
    if sys.platform != "win32":
        return None
    try:
        return _windows_foreground()
    except Exception:
        return None


def _windows_foreground() -> Activity | None:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    title, exe_path = _title_of(hwnd), _exe_of(hwnd)
    rect = wintypes.RECT()
    bounds = None
    try:  # the visible frame (without the invisible resize border); plain window rect as a fallback
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        ok = dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0
    except OSError:
        ok = False
    if ok or user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        bounds = (rect.left, rect.top, rect.right, rect.bottom)
    return make_activity(exe_path, title, bounds)


# How often she may speak up: (minimum seconds between comments, comments per hour at most)
CHATTINESS = {"quiet": (600, 4), "normal": (240, 8), "chatty": (90, 16)}
MUSIC_CHATTINESS = {"quiet": (1200, 2), "normal": (480, 4), "chatty": (240, 8)}  # songs: rarer


@dataclass
class Watcher:
    """Decides when something you're doing is worth a comment. Give it ``now`` and what you're on."""

    gap: float = 240.0       # seconds between her comments, at least
    per_hour: int = 8
    settle: float = 8.0      # you must stay on something this long (no comments while you Alt+Tab)
    ask_gap: float = 60.0    # even when she decides to stay quiet, she doesn't ask her brain more often
    forget_after: float = 1800.0  # after this long, the same thing can be mentioned again
    _current: Activity | None = field(default=None, init=False)
    _since: float = field(default=0.0, init=False)
    _last_comment: float = field(default=-1e9, init=False)
    _last_ask: float = field(default=-1e9, init=False)
    _recent: list[float] = field(default_factory=list, init=False)
    _mentioned: dict[str, float] = field(default_factory=dict, init=False)

    @classmethod
    def with_chattiness(cls, level: str) -> "Watcher":
        gap, per_hour = CHATTINESS.get(level, CHATTINESS["normal"])
        return cls(gap=gap, per_hour=per_hour)

    @classmethod
    def for_music(cls, level: str) -> "Watcher":
        """Songs change every few minutes: she comments on some of them, not each one."""
        gap, per_hour = MUSIC_CHATTINESS.get(level, MUSIC_CHATTINESS["normal"])
        return cls(gap=gap, per_hour=per_hour, settle=15.0, ask_gap=120.0, forget_after=3 * 3600.0)

    def observe(self, now: float, activity: Activity | None) -> Activity | None:
        """What she should comment on now, if anything."""
        if activity is None:
            return None
        if self._current is None or activity.key != self._current.key:
            self._current, self._since = activity, now
            return None
        if now - self._since < self.settle or activity.private or activity.quiet:
            return None
        if now - self._last_comment < self.gap or now - self._last_ask < self.ask_gap:
            return None
        self._recent = [t for t in self._recent if now - t < 3600]
        if len(self._recent) >= self.per_hour:
            return None
        if now - self._mentioned.get(activity.key, -1e9) < self.forget_after:
            return None
        return activity

    def mentioned(self, now: float, activity: Activity, spoke: bool) -> None:
        """Call after asking her about ``activity`` (``spoke``: she actually said something)."""
        self._mentioned[activity.key] = now  # even if she skipped it: don't ask again about the same thing
        self._last_ask = now
        if spoke:
            self._last_comment = now
            self._recent.append(now)

    def hold(self, now: float) -> None:
        """You're chatting (or she just talked): wait a full gap before speaking up again."""
        self._last_comment = now
