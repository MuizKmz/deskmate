"""The built-in voice pack: downloading it, starting/stopping it, and its little server."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path

from deskmate import voicepack
from deskmate.voicepack import EXE, MODEL_FILES, VoicePack, VoicePackError, download
from deskmate_voice import server


class _Response(io.BytesIO):
    def __init__(self, data: bytes, length: int | None = None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}

    def __exit__(self, *args):
        self.close()


def make_zip(entries: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as pack:
        for name, data in entries.items():
            pack.writestr(name, data)
    return out.getvalue()


GOOD = {EXE: b"MZ pretend exe", "NOTICE.txt": b"licenses", **{f"models/{m}": b"model" for m in MODEL_FILES}}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.folder = self.home / "voicepack"
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, ignore_errors=True))

    def get(self, data: bytes, length: int | None = None, **kwargs):
        seen = []
        download(self.folder, progress=lambda done, total: seen.append((done, total)),
                 opener=lambda request, timeout: _Response(data, length), **kwargs)
        return seen

    def test_downloads_and_unpacks(self):
        data = make_zip(GOOD)
        seen = self.get(data)
        self.assertEqual(seen[-1], (len(data), len(data)))
        self.assertTrue((self.folder / EXE).is_file())
        self.assertTrue(voicepack.installed(self.folder))
        self.assertFalse((self.home / "voicepack.zip.part").exists())  # cleaned up
        self.assertFalse((self.home / "voicepack.new").exists())

    def test_a_top_folder_in_the_zip_is_fine_and_a_new_pack_replaces_the_old(self):
        self.get(make_zip(GOOD))
        (self.folder / "old.txt").write_text("from the old pack")
        self.get(make_zip({f"DeskMate-Voice/{name}": data for name, data in GOOD.items()}))
        self.assertTrue((self.folder / EXE).is_file())
        self.assertFalse((self.folder / "old.txt").exists())

    def test_broken_downloads_are_refused(self):
        with self.assertRaises(VoicePackError):
            self.get(make_zip(GOOD), length=10 ** 9)  # cut off
        with self.assertRaises(VoicePackError):
            self.get(b"this is not a zip")
        with self.assertRaises(VoicePackError):
            self.get(make_zip({EXE: b"exe"}))  # no voice model
        with self.assertRaises(VoicePackError):
            self.get(make_zip({**GOOD, "../escape.txt": b"!"}))  # never write outside the folder
        self.assertFalse((self.home / "escape.txt").exists())
        self.assertFalse(voicepack.installed(self.folder))

    def test_not_published_yet(self):
        import urllib.error

        def missing(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

        with self.assertRaises(VoicePackError) as caught:
            download(self.folder, opener=missing)
        self.assertEqual(caught.exception.kind, "unavailable")
        self.assertIn("isn't on GitHub yet", str(caught.exception))

    def test_cancel(self):
        with self.assertRaises(VoicePackError) as caught:
            self.get(make_zip(GOOD), stop=lambda: True)
        self.assertIn("cancelled", str(caught.exception))


# A pretend pack: answers /v1/models on the port it's given, like DeskMate-Voice.exe.
PRETEND = """
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port = int(sys.argv[sys.argv.index("--port") + 1])
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = json.dumps({"data": [{"id": "kokoro"}]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


class VoicePackTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))

    def test_starts_once_and_stops(self):
        commands = []

        def make_command(folder, port, parent):
            commands.append((port, parent))
            return [sys.executable, "-c", PRETEND, "--port", str(port), "--parent", str(parent)]

        pack = VoicePack(self.folder, make_command=make_command, parent=1234)
        self.addCleanup(pack.stop)
        url = pack.ensure_running(timeout=20)
        self.assertTrue(url.startswith("http://127.0.0.1:") and url.endswith("/v1"))
        self.assertTrue(pack.running)
        self.assertEqual(pack.ensure_running(), url)  # already running: no second copy
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][1], 1234)  # it's told who to watch
        pack.stop()
        self.assertFalse(pack.running)

    def test_not_downloaded_or_broken(self):
        missing = VoicePack(self.folder, make_command=lambda *a: None)
        with self.assertRaises(VoicePackError) as caught:
            missing.ensure_running()
        self.assertEqual(caught.exception.kind, "missing")
        self.assertIsNone(voicepack.command(self.folder, 1, 1))  # nothing downloaded here

        crashes = VoicePack(self.folder, make_command=lambda *a: [sys.executable, "-c", "raise SystemExit(3)"])
        with self.assertRaises(VoicePackError) as caught:
            crashes.ensure_running(timeout=20)
        self.assertEqual(caught.exception.kind, "failed")

    def test_command_prefers_the_exe(self):
        for name in MODEL_FILES:
            (self.folder / "models").mkdir(exist_ok=True)
            (self.folder / "models" / name).write_bytes(b"model")
        (self.folder / EXE).write_bytes(b"exe")
        args = voicepack.command(self.folder, 4321, 99)
        self.assertEqual(args[0], str(self.folder / EXE))
        self.assertEqual(args[args.index("--port") + 1], "4321")
        self.assertEqual(args[args.index("--parent") + 1], "99")


