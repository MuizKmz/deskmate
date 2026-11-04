"""DeskMate's voice pack: Kokoro voices on your own PC, as a small separate program.

It's kept apart from DeskMate itself (its own download, its own process) because the engine is
big (~170 MB with the voice model) and part of it (phonemizer, espeak-ng) is GPL-licensed.
DeskMate talks to it over HTTP on 127.0.0.1 with the same protocol as OpenAI's /audio/speech
(and Kokoro-FastAPI), so to DeskMate it's just "a voice server on this PC".

    python -m deskmate_voice --models <folder with kokoro-v1.0.int8.onnx + voices-v1.0.bin> --port 8881
"""

__version__ = "1"
