"""Talking with an AI model (Phase 3). Pure Python, no Qt, no extra packages.

Works with any server that speaks the OpenAI "chat completions" protocol:

* OpenAI itself        https://api.openai.com/v1        (needs an API key)
* Ollama on your PC     http://localhost:11434/v1        (free, no key)

and with Anthropic's Claude (its own "messages" protocol, also handled here).

She can also *look*: :meth:`ChatSession.show` hands her a screenshot, which goes along with
your next questions for a few minutes (``LOOK_SECONDS``), and her answer then comes in two
parts: a short line for her speech bubble, and the real help (steps, an example, or a
question back) for the chat log.

The window code calls :meth:`ChatSession.ask` on a background thread, so a slow
network never freezes her. Everything she needs to stay in character (who she is,
her mood, the time, what you talked about today) is put into the messages here.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1"
CLAUDE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2026-10-21"  # current API version; DeskMate sends nothing its breaking changes touch
OLLAMA_URL = "http://localhost:11434/v1"
PROVIDERS = ("openai", "claude", "ollama")
KEY_NAMES = {"openai": "openai", "claude": "anthropic"}  # which saved key each provider uses
MODEL_SETTINGS = {"openai": "chat_model", "claude": "claude_model", "ollama": "ollama_model"}
MOODS = ("happy", "blush", "pouty", "surprised", "sleepy", "talk")
HISTORY_TURNS = 12  # messages of today's chat sent with every question
MAX_REPLY_CHARS = 260
MAX_DETAILS_CHARS = 1800
TIMEOUT = 45.0
LOOK_TIMEOUT = 90.0  # reading a picture takes longer
LOOK_SECONDS = 5 * 60  # after you show her your screen, follow-up questions still include it this long
LOOK_TEXT = "Can you take a look at this?"  # what you "say" if you just press Enter

_MOOD_TAG = re.compile(r"^\s*\[(\w+)\]\s*")
_REMIND_TAG = re.compile(r"<remind\s+when\s*=\s*[\"']([^\"'<>]{1,40})[\"']\s*>(.{0,200}?)</remind>", re.I | re.S)


class ChatError(Exception):
    """Something went wrong; ``kind`` says what, so she can explain it in her own words."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind  # no_key | auth | quota | model | vision | offline | timeout | server
        self.detail = detail


@dataclass
class ChatConfig:
    provider: str = "openai"
    model: str = ""  # empty: pick one automatically
    api_key: str = ""
    base_url: str = ""

    @property
    def url(self) -> str:
        default = {"ollama": OLLAMA_URL, "claude": CLAUDE_URL}.get(self.provider, OPENAI_URL)
        return (self.base_url or default).rstrip("/")

    @property
    def needs_key(self) -> bool:
        return self.provider in KEY_NAMES


# --------------------------------------------------------------------- the API
def _request(config: ChatConfig, path: str, body: dict | None = None, timeout: float = TIMEOUT, raw: bool = False):
    """Call the API. Returns the JSON answer, or the raw bytes with ``raw=True`` (e.g. audio)."""
    if config.needs_key and not config.api_key:
        raise ChatError("no_key")
    headers = {"Content-Type": "application/json", "User-Agent": "DeskMate"}
    if config.api_key and config.provider == "claude":  # Anthropic's own way of sending the key
        headers["x-api-key"] = config.api_key
        headers["anthropic-version"] = ANTHROPIC_VERSION
    elif config.api_key:
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
            payload = response.read()
            return payload if raw else json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = _error_message(error)
        if error.code == 401:
            raise ChatError("auth", detail) from None
        if error.code == 429:
            raise ChatError("quota", detail) from None
        if error.code in (400, 404, 500) and ("image" in detail.lower() or "vision" in detail.lower()):
            raise ChatError("vision", detail) from None  # this model can't see pictures
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
    if provider == "claude":
        claude = [m for m in models if m.startswith("claude")]
        undated = [m for m in claude if not re.search(r"-\d{8}$", m)] or claude
        for family in ("haiku", "sonnet"):  # quick and cheap first: she only says a sentence or two
            group = [m for m in undated if family in m]
            if group:
                return max(group, key=_version_key)
        return max(undated, key=_version_key) if undated else ""
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
        "If (and only if) the user asks you to remind them of something, confirm it in your own words and add "
        'this at the very end: <remind when="15:00">the meeting</remind>. "when" is a clock time like 15:00 or 3pm, '
        'or a delay like "in 20 min". The app shows the reminder at that time, so never say you can\'t do reminders.',
    ]
    return "\n".join(lines)