class _FakeEngine:
    voices = ["af_heart", "jf_alpha"]

    def __init__(self):
        self.said = []

    def speak(self, text, voice, speed=1.0, lang_code=None):
        if voice not in self.voices:
            raise ValueError(f"unknown voice {voice!r}")
        self.said.append((text, voice, server.reading_language(voice, lang_code)))
        return b"RIFF....WAVE"


class ServerTests(unittest.TestCase):
    def test_reading_language_and_kana_only_japanese(self):
        self.assertEqual(server.reading_language("jf_alpha"), "ja")
        self.assertEqual(server.reading_language("af_heart"), "en-us")
        self.assertEqual(server.reading_language("bf_emma"), "en-gb")
        self.assertEqual(server.reading_language("af_heart", "j"), "ja")  # asked for
        self.assertEqual(server.reading_language("zf_xiaobei+af_sky"), "cmn")
        self.assertEqual(server.prepare("元気？こんにちは～", "ja"), "？こんにちは")  # kanji would be "Chinese letter"
        self.assertEqual(server.prepare("Hi~ *waves*", "en-us"), "Hi waves")
        self.assertEqual(server.prepare("漢字 ok", "cmn"), "漢字 ok")  # Chinese voices read them fine

    def test_speaks_like_an_openai_voice_server(self):
        from http.server import ThreadingHTTPServer

        engine = _FakeEngine()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(engine))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        base = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path):
            with opener.open(base + path, timeout=5) as response:
                return json.loads(response.read())

        def post(payload):
            request = urllib.request.Request(base + "/audio/speech", json.dumps(payload).encode(),
                                             {"Content-Type": "application/json"})
            with opener.open(request, timeout=5) as response:
                return response.headers["Content-Type"], response.read()

        self.assertEqual(get("/models"), {"data": [{"id": "kokoro"}]})
        self.assertEqual(get("/audio/voices"), {"voices": [{"id": "af_heart"}, {"id": "jf_alpha"}]})
        self.assertEqual(post({"model": "kokoro", "voice": "jf_alpha", "input": "こんにちは"}),
                         ("audio/wav", b"RIFF....WAVE"))
        self.assertEqual(engine.said, [("こんにちは", "jf_alpha", "ja")])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            post({"voice": "nobody", "input": "hi"})
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("unknown voice", json.loads(caught.exception.read())["error"]["message"])

    def test_parent_check(self):
        self.assertTrue(server.parent_alive(os.getpid()))
        self.assertTrue(server.parent_alive(0))  # no parent given: keep running


MODELS = os.environ.get("DESKMATE_VOICE_MODELS", "")


@unittest.skipUnless(MODELS and voicepack.source_engine_available(),
                     "set DESKMATE_VOICE_MODELS to a folder with the Kokoro model files (and pip install kokoro-onnx)")
class RealVoiceTests(unittest.TestCase):
    def test_real_pack_speaks_english_and_japanese(self):
        from deskmate.voice import PackVoice

        home = Path(tempfile.mkdtemp())
        (home / "models").symlink_to(Path(MODELS).resolve(), target_is_directory=True)
        pack = VoicePack(home)
        self.addCleanup(pack.stop)
        started = time.monotonic()
        for voice, line in (("af_heart", "Hi, it's me!"), ("jf_alpha", "こんにちは！")):
            wav = PackVoice(pack, voice=voice).synthesize(line)
            self.assertEqual(wav[:4], b"RIFF")
            self.assertGreater(len(wav), 20000)
        self.assertLess(time.monotonic() - started, 60)


if __name__ == "__main__":
    unittest.main()
