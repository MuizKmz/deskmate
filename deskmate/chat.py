"""Talking with an AI model (Phase 3). Pure Python, no Qt, no extra packages.

Works with any server that speaks the OpenAI "chat completions" protocol:

* OpenAI itself        https://api.openai.com/v1        (needs an API key)
* Ollama on your PC     http://localhost:11434/v1        (free, no key)

The window code calls :meth:`ChatSession.ask` on a background thread, so a slow
network never freezes her. Everything she needs to stay in character (who she is,
her mood, the time, what you talked about today) is put into the messages here.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1"
OLLAMA_URL = "http://localhost:11434/v1"
PROVIDERS = ("openai", "ollama")
MOODS = ("happy", "blush", "pouty", "surprised", "sleepy", "talk")
HISTORY_TURNS = 12  # messages of today's chat sent with every question
MAX_REPLY_CHARS = 260
TIMEOUT = 45.0

_MOOD_TAG = re.compile(r"^\s*\[(\w+)\]\s*")


class ChatError(Exception):
    """Something went wrong; ``kind`` says what, so she can explain it in her own words."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind  # no_key | auth | quota | model | offline | timeout | server
        self.detail = detail


@dataclass
class ChatConfig:
    provider: str = "openai"
    model: str = ""  # empty: pick one automatically
    api_key: str = ""
    base_url: str = ""

    @property
    def url(self) -> str:
        return (self.base_url or (OLLAMA_URL if self.provider == "ollama" else OPENAI_URL)).rstrip("/")

    @property
    def needs_key(self) -> bool:
        return self.provider == "openai"