LOOK_PROMPT = """\
The user is showing you a screenshot of their screen (it is attached to their message). Look at it carefully, \
like a friend sitting right next to them, and help the way a good partner would.
For this reply the format changes. Write two parts, separated by a line with only --- on it.
Part 1: your mood tag, then 1 or 2 short sentences for your speech bubble: what you noticed and your main point.
Part 2: the real help, in plain text (no headings, no bold). Pick what fits best:
- Something is wrong (an error, a bug, a typo, a confusing setting): say what it is and why, then guide \
them with short numbered steps.
- An example would make it click: give one short, concrete example. Put code between ``` lines.
- You can't tell what they want, or the answer depends on something you can't see: ask one clear question \
instead of guessing (you can still say what you would check first).
Keep part 2 under about 150 words. Quote text exactly as it appears on the screen and never pretend to see \
something that isn't there. If you notice passwords, keys or private messages, don't repeat them.
Stay in character the whole time."""


@dataclass(frozen=True)
class Snapshot:
    """A picture of (part of) your screen, ready to send: JPEG bytes. Never written to disk."""

    data: bytes
    width: int
    height: int
    media_type: str = "image/jpeg"

    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


def image_message(text: str, snapshot: Snapshot, provider: str) -> dict:
    """Your message with the picture attached, in the shape each kind of server expects."""
    if provider == "claude":  # Anthropic: an "image" block (picture first, then the question)
        source = {"type": "base64", "media_type": snapshot.media_type, "data": snapshot.base64()}
        return {"role": "user", "content": [{"type": "image", "source": source}, {"type": "text", "text": text}]}
    url = f"data:{snapshot.media_type};base64,{snapshot.base64()}"  # OpenAI and Ollama: an "image_url" part
    return {"role": "user", "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]}


def situation(now: datetime, mood: str, worked_minutes: float | None) -> str:
    part = ("late at night" if now.hour < 5 else "morning" if now.hour < 12 else
            "afternoon" if now.hour < 18 else "evening")
    text = f"Right now it is {now:%A %H:%M} ({part}). You feel {mood}."
    if worked_minutes and worked_minutes >= 30:
        text += f" The user has been working for about {int(worked_minutes)} minutes without a break."
    return text


def extract_reminders(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Take ``<remind when="3pm">the meeting</remind>`` tags out of a reply: (text, [(when, what)])."""
    found = [(m.group(1).strip(), re.sub(r"\s+", " ", m.group(2)).strip()) for m in _REMIND_TAG.finditer(text or "")]
    return _REMIND_TAG.sub("", text or "").strip(), found[:3]


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
    text = re.sub(r"</?remind[^>]*>", "", text)           # a broken reminder tag
    text = re.sub(r"\s+", " ", text).strip().strip('"').strip()
    if len(text) > MAX_REPLY_CHARS:
        cut = text[:MAX_REPLY_CHARS]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("~ "))
        text = cut[: end + 1] if end > MAX_REPLY_CHARS // 3 else cut.rstrip() + "..."
    return mood, text or "..."


_DETAILS_SPLIT = re.compile(r"\n\s*-{3,}\s*\n")


def clean_details(text: str) -> str:
    """Tidy the help part of a look reply: keep lines and code, drop headings, bold and stray tags."""
    text = re.sub(r"</?remind[^>]*>", "", text or "")
    text = re.sub(r"^\s*\[(\w+)\]\s*", "", text)
    text = re.sub(r"^[ \t]*#{1,6}[ \t]+", "", text, flags=re.M)
    text = text.replace("**", "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_DETAILS_CHARS:
        text = text[:MAX_DETAILS_CHARS].rstrip() + "..."
        if text.count("```") % 2:
            text += "\n```"
    return text


def split_look_reply(text: str) -> tuple[str, str]:
    """``"[happy] short --- details"`` -> (bubble part, details). Copes with models that forget the ``---``."""
    text = (text or "").strip()
    parts = _DETAILS_SPLIT.split(text, maxsplit=1)
    if len(parts) == 2:
        return parts[0], clean_details(parts[1])
    match = _MOOD_TAG.match(text)
    body = text[match.end():] if match else text
    if len(body) <= MAX_REPLY_CHARS and "```" not in body:
        return text, ""
    return text, clean_details(body)  # the bubble shows the start, the chat log shows it all


OFFLINE_LINES = {
    "no_key": "I can't chat yet... right-click me and open Chat settings to give me a key~",
    "auth": "Hmm, that key doesn't work... could you check it in Chat settings?",
    "quota": "My chat credits ran out, or I'm talking too fast... let's try again in a bit.",
    "model": "I couldn't find that model... try Chat settings > Pick for me.",
    "vision": "Hmm, my eyes don't work with this model... pick one that can see pictures in Chat settings.",
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
    clock: Callable[[], float] = time.monotonic
    history: list[dict] = field(default_factory=list)
    last_reminders: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)
    last_details: str = field(default="", init=False, repr=False)
    _day: date | None = field(default=None, init=False, repr=False)
    _seeing: Snapshot | None = field(default=None, init=False, repr=False)
    _seen_at: float = field(default=0.0, init=False, repr=False)

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

    # ------------------------------------------------------------- looking
    def show(self, snapshot: Snapshot) -> None:
        """She sees this picture with your next questions (for ``LOOK_SECONDS`` after the last one)."""
        self._seeing = snapshot
        self._seen_at = self.clock()

    @property
    def seeing(self) -> Snapshot | None:
        if self._seeing is not None and self.clock() - self._seen_at > LOOK_SECONDS:
            self._seeing = None  # it's been a while: she stops looking (and stops sending it)
        return self._seeing

    def stop_looking(self) -> None:
        self._seeing = None

    # ----------------------------------------------------------------- chat
    def messages(self, user_text: str, context: str = "", snapshot: Snapshot | None = None) -> list[dict]:
        if self.today() != self._day:  # a new day: a fresh start (she was up all night with you?)
            self._day = self.today()
            self.history = []
        system = self.persona + ("\n" + context if context else "") + ("\n" + LOOK_PROMPT if snapshot else "")
        recent = [{"role": m["role"], "content": ("(showing you my screen) " if m.get("image") else "") + m["content"]}
                  for m in self.history[-HISTORY_TURNS:]]
        last = (image_message(user_text, snapshot, self.config.provider) if snapshot
                else {"role": "user", "content": user_text})
        return [{"role": "system", "content": system}, *recent, last]

    def ask(self, user_text: str, context: str = "") -> tuple[str, str]:
        """Blocking call (run it on a thread). Returns (mood, reply) or raises ChatError.

        If she's looking at a screenshot, it goes along, and the longer help she writes
        ends up in ``last_details`` (and in the chat log).
        """
        snapshot = self.seeing
        user_text = user_text.strip()[:1000] or (LOOK_TEXT if snapshot else "...")
        asked_at = datetime.now().strftime("%H:%M")
        config = self.config
        if not config.model:
            config.model = pick_model(list_models(config), config.provider)
            if not config.model:
                raise ChatError("model", "no chat model found")
            log.info("Chat model picked automatically: %s", config.model)
        messages = self.messages(user_text, context, snapshot)
        timeout = LOOK_TIMEOUT if snapshot else TIMEOUT
        try:
            if config.provider == "claude":  # Anthropic: the persona goes in "system", answers come in blocks
                payload = {"model": config.model, "max_tokens": 1200 if snapshot else 400,
                           "system": messages[0]["content"], "messages": messages[1:]}
                data = _request(config, "/messages", payload, timeout=timeout)
                raw = "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
            else:
                data = _request(config, "/chat/completions", {"model": config.model, "messages": messages},
                                timeout=timeout)
                raw = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ChatError("server", "unexpected reply") from None
        raw, self.last_reminders = extract_reminders(raw)
        head, details = split_look_reply(raw) if snapshot else (raw, "")
        mood, reply = parse_reply(head)
        self.last_details = details
        if snapshot:
            self._seen_at = self.clock()  # still talking about it: keep looking a while longer
        noted = "".join(f' <remind when="{when}">{what}</remind>' for when, what in self.last_reminders)
        sent_at, replied_at = asked_at, datetime.now().strftime("%H:%M")
        mine = {"role": "user", "content": user_text, "time": sent_at}
        if snapshot:
            mine["image"] = True
        answer = f"[{mood}] {reply}{noted}" + (f"\n---\n{details}" if details else "")
        self.history += [mine, {"role": "assistant", "content": answer, "time": replied_at}]
        self._save()
        return mood, reply

    def transcript(self) -> list[dict]:
        """Today's chat for the chat log window: who, clean text, time, and any reminders she set."""
        if self.today() != self._day:
            return []
        lines = []
        for message in self.history:
            if message["role"] == "user":
                lines.append({"role": "user", "text": message["content"], "time": message.get("time", ""),
                              "image": bool(message.get("image"))})
            else:
                head, _, details = message["content"].partition("\n---\n")
                raw, reminders = extract_reminders(head)
                mood, text = parse_reply(raw)
                lines.append({"role": "assistant", "text": text, "mood": mood, "time": message.get("time", ""),
                              "reminders": reminders, "details": details})
        return lines

    def forget(self) -> None:
        self.history = []
        self._save()


# ------------------------------------------------------------------- secrets
def _read_keys(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_key(path: Path, name: str = "openai") -> str:
    """A saved API key ("openai" or "anthropic"), or the OPENAI_API_KEY / ANTHROPIC_API_KEY variable."""
    key = _read_keys(path).get(f"{name}_api_key", "")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return os.environ.get(f"{name.upper()}_API_KEY", "").strip()


def save_key(path: Path, key: str, name: str = "openai") -> None:
    """Kept apart from settings.json (and outside the project folder), so it never ends up on GitHub.
    Each key has its own name in the file, so saving one never erases another."""
    keys = {k: v for k, v in _read_keys(path).items() if k.endswith("_api_key") and isinstance(v, str)}
    keys[f"{name}_api_key"] = key.strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(keys), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def mask(key: str) -> str:
    return f"{key[:3]}...{key[-4:]}" if len(key) > 10 else ("set" if key else "not set")
