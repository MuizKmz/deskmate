"""A tiny pretend OpenAI server on localhost, so chat can be tested without a real key."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _tone(seconds: float = 0.2, rate: int = 24000) -> bytes:
    """A little 440 Hz beep as a 16-bit mono WAV."""
    import math
    import struct

    samples = b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate)))
                       for i in range(int(seconds * rate)))
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(samples), b"WAVE", b"fmt ", 16, 1, 1, rate,
                       rate * 2, 2, 16, b"data", len(samples)) + samples


class FakeOpenAI:
    MODELS = ["gpt-4o-mini-transcribe", "gpt-4o-mini-tts", "gpt-5-mini", "gpt-5.4-mini", "gpt-6.1-sol",
              "text-embedding-3-small", "tts-1", "tts-1-hd", "claude-haiku-5-5", "claude-sonnet-5-5"]
    WAV = _tone()  # a real (short, quiet) WAV clip, so the voice code can check and play it

    def __init__(self, key: str = "sk-test-1234567890"):
        self.key = key
        self.reply = "[happy] Ehehe, hi there~"
        self.status = 200  # set to 401 / 429 / 500 to pretend something failed
        self.error = "pretend failure"  # the message that comes with it
        self.require_key = True  # False: like a server on your own PC (Kokoro), no key needed
        self.voices = [{"id": "af_bella"}, {"id": "jf_alpha"}, {"id": "af_heart"}]
        self.requests: list[dict] = []
        self.headers: list[dict] = []  # headers of each POST (to check how the key was sent)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _check(self):
                bearer = self.headers.get("Authorization") == f"Bearer {fake.key}"
                anthropic = self.headers.get("x-api-key") == fake.key and self.headers.get("anthropic-version")
                if fake.require_key and not (bearer or anthropic):
                    self._send(401, {"error": {"message": "Incorrect API key provided"}})
                    return False
                if fake.status != 200:
                    self._send(fake.status, {"error": {"message": fake.error}})
                    return False
                return True

            def do_GET(self):
                if not self._check():
                    return
                if self.path.endswith("/audio/voices"):  # like Kokoro-FastAPI
                    self._send(200, {"voices": fake.voices})
                else:
                    self._send(200, {"data": [{"id": m} for m in fake.MODELS]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                fake.headers.append({k.lower(): v for k, v in self.headers.items()})  # names ignore case
                if not self._check():
                    return
                if self.path.endswith("/messages"):  # pretend to be Claude (Anthropic's Messages API)
                    self._send(200, {"type": "message", "role": "assistant",
                                     "content": [{"type": "text", "text": fake.reply}]})
                    return
                if self.path.endswith("/audio/speech"):  # her voice: raw WAV bytes, not JSON
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(len(fake.WAV)))
                    self.end_headers()
                    self.wfile.write(fake.WAV)
                    return
                self._send(200, {"choices": [{"message": {"role": "assistant", "content": fake.reply}}]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
