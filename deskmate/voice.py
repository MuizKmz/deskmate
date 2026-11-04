"""Her voice: she can say her lines out loud. No Qt in here.

Two voices:

* **Windows voice**: the speech engine built into Windows (free, offline). Run through a
  hidden PowerShell, so nothing extra has to be installed. Any voice installed on Windows can
  be picked by name (``list_windows_voices``).
* **Natural voice**: a natural-sounding voice from a server that speaks OpenAI's
  ``/audio/speech`` protocol: OpenAI itself (uses the chat key, costs a little per line), or
  your own server on your PC, like Kokoro-FastAPI (free, offline, dozens of voices). The clip
  comes back as WAV and is played with Python's own ``winsound``.

``Speaker`` decides what to say and with which voice; it never blocks the window (slow parts
run on a thread) and falls back to the Windows voice if OpenAI can't be reached.
"""

from __future__ import annotations

import array
import base64
import json
import logging
import struct
import re
import subprocess
import sys
import random
import threading
import time
from typing import Callable

from .chat import ChatConfig, ChatError, _request, list_models

log = logging.getLogger(__name__)

MODES = ("off", "windows", "openai")
OPENAI_VOICES = ("nova", "shimmer", "coral", "alloy", "sage", "fable")
OWN_SERVER_URL = "http://localhost:8880/v1"  # where Kokoro-FastAPI listens by default
OWN_SERVER_VOICE = "af_heart"  # a Kokoro voice, for when none is chosen yet
MAX_SPOKEN = 300
STYLE = ("Speak softly and sweetly, a little sleepy, like a shy anime girl talking to a close friend. "
         "Keep a gentle, warm tone.")


def clean_for_speech(text: str) -> str:
    """What the bubble shows isn't always what a voice should read out."""
    text = re.sub(r"\*([^*]{1,30})\*", r"\1", text or "")   # *yawn* -> yawn
    text = re.sub(r"[~*_`#<>]+", "", text)                   # cute decorations
    text = re.sub(r"\.{2,}|…", ", ", text)                   # "Mmh..." -> "Mmh, " (a short pause)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", text)  # emoji
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return text[:MAX_SPOKEN]


# ---------------------------------------------------------------- Windows voice
# The input is: the voice's name on the first line (empty = the first female voice), then the text.
_PS_SCRIPT = r"""
[Console]::InputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$name, $text = [Console]::In.ReadToEnd() -split "`n", 2
$name = "$name".Trim()
$chosen = $false
if ($name) { try { $s.SelectVoice($name); $chosen = $true } catch { } }
if (-not $chosen) {
  $v = $s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo } | Where-Object { $_.Gender -eq 'Female' } | Select-Object -First 1
  if ($v) { $s.SelectVoice($v.Name) }
}
$s.Rate = 1
$s.Speak("$text")
"""

_PS_LIST = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$list = @($s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
  [pscustomobject]@{ name = $_.VoiceInfo.Name; gender = "$($_.VoiceInfo.Gender)"; culture = "$($_.VoiceInfo.Culture)" } })
