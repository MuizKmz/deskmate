"""User settings stored as JSON.

Two rules keep this file safe:

1. **Atomic saves**: write to ``settings.json.tmp`` first, then swap it in with
   ``os.replace``. A crash or power cut can never leave half a file behind.
2. **Never trust what's on disk**: every value is checked. A broken file is
   moved aside (``settings.broken-<time>.json``) and defaults are used, so a bad
   edit can't stop DeskMate from starting.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

# On-screen height of the character, in logical pixels (Windows scaling is applied on top).
SIZES = {"small": 200, "medium": 280, "large": 360}


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_position(value: Any) -> bool:
    if value is None:
        return True
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in value)
        and all(abs(n) < 1_000_000 for n in value)
    )


# key -> (default, validator)
SCHEMA: dict[str, tuple[Any, Callable[[Any], bool]]] = {
    "character": ("yuki", lambda v: isinstance(v, str) and 0 < len(v) < 100),
    "size": ("medium", lambda v: v in SIZES),
    "position": (None, _is_position),
    "visible": (True, _is_bool),
    "always_on_top": (True, _is_bool),
    "chatty": (True, _is_bool),
    "reminders": (True, _is_bool),
    "gravity": (True, _is_bool),
    "wander": (True, _is_bool),
    "perch": (True, _is_bool),
    "voice": ("off", lambda v: v in ("off", "windows", "openai")),
    "voice_lines": ("all", lambda v: v in ("all", "chat")),  # say every line out loud, or only chat replies
    "openai_voice": ("nova", lambda v: isinstance(v, str) and 0 < len(v) < 80),
    "windows_voice": ("", lambda v: isinstance(v, str) and len(v) < 120),  # "" = the first female voice
    "windows_voice_lang": ("", lambda v: isinstance(v, str) and len(v) < 20),  # its culture, e.g. "ja-JP"
    "voice_translate": (True, _is_bool),  # a Japanese voice says her lines in Japanese (text stays English)
    "tts_source": ("openai", lambda v: v in ("openai", "builtin", "local")),  # OpenAI, the voice pack, or your server
    "tts_url": ("http://localhost:8880/v1", lambda v: isinstance(v, str) and v.startswith(("http://", "https://"))),
    "tts_model": ("", lambda v: isinstance(v, str) and len(v) < 120),
    "update_check": (True, _is_bool),
    "update_announced": ("", lambda v: isinstance(v, str) and len(v) < 40),
    "last_update_check": (0.0, lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0),
    "remember": (True, _is_bool),
    "setup_done": (False, _is_bool),  # the first-run setup was finished (or skipped)
    "seen_version": ("", lambda v: isinstance(v, str) and len(v) < 40),  # for the "What's new" window
    "watch_minutes": (60, lambda v: v in (0, 30, 60, 120)),
    "watch_picture": (True, _is_bool),
    "watch_badge": (True, _is_bool),
    "watch_level": ("normal", lambda v: v in ("quiet", "normal", "chatty")),
    "chat_provider": ("openai", lambda v: v in ("openai", "claude", "ollama")),
    "claude_model": ("", lambda v: isinstance(v, str) and len(v) < 120),
    "chat_model": ("", lambda v: isinstance(v, str) and len(v) < 120),
    "ollama_url": ("http://localhost:11434/v1", lambda v: isinstance(v, str) and v.startswith(("http://", "https://"))),
    "ollama_model": ("", lambda v: isinstance(v, str) and len(v) < 120),
    # My day (Phase 8)
    "focus_minutes": (25, lambda v: isinstance(v, int) and not isinstance(v, bool) and 5 <= v <= 180),
    "focus_nudge": (True, _is_bool),  # a gentle word if you drift off to YouTube while focusing
    "day_log": (True, _is_bool),  # keep a little log of the day (app names only) for the wrap-up
    "wrapup": (True, _is_bool),
    "wrapup_hour": (21, lambda v: isinstance(v, int) and not isinstance(v, bool) and 15 <= v <= 23),
    "special_days": (True, _is_bool),
    "birthday": ("", lambda v: isinstance(v, str) and (v == "" or (len(v) == 5 and v[2] == "-"))),  # "MM-DD"
    "country": ("auto", lambda v: isinstance(v, str) and (v == "auto" or len(v) <= 3)),  # holidays: "MY", "" = none
    "region": ("", lambda v: isinstance(v, str) and len(v) <= 10),  # state, e.g. "JHR" (state holidays)
    "payday": (0, lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 31),
    "weather_city": ("", lambda v: isinstance(v, str) and len(v) <= 80),  # "" = no weather
    "stuck_help": (True, _is_bool),  # buddy mode: offer help when you seem stuck on an error
    # More alive (Phase 9)
    "dance": (True, _is_bool),  # dances when music plays in Spotify / YouTube Music
    "outfit": ("", lambda v: isinstance(v, str) and len(v) < 30),  # "" = none
    "outfit_seasonal": (True, _is_bool),  # a party hat on your birthday, a Santa hat at Christmas...
}


class Settings:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, Any] = {key: default for key, (default, _) in SCHEMA.items()}
        self.load()

    # ---------------------------------------------------------------- loading
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("top level is not a JSON object")
        except (OSError, ValueError) as exc:
            self._quarantine(exc)
            return
        for key, value in raw.items():
            if key not in SCHEMA:
                continue  # unknown keys (from an older/newer version) are ignored
            default, valid = SCHEMA[key]
            if valid(value):
                self._data[key] = list(value) if isinstance(value, tuple) else value
            else:
                log.warning("Ignoring invalid setting %s=%r (using %r)", key, value, default)

    def _quarantine(self, exc: Exception) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup: Path | None = self.path.with_name(f"{self.path.stem}.broken-{stamp}{self.path.suffix}")
        try:
            self.path.replace(backup)
        except OSError:
            backup = None
        log.warning("Settings file was unreadable (%s); using defaults. Old file kept as %s", exc, backup)

    # ----------------------------------------------------------------- access
    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in SCHEMA:
            raise KeyError(key)
        if not SCHEMA[key][1](value):
            raise ValueError(f"invalid value for {key}: {value!r}")
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)

    # ----------------------------------------------------------------- saving
    def save(self) -> bool:
        """Write atomically. Returns False (and logs) instead of raising."""
        payload = json.dumps(self._data, indent=2, sort_keys=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        last_error: OSError | None = None
        for attempt in range(5):
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.path)
                return True
            except OSError as exc:  # e.g. antivirus briefly locking the file on Windows
                last_error = exc
                time.sleep(0.05 * (attempt + 1))
        log.error("Could not save settings to %s: %s", self.path, last_error)
        return False