# --------------------------------------------------------------------- the API
def _request(config: ChatConfig, path: str, body: dict | None = None, timeout: float = TIMEOUT) -> dict:
    if config.needs_key and not config.api_key:
        raise ChatError("no_key")
    headers = {"Content-Type": "application/json", "User-Agent": "DeskMate"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(config.url + path, data=data, headers=headers,
                                     method="POST" if body is not None else "GET")
    host = urllib.parse.urlsplit(config.url).hostname or ""
    # Ollama on this PC must never go through a (company / system) proxy.
    opener = (urllib.request.build_opener(urllib.request.ProxyHandler({}))
              if host in ("localhost", "127.0.0.1", "::1") else urllib.request.build_opener())
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = _error_message(error)
        if error.code == 401:
            raise ChatError("auth", detail) from None
        if error.code == 429:
            raise ChatError("quota", detail) from None
        if error.code in (400, 404) and "model" in detail.lower():
            raise ChatError("model", detail) from None
        raise ChatError("server", f"HTTP {error.code}: {detail}") from None
    except TimeoutError:
        raise ChatError("timeout") from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise ChatError("timeout") from None
        raise ChatError("offline", str(error.reason)) from None
    except (OSError, ValueError) as error:
        raise ChatError("server", str(error)) from None


def _error_message(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8", "replace"))
        message = payload.get("error", payload)
        return str(message.get("message", message) if isinstance(message, dict) else message)[:300]
    except Exception:
        return error.reason or ""


def list_models(config: ChatConfig) -> list[str]:
    return sorted(item.get("id", "") for item in _request(config, "/models", timeout=15).get("data", []))


_NOT_CHAT = ("audio", "realtime", "transcribe", "tts", "whisper", "embedding", "image", "dall-e", "sora",
             "moderation", "search", "instruct", "codex", "computer", "babbage", "davinci", "-pro")


def pick_model(models: list[str], provider: str = "openai") -> str:
    """A sensible cheap chat model from what the account can use (names change often)."""
    if provider == "ollama":
        return models[0] if models else ""
    chat = [m for m in models if m.startswith(("gpt-", "o")) and not any(word in m for word in _NOT_CHAT)]
    chat = [m for m in chat if not re.search(r"-\d{4}-\d{2}-\d{2}$", m)]  # skip dated snapshots
    for marker in ("mini", "luna", "nano"):  # small and cheap, but mini is chattier than nano
        group = [m for m in chat if marker in m]
        if group:
            return max(group, key=_version_key)
    return max(chat, key=_version_key) if chat else ""


def _version_key(name: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", name)) or (0,)


# ------------------------------------------------------------------- the chat
def persona_prompt(pack_meta: dict, name: str) -> str:
    personality = pack_meta.get("personality", "friendly")
    persona = pack_meta.get("persona") or ""
    catchphrase = pack_meta.get("catchphrase")
    lines = [
        f"You are {name}, a tiny anime girl who lives on the user's computer desktop as their companion.",
        f"Personality: {personality}.",
    ]
    if persona:
        lines.append(persona)
    if catchphrase:
        lines.append(f'Something you might say: "{catchphrase}"')
    lines += [
        "Stay in character. You are not an AI assistant and never talk about being a language model.",
        "Speak casually and warmly, like a close friend. Replies are 1 or 2 short sentences "
        f"(under {MAX_REPLY_CHARS // 2} characters is ideal), because they appear in a small speech bubble.",
        "You can still help with quick questions, but keep the answer short and in your own voice.",
        "No markdown, lists or emoji codes. A simple ~ or ... is fine.",
        f"Start every reply with your mood in brackets, one of: {', '.join('[' + m + ']' for m in MOODS)}. "
        "Example: [happy] Ehehe, thanks~",
    ]
    return "\n".join(lines)


def situation(now: datetime, mood: str, worked_minutes: float | None) -> str:
    part = ("late at night" if now.hour < 5 else "morning" if now.hour < 12 else
            "afternoon" if now.hour < 18 else "evening")
    text = f"Right now it is {now:%A %H:%M} ({part}). You feel {mood}."
    if worked_minutes and worked_minutes >= 30:
        text += f" The user has been working for about {int(worked_minutes)} minutes without a break."
    return text


def parse_reply(text: str) -> tuple[str, str]:
    """Split ``"[happy] Hello!"`` into ``("happy", "Hello!")`` and tidy it for the bubble."""
    mood = "talk"
    match = _MOOD_TAG.match(text or "")
    if match:
        tag = match.group(1).lower()
        mood = tag if tag in MOODS else "talk"
        text = text[match.end():]
    text = re.sub(r"[*_`#]+", "", text or "")            # markdown the model added anyway
    text = re.sub(r"\[(\w+)\]", "", text)                 # stray mood tags
    text = re.sub(r"\s+", " ", text).strip().strip('"').strip()
    if len(text) > MAX_REPLY_CHARS:
        cut = text[:MAX_REPLY_CHARS]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("~ "))
        text = cut[: end + 1] if end > MAX_REPLY_CHARS // 3 else cut.rstrip() + "..."
    return mood, text or "..."


OFFLINE_LINES = {
    "no_key": "I can't chat yet... right-click me and open Chat settings to give me a key~",
    "auth": "Hmm, that key doesn't work... could you check it in Chat settings?",
    "quota": "My chat credits ran out, or I'm talking too fast... let's try again in a bit.",
    "model": "I couldn't find that model... try Chat settings > Pick for me.",
    "offline": "I can't reach my chat brain... is the internet (or Ollama) on?",
    "timeout": "Sorry, I zoned out... could you say that again?",
    "server": "Something went fuzzy in my head... let's try again later.",
}


@dataclass
class ChatSession:
    """One day of chatting. Today's messages are kept on disk, so she remembers after a restart."""

    config: ChatConfig
    persona: str
    path: Path | None = None
    today: Callable[[], date] = date.today
    history: list[dict] = field(default_factory=list)
    _day: date | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._day = self.today()
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("date") == self._day.isoformat():
                self.history = [m for m in data.get("messages", [])
                                if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
        except (OSError, ValueError, AttributeError):
            log.warning("Chat history unreadable, starting fresh")

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"date": self._day.isoformat(), "messages": self.history[-60:]},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            log.warning("Could not save chat history", exc_info=True)

    def messages(self, user_text: str, context: str = "") -> list[dict]:
        if self.today() != self._day:  # a new day: a fresh start (she was up all night with you?)
            self._day = self.today()
            self.history = []
        system = self.persona + ("\n" + context if context else "")
        return [{"role": "system", "content": system}, *self.history[-HISTORY_TURNS:],
                {"role": "user", "content": user_text}]

    def ask(self, user_text: str, context: str = "") -> tuple[str, str]:
        """Blocking call (run it on a thread). Returns (mood, reply) or raises ChatError."""
        user_text = user_text.strip()[:1000]
        config = self.config
        if not config.model:
            config.model = pick_model(list_models(config), config.provider)
            if not config.model:
                raise ChatError("model", "no chat model found")
            log.info("Chat model picked automatically: %s", config.model)
        payload = {"model": config.model, "messages": self.messages(user_text, context)}
        data = _request(config, "/chat/completions", payload)
        try:
            raw = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ChatError("server", "unexpected reply") from None
        mood, reply = parse_reply(raw)
        self.history += [{"role": "user", "content": user_text},
                         {"role": "assistant", "content": f"[{mood}] {reply}"}]
        self._save()
        return mood, reply

    def forget(self) -> None:
        self.history = []
        self._save()


# ------------------------------------------------------------------- secrets
def load_key(path: Path) -> str:
    """The API key: from the secrets file, or the OPENAI_API_KEY environment variable."""
    try:
        key = json.loads(path.read_text(encoding="utf-8")).get("openai_api_key", "")
        if isinstance(key, str) and key.strip():
            return key.strip()
    except (OSError, ValueError, AttributeError):
        pass
    return os.environ.get("OPENAI_API_KEY", "").strip()


def save_key(path: Path, key: str) -> None:
    """Kept apart from settings.json (and outside the project folder), so it never ends up on GitHub."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"openai_api_key": key.strip()}), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def mask(key: str) -> str:
    return f"{key[:3]}...{key[-4:]}" if len(key) > 10 else ("set" if key else "not set")
