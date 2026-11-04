"""The voice pack's server: POST /v1/audio/speech -> a WAV clip, like OpenAI / Kokoro-FastAPI.

Only listens on 127.0.0.1 (this PC). Quits by itself when DeskMate (``--parent``) is gone.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger("deskmate_voice")

MODEL_FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
# Kokoro voice names start with their language ("jf_alpha" = Japanese, female): how to read the text.
LANGS = {"a": "en-us", "b": "en-gb", "j": "ja", "z": "cmn", "e": "es", "f": "fr-fr", "h": "hi", "i": "it",
         "p": "pt-br"}
KANJI = re.compile(r"[一-鿿㐀-䶿]")


def reading_language(voice: str, lang_code: str | None = None) -> str:
    """The pronunciation to use: the asked-for one (Kokoro's one-letter codes), else the voice's."""
    if lang_code and lang_code[:1] in LANGS:
        return LANGS[lang_code[:1]]
    first = (voice or "").split("+")[0].strip().lower()
    return LANGS.get(first[:1], "en-us")


def prepare(text: str, language: str) -> str:
    """Japanese: the built-in pronunciation only reads kana. Kanji would be read out as 'Chinese letter',
    so they're left out (DeskMate asks her brain for kana-only Japanese, so this is just a safety net)."""
    text = re.sub(r"\s+", " ", re.sub(r"[~～*_`#<>]+", " ", text or "")).strip()
    if language == "ja" and KANJI.search(text):
        log.warning("Kanji in a Japanese line: left out (the built-in voice reads kana only)")
        text = KANJI.sub("", text)
    return text


def to_wav(samples, rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(rate)
        clip.writeframes(pcm)
    return out.getvalue()


class Engine:
    """Kokoro, loaded once (about a second), one line at a time."""

    def __init__(self, models: Path):
        from kokoro_onnx import Kokoro

        self.kokoro = Kokoro(str(models / MODEL_FILES[0]), str(models / MODEL_FILES[1]))
        self.voices = sorted(self.kokoro.get_voices())
        self.lock = threading.Lock()

    def speak(self, text: str, voice: str, speed: float = 1.0, lang_code: str | None = None) -> bytes:
        if voice not in self.voices and "+" not in voice:
            raise ValueError(f"unknown voice {voice!r}")
        language = reading_language(voice, lang_code)
        text = prepare(text, language)
        if not text:
            raise ValueError("nothing to say")
        style = voice
        if "+" in voice:  # "af_bella+af_sky": the average of the two voices
            parts = [p.strip() for p in voice.split("+")]
            style = sum(self.kokoro.get_voice_style(p) for p in parts) / len(parts)
        with self.lock:
            samples, rate = self.kokoro.create(text, voice=style, speed=max(0.5, min(2.0, speed)), lang=language)
        return to_wav(samples, rate)


def make_handler(engine: Engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug(fmt, *args)

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.rstrip("/").endswith("/models"):
                self._json(200, {"data": [{"id": "kokoro"}]})
            elif self.path.rstrip("/").endswith("/audio/voices"):
                self._json(200, {"voices": [{"id": v} for v in engine.voices]})
            else:
                self._json(404, {"error": {"message": "not found"}})

        def do_POST(self):
            if not self.path.rstrip("/").endswith("/audio/speech"):
                self._json(404, {"error": {"message": "not found"}})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(min(length, 100_000)) or b"{}")
                wav = engine.speak(str(request.get("input", ""))[:2000], str(request.get("voice", "af_heart")),
                                   float(request.get("speed", 1.0)), request.get("lang_code"))
            except (ValueError, TypeError) as error:
                self._json(400, {"error": {"message": str(error)}})
                return
            except Exception as error:  # never take the server down for one bad line
                log.exception("Couldn't make that line")
                self._json(500, {"error": {"message": str(error)}})
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.end_headers()
            self.wfile.write(wav)

    return Handler


def parent_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeskMate voice pack (Kokoro)")
    parser.add_argument("--models", type=Path, default=Path(sys.argv[0]).resolve().parent / "models")
    parser.add_argument("--port", type=int, default=8881)
    parser.add_argument("--parent", type=int, default=0, help="quit when this process (DeskMate) is gone")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = Engine(args.models)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(engine))
    log.info("DeskMate voice pack ready on http://127.0.0.1:%d/v1 (%d voices)", args.port, len(engine.voices))

    def watch_parent() -> None:
        while parent_alive(args.parent):
            time.sleep(2)
        log.info("DeskMate is gone: stopping")
        server.shutdown()

    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0
