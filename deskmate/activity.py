"""What are you doing right now? (Buddy mode.) Pure Python; asks Windows through ctypes.

``foreground()`` reads the window you're using: the program (``chrome.exe``) and the window
title ("lofi hip hop radio - YouTube - Google Chrome"). That's often enough to know what you're
up to, and it's free and stays on your PC.

``Watcher`` decides *when* she says something: only after you've stayed on something new for
a few seconds (not while you Alt+Tab around), not too often, never twice about the same thing
in a row, and never about private things (incognito windows, password managers, banking) or
while you're in a call.
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
IGNORED_APPS = ("deskmate", "python", "pythonw", "shellexperiencehost", "searchhost", "startmenuexperiencehost",
                "lockapp", "applicationframehost", "textinputhost", "snippingtool", "screenclippinghost")


@dataclass(frozen=True)
class Activity:
    app: str    # "Chrome"
    title: str  # "lofi hip hop radio - YouTube" (browser name taken off)
    exe: str = ""

    @property
    def key(self) -> str:
        """What counts as 'something new': the app plus the title, without counters like '(3)'."""
        title = re.sub(r"^\(\d+\)\s*", "", self.title.lower())  # "(3) YouTube" -> "youtube"
        return f"{self.app.lower()}|{title.strip()}"

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


def make_activity(exe_path: str, title: str) -> Activity | None:
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
    return Activity(app, title[:160], exe)


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
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe_path = ""
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        try:
            size = wintypes.DWORD(1024)
            path = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                exe_path = path.value
        finally:
            kernel32.CloseHandle(handle)
    return make_activity(exe_path, buffer.value)


# How often she may speak up: (minimum seconds between comments, comments per hour at most)
CHATTINESS = {"quiet": (600, 4), "normal": (240, 8), "chatty": (90, 16)}


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