[Console]::OutputEncoding = [Text.Encoding]::UTF8
ConvertTo-Json -InputObject $list -Compress
"""


def powershell_command(script: str = _PS_SCRIPT) -> list[str]:
    """A hidden PowerShell running ``script`` (the text to speak goes in through its input)."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def list_windows_voices(run=subprocess.run) -> list[dict]:
    """The voices installed on Windows: [{"name", "gender", "culture"}]. Empty elsewhere or on failure.

    Slow-ish (it starts PowerShell): call it from a background thread.
    """
    if run is subprocess.run and sys.platform != "win32":
        return []
    try:
        result = run(powershell_command(_PS_LIST), capture_output=True, timeout=30,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads((result.stdout or b"").decode("utf-8", "replace").strip() or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        log.warning("Couldn't list the Windows voices", exc_info=True)
        return []
    data = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
    return [{"name": str(v.get("name", "")), "gender": str(v.get("gender", "")), "culture": str(v.get("culture", ""))}
            for v in data if isinstance(v, dict) and v.get("name")]


def describe_windows_voice(voice: dict) -> str:
    """'Microsoft Zira Desktop (en-US, female)'."""
    extra = ", ".join(x for x in (voice.get("culture", ""), voice.get("gender", "").lower()) if x and x != "notset")
    return f"{voice['name']} ({extra})" if extra else voice["name"]


class WindowsVoice:
    def __init__(self, popen=subprocess.Popen, name: str = ""):
        self._popen = popen
        self._process = None
        self.name = name  # "" = the first female voice

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    def speak(self, text: str) -> None:
        self.stop()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no black console flashing up
        self._process = self._popen(powershell_command(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            self._process.stdin.write(f"{self.name}\n{text}".encode("utf-8"))
            self._process.stdin.close()
        except OSError:
            log.warning("Windows voice couldn't start", exc_info=True)

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
        self._process = None

    def speaking(self) -> bool:
        """Still talking? (Her mouth keeps moving until the hidden PowerShell has finished.)"""
        return self._process is not None and self._process.poll() is None


# ----------------------------------------------------------------- OpenAI voice
def pick_tts_model(models: list[str]) -> str:
    speech = [m for m in models if "tts" in m and "realtime" not in m]
    for marker in ("mini-tts", "tts-1"):
        group = sorted((m for m in speech if marker in m and "hd" not in m), key=len)
        if group:
            return group[0]
    return speech[0] if speech else ""


class OpenAIVoice:
    """A natural voice from OpenAI, or from your own server that speaks the same protocol (e.g. Kokoro).

    ``config.provider`` is "openai" for OpenAI; anything else ("local") is your own server at
    ``config.base_url``, with its own voice names (like "af_bella" or "jf_alpha" on Kokoro).
    """

    def __init__(self, config: ChatConfig, voice: str = "nova", model: str = "", play: Callable[[bytes], None] | None = None):
        self.config = config
        if self.own_server:
            self.voice = voice if voice and voice not in OPENAI_VOICES else OWN_SERVER_VOICE
        else:
            self.voice = voice if voice in OPENAI_VOICES else "nova"
        self.model = model
        self._play = play or play_wav

    @property
    def own_server(self) -> bool:
        return self.config.provider != "openai"

    def synthesize(self, text: str) -> bytes:
        """Blocking (run it on a thread): the WAV clip of ``text`` in her voice."""
        if not self.model:
            if self.own_server:
                try:
                    models = list_models(self.config)
                except ChatError:
                    models = []  # some servers don't list models: Kokoro's name is a safe guess
                self.model = "kokoro" if "kokoro" in models or not models else (pick_tts_model(models) or "kokoro")
            else:
                self.model = pick_tts_model(list_models(self.config)) or "tts-1"
            log.info("Voice model picked automatically: %s", self.model)
        body = {"model": self.model, "voice": self.voice, "input": text, "response_format": "wav"}
        if self.own_server:
            body["stream"] = False  # one whole clip (Kokoro streams by default, and a streamed WAV can't be played)
        elif "tts-1" not in self.model:  # newer OpenAI voices can be told *how* to speak
            body["instructions"] = STYLE
        return fix_wav(_request(self.config, "/audio/speech", body, timeout=30, raw=True))

    def play(self, wav: bytes) -> None:
        self._play(wav)

    def stop(self) -> None:
        stop_wav()


# Kokoro's voice names start with their language: "af_bella" = American English, female.
KOKORO_LANGUAGES = {"a": "American English", "b": "British English", "j": "Japanese", "z": "Chinese",
                    "e": "Spanish", "f": "French", "h": "Hindi", "i": "Italian", "p": "Portuguese"}
SAMPLES = {  # a test line each voice can actually say
    "English": "Hi, it's me~ How do I sound?",
    "Japanese": "こんにちは、わたしの こえは どうですか？",  # kana only: every Japanese voice can read it
    "Chinese": "你好，我的声音听起来怎么样？",
    "Spanish": "Hola, soy yo. ¿Qué tal sueno?",
    "French": "Coucou, c'est moi. Comment je sonne ?",
    "Hindi": "नमस्ते, मेरी आवाज़ कैसी लगती है?",
    "Italian": "Ciao, sono io. Come ti sembra la mia voce?",
    "Portuguese": "Oi, sou eu. Como está a minha voz?",
}


def voice_language(name: str) -> str:
    """The language of a Kokoro voice from its name ("jf_alpha" -> "Japanese"); "" if it can't tell.

    A mix like "af_bella+af_sky" goes by its first voice."""
    first = (name or "").split("+")[0].strip().lower()
    if len(first) >= 3 and first[2] == "_" and first[1] in "fm":
        return KOKORO_LANGUAGES.get(first[0], "")
    return ""


def sample_for(name: str) -> str:
    language = voice_language(name)
    return SAMPLES.get("English" if "English" in language or not language else language, SAMPLES["English"])


def fix_wav(data: bytes) -> bytes:
    """Make sure a voice clip is a WAV the Windows player accepts, or say clearly why it isn't.

    Streamed WAVs often carry 'unknown' sizes in their header (0 or 0xFFFFFFFF), which the player
    refuses without a word; those sizes are fixed here. Raw PCM (Kokoro's "pcm") gets a header.
    Raises ValueError for other formats, empty clips, or silence.
    """
    if not data:
        raise ValueError("The voice server sent an empty clip.")
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        out = bytearray(data)
        position, sample_width, data_start, data_end = 12, 2, -1, len(out)
        while position + 8 <= len(out):
            chunk, size = out[position:position + 4], struct.unpack_from("<I", out, position + 4)[0]
            if chunk == b"fmt ":
                sample_width = max(1, struct.unpack_from("<H", out, position + 22)[0] // 8)
            if chunk == b"data":
                data_start = position + 8
                if size == 0 or data_start + size > len(out):  # "unknown" size: it's the rest of the clip
                    struct.pack_into("<I", out, position + 4, len(out) - data_start)
                else:
                    data_end = data_start + size
                break
            position += 8 + size + (size & 1)
        if data_start < 0:
            raise ValueError("The voice server sent a WAV clip without any sound in it.")
        struct.pack_into("<I", out, 4, len(out) - 8)
        _check_not_silent(bytes(out[data_start:data_end]), sample_width)
        return bytes(out)
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2") or data[:4] in (b"OggS", b"fLaC"):
        raise ValueError("The voice server sent MP3/OGG/FLAC instead of WAV. Is it OpenAI-compatible?")
    if data[:1] in (b"{", b"<"):
        raise ValueError("The voice server sent text instead of a sound clip: " + data[:120].decode("utf-8", "replace"))
    # Raw 16-bit mono PCM at 24 kHz (what Kokoro sends for "pcm"): add a WAV header.
    _check_not_silent(data, 2)
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16, 1, 1, 24000,
                         48000, 2, 16, b"data", len(data))
    return header + data


def _check_not_silent(samples: bytes, width: int) -> None:
    if len(samples) < 2400:  # under ~0.05 s
        raise ValueError("The voice server sent an empty clip. Does this voice speak the language of the text?")
    if width == 2:
        values = array.array("h", samples[: len(samples) - len(samples) % 2])
        if sys.byteorder == "big":
            values.byteswap()
        if max(abs(min(values)), abs(max(values))) < 200:
            raise ValueError("The clip is silent. Does this voice speak the language of the text?")


class PackVoice(OpenAIVoice):
    """The Natural voice from the built-in voice pack (deskmate/voicepack.py), started when first needed."""

    def __init__(self, pack, voice: str = OWN_SERVER_VOICE, play: Callable[[bytes], None] | None = None):
        super().__init__(ChatConfig(provider="local", base_url="http://127.0.0.1:0/v1"), voice=voice,
                         model="kokoro", play=play)
        self.pack = pack

    def synthesize(self, text: str) -> bytes:
        self.config.base_url = self.pack.ensure_running()  # (blocking: this already runs on a thread)
        return super().synthesize(text)


def list_voices(config: ChatConfig) -> list[str]:
    """Voice names to choose from: OpenAI's own, or what your server offers (Kokoro: GET /audio/voices)."""
    if config.provider == "openai":
        return list(OPENAI_VOICES)
    data = _request(config, "/audio/voices", timeout=10)
    items = data.get("voices", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    names = [item if isinstance(item, str) else str(item.get("id") or item.get("name") or "")
             for item in items if isinstance(item, (str, dict))]
    return sorted(n for n in names if n)


def play_wav(wav: bytes) -> None:
    """Play a WAV clip without blocking (Windows; elsewhere it's silently skipped)."""
    if sys.platform != "win32" or not wav:
        return
    import winsound

    def run() -> None:
        try:
            winsound.PlaySound(wav, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except RuntimeError:
            log.warning("Couldn't play her voice", exc_info=True)

    threading.Thread(target=run, name="deskmate-voice", daemon=True).start()


def stop_wav() -> None:
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(None, 0)


# ---------------------------------------------------------------------- Speaker
# ------------------------------------------------------------------ her mouth
def wav_envelope(wav: bytes, step: float = 0.05) -> list[float]:
    """How loud a (16-bit) WAV clip is every ``step`` seconds, from 0 to 1. Empty if it can't tell."""
    try:
        position, rate, channels, width, data = 12, 24000, 1, 2, b""
        while position + 8 <= len(wav):
            chunk, size = wav[position:position + 4], struct.unpack_from("<I", wav, position + 4)[0]
            if chunk == b"fmt ":
                channels, rate = struct.unpack_from("<HI", wav, position + 10)
                width = struct.unpack_from("<H", wav, position + 22)[0] // 8
            elif chunk == b"data":
                data = wav[position + 8:position + 8 + size]
                break
            position += 8 + size + (size & 1)
        if width != 2 or not data:
            return []
        samples = array.array("h", data[: len(data) - len(data) % 2])
        if sys.byteorder == "big":
            samples.byteswap()
        window = max(1, int(rate * step) * channels)
        levels = []
        for start in range(0, len(samples), window):
            part = samples[start:start + window]
            levels.append((sum(v * v for v in part[::4]) / max(1, len(part[::4]))) ** 0.5)
        loudest = max(levels, default=0) or 1
        return [level / loudest for level in levels]
    except (struct.error, ValueError):
        return []


class Mouth:
    """Is her mouth open right now? One of these runs for each line she says.

    * With an ``envelope`` (how loud her voice clip is, every ``step`` seconds): open on loud
      parts, closed in the quiet ones: real lip-sync.
    * Without one (the Windows voice, or no voice at all while the bubble types): a natural
      talking rhythm, until ``until`` (a time) or for as long as ``alive()`` says she's talking.
    """

    OPEN, CLOSE = 0.30, 0.16  # loudness to open / to close again (a little gap, so it doesn't flicker)

    def __init__(self, envelope: list[float] | None = None, step: float = 0.05, until: float | None = None,
                 alive: Callable[[], bool] | None = None, delay: float = 0.0,
                 clock: Callable[[], float] = time.monotonic, rng: random.Random | None = None):
        self.envelope, self.step, self.until, self.alive = envelope, step, until, alive
        self.clock = clock
        self.start = clock() + delay
        self._open = False
        rng = rng or random.Random()
        self._rhythm = []  # (seconds open, seconds closed), syllable by syllable
        t = 0.0
        while t < 120:
            pair = (rng.uniform(0.08, 0.17), rng.uniform(0.05, 0.11))
            self._rhythm.append(pair)
            t += sum(pair)

    def state(self, now: float | None = None) -> str:
        """'open', 'closed', or 'done' (she has finished this line)."""
        now = self.clock() if now is None else now
        if now < self.start:
            return "closed"
        t = now - self.start
        if self.envelope is not None:
            index = int(t / self.step)
            if index >= len(self.envelope):
                return "done"
            level = self.envelope[index]
            self._open = level >= (self.CLOSE if self._open else self.OPEN)
            return "open" if self._open else "closed"
        if self.until is not None and now >= self.until:
            return "done"
        if self.alive is not None and not self.alive():
            return "done"
        for opened, closed in self._rhythm:
            if t < opened:
                return "open"
            if t < opened + closed:
                return "closed"
            t -= opened + closed
        return "closed"


# Windows voices say their language as a culture code ("ja-JP"): the language she'd speak with it.
CULTURE_LANGUAGES = {"ja": "Japanese", "zh": "Chinese", "ko": "Korean", "es": "Spanish", "fr": "French",
                     "de": "German", "it": "Italian", "pt": "Portuguese", "hi": "Hindi", "ms": "Malay",
                     "id": "Indonesian", "th": "Thai", "vi": "Vietnamese", "ru": "Russian", "ar": "Arabic"}


def culture_language(culture: str) -> str:
    """'ja-JP' -> 'Japanese'; '' for English or anything unknown."""
    return CULTURE_LANGUAGES.get((culture or "").split("-")[0].lower(), "")


class Speaker:
    """Decides whether and how she says a line.

    ``run_in_background(work, done)`` is how slow work leaves the window's thread
    (the app passes chatbox.Background().run; tests pass something simple).

    If her voice speaks another language (``language()`` returns e.g. "Japanese"), she says the
    line in that language: the version that came with it (``say(..., spoken=...)``, written by the
    chat brain together with the reply), or else ``translate(line, language)``. The bubble keeps
    the English text. If translating fails, she just says it in English.
    """

    def __init__(self, windows: WindowsVoice, openai: OpenAIVoice | None,
                 run_in_background: Callable, mode: str = "off", everything: bool = True,
                 hush: Callable[[], bool] | None = None, language: Callable[[], str] | None = None,
                 translate: Callable[[str, str], str] | None = None,
                 on_mouth: Callable[["Mouth | None"], None] | None = None):
        self.windows = windows
        self.openai = openai
        self._run = run_in_background
        self.mode = mode if mode in MODES else "off"
        self.everything = everything  # every line she says, or only her chat replies
        self.hush = hush or (lambda: False)  # True while she must not talk out loud (you're in a call)
        self.language = language or (lambda: "")  # the language her voice speaks, if not English
        self.translate = translate
        self.on_mouth = on_mouth  # told when her voice starts (with a Mouth to move her lips) or stops (None)
        self._turn = 0  # newer lines win over older, still-loading ones

    def wants(self, kind: str) -> bool:
        return self.mode != "off" and (self.everything or kind == "chat")

    def say(self, text: str, kind: str = "line", spoken: str = "") -> bool:
        """Speak ``text`` if the settings say so. Returns True if she'll speak it.

        ``spoken``: the same line in her voice's language, if the chat brain wrote one."""
        line = clean_for_speech(text)
        if not line or not self.wants(kind):
            return False
        try:
            if self.hush():
                return False  # the bubble still shows it; she just doesn't say it out loud
        except Exception:
            log.warning("Couldn't tell if you're in a call", exc_info=True)
        self.stop()
        self._turn += 1
        turn = self._turn
        try:
            target = self.language()
        except Exception:
            target = ""
        if target and clean_for_speech(spoken):
            return self._speak(clean_for_speech(spoken), line, turn)
        if target and self.translate is not None:
            def translated(ok: bool, value) -> None:
                if turn != self._turn:
                    return  # she has already moved on to another line
                if not ok:
                    log.warning("Couldn't translate her line (%s); saying it in English", value)
                self._speak(clean_for_speech(value) if ok and value else line, line, turn)
            self._run(lambda: self.translate(line, target), translated)
            return True
        return self._speak(line, line, turn)

    def _speak(self, spoken: str, english: str, turn: int) -> bool:
        if self.mode == "openai" and self.openai is not None:
            def done(ok: bool, value) -> None:
                if turn != self._turn:
                    return  # she has already moved on to another line
                if ok:
                    self.openai.play(value)
                    self._mouth(Mouth(envelope=wav_envelope(value)))  # lips in time with the clip
                else:
                    log.warning("Natural voice failed (%s); using the Windows voice", value)
                    self._windows(english)  # (the Windows voice may not speak the other language)
            self._run(lambda: self.openai.synthesize(spoken), done)
            return True
        return self._windows(spoken)

    def _windows(self, spoken: str) -> bool:
        if not self.windows.available():
            return False
        try:
            self.windows.speak(spoken)
        except OSError:
            log.warning("Windows voice failed", exc_info=True)
            return False
        speaking = getattr(self.windows, "speaking", None)
        # PowerShell takes a moment to start talking; then the mouth moves until it's done.
        self._mouth(Mouth(alive=speaking if callable(speaking) else None, delay=0.6,
                          until=None if callable(speaking) else time.monotonic() + 0.6 + 0.07 * len(spoken)))
        return True

    def _mouth(self, mouth: "Mouth | None") -> None:
        if self.on_mouth is not None:
            try:
                self.on_mouth(mouth)
            except Exception:
                log.warning("Couldn't move her mouth", exc_info=True)

    def stop(self) -> None:
        self._turn += 1
        self.windows.stop()
        if self.openai is not None:
            self.openai.stop()
        self._mouth(None)
