"""Her voice: she can say her lines out loud. No Qt in here.

Two voices:

* **Windows voice**: the speech engine built into Windows (free, offline). Run through a
  hidden PowerShell, so nothing extra has to be installed.
* **OpenAI voice**: a natural-sounding voice from the OpenAI API (uses the chat key, costs a
  little per line). The clip comes back as WAV and is played with Python's own ``winsound``.

``Speaker`` decides what to say and with which voice; it never blocks the window (slow parts
run on a thread) and falls back to the Windows voice if OpenAI can't be reached.
"""

from __future__ import annotations

import base64
import logging
import re
import subprocess
import sys
import threading
from typing import Callable

from .chat import ChatConfig, _request, list_models

log = logging.getLogger(__name__)

MODES = ("off", "windows", "openai")
OPENAI_VOICES = ("nova", "shimmer", "coral", "alloy", "sage", "fable")
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
_PS_SCRIPT = r"""
[Console]::InputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo } | Where-Object { $_.Gender -eq 'Female' } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.Name) }
$s.Rate = 1
$s.Speak([Console]::In.ReadToEnd())
"""


def powershell_command() -> list[str]:
    """The hidden PowerShell that reads the text from its input and speaks it."""
    encoded = base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


class WindowsVoice:
    def __init__(self, popen=subprocess.Popen):
        self._popen = popen
        self._process = None

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    def speak(self, text: str) -> None:
        self.stop()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no black console flashing up
        self._process = self._popen(powershell_command(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            self._process.stdin.write(text.encode("utf-8"))
            self._process.stdin.close()
        except OSError:
            log.warning("Windows voice couldn't start", exc_info=True)

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
        self._process = None


# ----------------------------------------------------------------- OpenAI voice
def pick_tts_model(models: list[str]) -> str:
    speech = [m for m in models if "tts" in m and "realtime" not in m]
    for marker in ("mini-tts", "tts-1"):
        group = sorted((m for m in speech if marker in m and "hd" not in m), key=len)
        if group:
            return group[0]
    return speech[0] if speech else ""


class OpenAIVoice:
    def __init__(self, config: ChatConfig, voice: str = "nova", model: str = "", play: Callable[[bytes], None] | None = None):
        self.config = config
        self.voice = voice if voice in OPENAI_VOICES else "nova"
        self.model = model
        self._play = play or play_wav

    def synthesize(self, text: str) -> bytes:
        """Blocking (run it on a thread): the WAV clip of ``text`` in her voice."""
        if not self.model:
            self.model = pick_tts_model(list_models(self.config)) or "tts-1"
            log.info("Voice model picked automatically: %s", self.model)
        body = {"model": self.model, "voice": self.voice, "input": text, "response_format": "wav"}
        if "tts-1" not in self.model:  # the newer voice models can be told *how* to speak
            body["instructions"] = STYLE
        return _request(self.config, "/audio/speech", body, timeout=30, raw=True)

    def play(self, wav: bytes) -> None:
        self._play(wav)

    def stop(self) -> None:
        stop_wav()


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
class Speaker:
    """Decides whether and how she says a line.

    ``run_in_background(work, done)`` is how slow work leaves the window's thread
    (the app passes chatbox.Background().run; tests pass something simple).
    """

    def __init__(self, windows: WindowsVoice, openai: OpenAIVoice | None,
                 run_in_background: Callable, mode: str = "off", everything: bool = False):
        self.windows = windows
        self.openai = openai
        self._run = run_in_background
        self.mode = mode if mode in MODES else "off"
        self.everything = everything
        self._turn = 0  # newer lines win over older, still-loading ones

    def wants(self, kind: str) -> bool:
        return self.mode != "off" and (self.everything or kind == "chat")

    def say(self, text: str, kind: str = "line") -> bool:
        """Speak ``text`` if the settings say so. Returns True if she'll speak it."""
        spoken = clean_for_speech(text)
        if not spoken or not self.wants(kind):
            return False
        self.stop()
        self._turn += 1
        turn = self._turn
        if self.mode == "openai" and self.openai is not None:
            def done(ok: bool, value) -> None:
                if turn != self._turn:
                    return  # she has already moved on to another line
                if ok:
                    self.openai.play(value)
                else:
                    log.warning("OpenAI voice failed (%s); using the Windows voice", value)
                    self._windows(spoken)
            self._run(lambda: self.openai.synthesize(spoken), done)
            return True
        return self._windows(spoken)

    def _windows(self, spoken: str) -> bool:
        if not self.windows.available():
            return False
        try:
            self.windows.speak(spoken)
            return True
        except OSError:
            log.warning("Windows voice failed", exc_info=True)
            return False

    def stop(self) -> None:
        self._turn += 1
        self.windows.stop()
        if self.openai is not None:
            self.openai.stop()
