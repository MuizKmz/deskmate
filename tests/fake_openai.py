"""A tiny pretend OpenAI server on localhost, so chat can be tested without a real key."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOpenAI:
    MODELS = ["gpt-4o-mini-transcribe", "gpt-5-mini", "gpt-5.4-mini", "gpt-6.1-sol", "text-embedding-3-small"]

    def __init__(self, key: str = "sk-test-1234567890"):
        self.key = key
        self.reply = "[happy] Ehehe, hi there~"
        self.status = 200  # set to 401 / 429 / 500 to pretend something failed
        self.requests: list[dict] = []
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
                if self.headers.get("Authorization") != f"Bearer {fake.key}":
                    self._send(401, {"error": {"message": "Incorrect API key provided"}})
                    return False
                if fake.status != 200:
                    self._send(fake.status, {"error": {"message": "pretend failure"}})
                    return False
                return True

            def do_GET(self):
                if self._check():
                    self._send(200, {"data": [{"id": m} for m in fake.MODELS]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                if self._check():
                    self._send(200, {"choices": [{"message": {"role": "assistant", "content": fake.reply}}]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
