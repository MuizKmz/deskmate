"""The built-in voice pack: download it once, then DeskMate starts and stops it by itself.

The pack is a separate little program (``deskmate_voice``, built by GitHub Actions into
DeskMate-Voice-win64.zip with the Kokoro voice model inside). DeskMate never loads it into its
own process: it starts ``DeskMate-Voice.exe`` on a free port on 127.0.0.1 the first time she
needs a natural voice, talks to it like any OpenAI-style voice server, and stops it when she
quits. The pack also stops itself if DeskMate disappears (``--parent``).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .updates import REPO

log = logging.getLogger(__name__)

PACK_TAG = "voicepack-v1"
PACK_URL = f"https://github.com/{REPO}/releases/download/{PACK_TAG}/DeskMate-Voice-win64.zip"
PACK_MB = 130  # roughly, for the "Download (~130 MB)" button (the real zip is 128 MB)
EXE = "DeskMate-Voice.exe"
MODEL_FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
START_TIMEOUT = 60.0  # the first start loads the model (a few seconds; slower PCs, a bit more)
ROOT = Path(__file__).resolve().parents[1]  # (running from source: where deskmate_voice is)
# Windows refusing to start a program: Smart App Control / a company's app policy (4551, 1260), antivirus (225).
BLOCKED = {4551, 1260, 225}
BLOCKED_TEXT = ("Windows blocked the voice pack (Smart App Control or your company's app policy), because it "
                "isn't code-signed yet. If you run DeskMate from source, it can use Python instead: run "
                "'.venv\\Scripts\\pip install kokoro-onnx' in the DeskMate folder, then restart DeskMate.")


class VoicePackError(Exception):
    """Why the voice pack can't speak: ``kind`` is "missing" (not downloaded) or "failed"."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail or kind)
        self.kind = kind


def models_ready(folder: Path) -> bool:
    return all((folder / "models" / name).is_file() for name in MODEL_FILES)


def source_engine_available() -> bool:
    """Running DeskMate from source with kokoro-onnx installed: the pack can run from source too."""
    if getattr(sys, "frozen", False):
        return False
    try:
        import importlib.util

        return (importlib.util.find_spec("kokoro_onnx") is not None
                and importlib.util.find_spec("deskmate_voice") is not None)
    except (ImportError, ValueError):
        return False


def installed(folder: Path) -> bool:
    return models_ready(folder) and ((folder / EXE).is_file() or source_engine_available())


def command(folder: Path, port: int, parent: int) -> list[str] | None:
    """How to start the pack, or None if it isn't here. Running DeskMate from source with kokoro-onnx
    installed, the same (trusted, signed) Python runs it; otherwise the pack's own .exe."""
    args = ["--models", str(folder / "models"), "--port", str(port), "--parent", str(parent)]
    if not models_ready(folder):
        return None
    if source_engine_available():
        start = f"import sys; sys.path.insert(0, {str(ROOT)!r}); from deskmate_voice.server import main; main()"
        return [sys.executable, "-c", start, *args]
    if (folder / EXE).is_file():
        return [str(folder / EXE), *args]
    return None


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def download(folder: Path, progress: Callable[[int, int], None] | None = None,
             stop: Callable[[], bool] | None = None, url: str = PACK_URL, opener=None) -> None:
    """(Background thread.) Download the pack and unpack it into ``folder`` (replacing an old one)."""
    folder.parent.mkdir(parents=True, exist_ok=True)
    part = folder.parent / "voicepack.zip.part"
    request = urllib.request.Request(url, headers={"User-Agent": "DeskMate"})
    try:
        response = (opener or urllib.request.urlopen)(request, timeout=60)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise VoicePackError("unavailable", "The voice pack isn't on GitHub yet. Try again later, or use "
                                                "Windows voice for now.") from None
        raise VoicePackError("failed", f"GitHub said no ({error.code}). Try again later.") from None
    with response, open(part, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if stop is not None and stop():
                raise VoicePackError("failed", "Download cancelled.")
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)
    if total and done != total:
        raise VoicePackError("failed", "The download was cut off. Try again.")
    unpacked = folder.parent / "voicepack.new"
    shutil.rmtree(unpacked, ignore_errors=True)
    try:
        with zipfile.ZipFile(part) as pack:
            for name in pack.namelist():  # a zip must never write outside its folder
                target = (unpacked / name).resolve()
                if not str(target).startswith(str(unpacked.resolve())):
                    raise VoicePackError("failed", "The voice pack looks broken.")
            pack.extractall(unpacked)
    except zipfile.BadZipFile:
        raise VoicePackError("failed", "The voice pack looks broken. Try again.") from None
    inner = next((p.parent for p in unpacked.rglob(EXE)), None) or unpacked  # the zip may have a top folder
    if not models_ready(inner):
        raise VoicePackError("failed", "The voice pack is missing its voice model.")
    shutil.rmtree(folder, ignore_errors=True)
    shutil.move(str(inner), str(folder))
    shutil.rmtree(unpacked, ignore_errors=True)
    part.unlink(missing_ok=True)
    log.info("Voice pack installed in %s", folder)


class VoicePack:
    """Starts the pack when she first needs it (on a background thread), and stops it at the end."""

    def __init__(self, folder: Path, popen=subprocess.Popen, make_command=command, parent: int | None = None):
        self.folder = folder
        self._popen = popen
        self._command = make_command
        self._parent = parent if parent is not None else os.getpid()
        self._process = None
        self._port = 0
        self._lock = threading.Lock()

    @property
    def installed(self) -> bool:
        return installed(self.folder)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def ensure_running(self, timeout: float = START_TIMEOUT) -> str:
        """(Background thread.) The pack's address, starting it first if needed."""
        with self._lock:
            if self.running and self._answers(self._port):
                return self._url(self._port)
            self.stop()
            port = free_port()
            args = self._command(self.folder, port, self._parent)
            if args is None:
                raise VoicePackError("missing", "The voice pack isn't downloaded yet (Voice settings).")
            log.info("Starting the voice pack on port %d", port)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            log_file = open(self.folder / "voicepack.log", "ab") if self.folder.is_dir() else subprocess.DEVNULL
            try:
                self._process = self._popen(args, stdout=log_file, stderr=log_file, stdin=subprocess.DEVNULL,
                                            creationflags=flags)
            except OSError as error:
                if getattr(error, "winerror", None) in BLOCKED:
                    raise VoicePackError("blocked", BLOCKED_TEXT) from None
                raise VoicePackError("failed", f"The voice pack didn't start: {error}") from None
            finally:
                if log_file is not subprocess.DEVNULL:
                    log_file.close()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise VoicePackError("failed", "The voice pack stopped right away (see voicepack.log).")
                if self._answers(port):
                    self._port = port
                    return self._url(port)
                time.sleep(0.25)
            self.stop()
            raise VoicePackError("failed", "The voice pack took too long to start.")

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    @staticmethod
    def _url(port: int) -> str:
        return f"http://127.0.0.1:{port}/v1"

    @staticmethod
    def _answers(port: int) -> bool:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
            with opener.open(f"http://127.0.0.1:{port}/v1/models", timeout=1.5) as response:
                return "data" in json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError):
            return False
