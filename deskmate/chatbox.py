"""The chat window (a little text box next to her) and the Chat settings dialog."""

from __future__ import annotations

import html
import re
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from .chat import KEY_NAMES, MODEL_SETTINGS, OLLAMA_URL, ChatConfig, ChatError, list_models, mask, pick_model
from .menu_style import GLASS_BOTTOM, GLASS_TOP, INK, accent_of
from .menu_style import icon as _icon


class Background(QObject):
    """Run a slow function on a thread and get the result back on the Qt (main) thread."""

    _done = Signal(object, object)  # (callback, (ok, value))

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._done.connect(lambda callback, result: callback(*result))
        self.busy = 0

    def run(self, work: Callable[[], Any], callback: Callable[[bool, Any], None]) -> None:
        self.busy += 1

        def target() -> None:
            try:
                result = (True, work())
            except Exception as error:  # handed to the callback, which decides what to show
                result = (False, error)
            self._done.emit(self._finish(callback), result)

        threading.Thread(target=target, name="deskmate-chat", daemon=True).start()

    def _finish(self, callback):
        def wrapped(ok, value):
            self.busy -= 1
            callback(ok, value)
        return wrapped


class ChatBox(QWidget):
    """A small rounded text box that pops up beside her. Enter sends, Esc closes."""

    sent = Signal(str)
    history_requested = Signal()
    look_requested = Signal()

    def __init__(self, name: str, theme: dict[str, str]):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(f"Chat with {name}")
        self._name = name
        self._looking = False
        self._accent = QColor(theme.get("accent", "#C9A0DC"))
        self._ink = QColor(theme.get("text", "#3B2F4A"))
        self._fill = QColor(theme.get("bubble", "#FFFFFF"))

        self.edit = QLineEdit(self)
        self.edit.setFrame(False)
        self.edit.setMaxLength(1000)
        self.edit.setPlaceholderText(f"Say something to {name}...")
        self.edit.setStyleSheet(f"QLineEdit {{ background: transparent; color: {self._ink.name()}; }}")
        self.edit.returnPressed.connect(self._send)
        self.send_button = QToolButton(self)
        self.send_button.setText("➤")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setAutoRaise(True)
        self.send_button.setStyleSheet(f"QToolButton {{ color: {self._accent.darker(130).name()}; font-size: 15px; }}")
        self.send_button.clicked.connect(self._send)
        self.history_button = QToolButton(self)
        self.history_button.setIcon(_icon("clock", self._accent.darker(130)))
        self.history_button.setToolTip("Today's chat")
        self.history_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_button.setAutoRaise(True)
        self.history_button.clicked.connect(self.history_requested)
        self.look_button = QToolButton(self)
        self.look_button.setIcon(_icon("eye", self._accent.darker(130)))
        self.look_button.setToolTip(f"Let {name} watch your screen with you")
        self.look_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.look_button.setAutoRaise(True)
        self.look_button.clicked.connect(self.look_requested)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(2)
        layout.addWidget(self.history_button)
        layout.addWidget(self.look_button)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.send_button)
        self.resize(320, 46)
        self._waiting = False

    def set_looking(self, looking: bool) -> None:
        """While she watches your screen, an empty message means 'have a look at this'."""
        self._looking = looking
        self.edit.setPlaceholderText("Ask about your screen... (or just Enter)" if looking
                                     else f"Say something to {self._name}...")
        self.look_button.setToolTip("Stop watching my screen" if looking
                                    else f"Let {self._name} watch your screen with you")

    def set_waiting(self, waiting: bool) -> None:
        """While she's thinking, you can type but not send (one question at a time)."""
        self._waiting = waiting
        self.send_button.setEnabled(not waiting)
        self.send_button.setText("…" if waiting else "➤")

    def _send(self) -> None:
        text = self.edit.text().strip()
        if (text or self._looking) and not self._waiting:
            self.edit.clear()
            self.sent.emit(text)

    def open_near(self, body: QRect, available: QRect) -> None:
        """Show it under her head, beside her body, always fully on screen."""
        x = body.left() - self.width() - 6
        if x < available.left():
            x = body.right() + 6
        if x + self.width() > available.right():
            x = body.center().x() - self.width() // 2
        y = body.top() + int(body.height() * 0.45)
        x = max(available.left(), min(x, available.right() - self.width()))
        y = max(available.top(), min(y, available.bottom() - self.height()))
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.fillPath(path, self._fill)
        painter.setPen(QPen(self._accent, 2.0))
        painter.drawPath(path)


class ChatSettingsDialog(QDialog):
    """Choose OpenAI, Claude or Ollama, paste the key, pick a model, and test it."""

    KEY_LABELS = {"openai": ("OpenAI API key", "sk-..."), "claude": ("Anthropic API key", "sk-ant-...")}

    def __init__(self, settings, keys, name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Chat with {name}: settings")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(460)
        self._settings = settings
        self._keys = {"openai": keys} if isinstance(keys, str) else dict(keys)  # saved keys, by key name
        self._worker = Background(self)

        self.provider = QComboBox()
        self.provider.addItem("OpenAI (needs an API key)", "openai")
        self.provider.addItem("Claude (needs an Anthropic API key)", "claude")
        self.provider.addItem("Ollama (free, runs on this PC)", "ollama")
        self.provider.setCurrentIndex(max(0, self.provider.findData(settings["chat_provider"])))

        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.url = QLineEdit(settings["ollama_url"] or OLLAMA_URL)

        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.lineEdit().setPlaceholderText("empty = pick a cheap one automatically")
        self.pick = QPushButton("Pick for me")
        self.pick.clicked.connect(self._pick)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.pick)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.test = QPushButton("Test connection")
        self.test.clicked.connect(self._test)

        self.form = QFormLayout()
        self.form.addRow("Chat brain", self.provider)
        self.form.addRow("OpenAI API key", self.key)
        self.form.addRow("Ollama address", self.url)
        self.form.addRow("Model", model_row)
        note = QLabel("Keys are saved only on this PC (in your DeskMate settings folder), never in the project "
                      "folder. Tip: set a monthly spending limit in your OpenAI / Anthropic account.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(note)
        test_row = QHBoxLayout()
        test_row.addWidget(self.test)
        test_row.addWidget(self.status, 1)
        layout.addLayout(test_row)
        layout.addWidget(buttons)

        self.provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed()

    # ------------------------------------------------------------------ values
    @property
    def chosen_provider(self) -> str:
        return self.provider.currentData()

    @property
    def saved_key(self) -> str:
        return self._keys.get(KEY_NAMES.get(self.chosen_provider, ""), "")

    @property
    def chosen_key(self) -> str:
        return self.key.text().strip() or self.saved_key

    @property
    def chosen_model(self) -> str:
        return self.model.currentText().strip()

    def config(self) -> ChatConfig:
        ollama = self.chosen_provider == "ollama"
        return ChatConfig(provider=self.chosen_provider, model=self.chosen_model,
                          api_key="" if ollama else self.chosen_key,
                          base_url=self.url.text().strip() if ollama else "")

    def _provider_changed(self) -> None:
        provider = self.chosen_provider
        ollama = provider == "ollama"
        self.form.setRowVisible(self.key, not ollama)
        self.form.setRowVisible(self.url, ollama)
        if not ollama:
            label, example = self.KEY_LABELS[provider]
            self.form.labelForField(self.key).setText(label)
            self.key.clear()  # a typed key belongs to the brain it was typed for
            saved = self.saved_key
            self.key.setPlaceholderText(f"saved: {mask(saved)}  (leave empty to keep it)" if saved
                                        else f"{example}  (paste your key here)")
        self.model.clear()
        current = self._settings[MODEL_SETTINGS[provider]]
        if current:
            self.model.addItem(current)
        self.model.setEditText(current)
        hints = {"ollama": "Install Ollama from ollama.com, then run:  ollama pull llama3.2",
                 "claude": "Get a key at console.anthropic.com (API keys)."}
        self.status.setText(hints.get(provider, ""))

    # ------------------------------------------------------------------ network
    def _busy(self, text: str) -> None:
        self.status.setText(text)
        self.test.setEnabled(False)
        self.pick.setEnabled(False)

    def _idle(self) -> None:
        self.test.setEnabled(True)
        self.pick.setEnabled(True)

    def _models(self, then: Callable[[list[str]], None]) -> None:
        config = self.config()
        self._busy("Connecting...")

        def done(ok: bool, value) -> None:
            self._idle()
            if not ok:
                self.status.setText(describe_error(value))
                return
            then(value)

        self._worker.run(lambda: list_models(config), done)

    def _pick(self) -> None:
        def chosen(models: list[str]) -> None:
            best = pick_model(models, self.chosen_provider)
            self.model.clear()
            for name in sorted(models, key=lambda m: (m != best, m)):
                self.model.addItem(name)
            self.model.setEditText(best)
            self.status.setText(f"Picked {best}. You can choose another from the list." if best
                                else "No chat models found on this account.")
        self._models(chosen)

    def _test(self) -> None:
        def tested(models: list[str]) -> None:
            wanted = self.chosen_model
            if wanted and wanted not in models:
                self.status.setText(f"Connected, but '{wanted}' isn't available. Try Pick for me.")
            else:
                self.status.setText(f"✓ Connected! {len(models)} models available.")
        self._models(tested)


class VoiceSettingsDialog(QDialog):
    """Which voice she speaks with: any Windows voice, and the Natural voice from OpenAI or your own server."""

    SAMPLE = "Hi, it's me~ How do I sound?"

    def __init__(self, settings, openai_key: str, name: str, parent=None, list_windows=None, make_windows=None,
                 play=None):
        from .voice import OWN_SERVER_URL, WindowsVoice, list_windows_voices, play_wav

        super().__init__(parent)
        self.setWindowTitle(f"{name}'s voice")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(480)
        self._settings = settings
        self._openai_key = openai_key
        self._worker = Background(self)
        self._list_windows = list_windows or list_windows_voices
        self._windows = (make_windows or WindowsVoice)()
        self._play = play or play_wav
        self._cultures = {settings["windows_voice"]: settings["windows_voice_lang"]} if settings["windows_voice"] else {}

        # --- Windows voice
        self.windows_voice = QComboBox()
        self.windows_voice.addItem("Automatic (the first female voice)", "")
        saved = settings["windows_voice"]
        if saved:
            self.windows_voice.addItem(saved, saved)
            self.windows_voice.setCurrentIndex(1)
        self.test_windows = QPushButton("Test")
        self.test_windows.clicked.connect(self._test_windows)
        windows_row = QHBoxLayout()
        windows_row.addWidget(self.windows_voice, 1)
        windows_row.addWidget(self.test_windows)

        # --- Natural voice
        self.source = QComboBox()
        self.source.addItem("OpenAI (uses your OpenAI key)", "openai")
        self.source.addItem("My own server, e.g. Kokoro (free, on this PC)", "local")
        self.source.setCurrentIndex(max(0, self.source.findData(settings["tts_source"])))
        self.url = QLineEdit(settings["tts_url"] or OWN_SERVER_URL)
        self.voice = QComboBox()
        self.voice.setEditable(True)
        self.voice.currentTextChanged.connect(self._voice_changed)
        self.language = QLabel("")
        self.language.setWordWrap(True)
        self.language.setStyleSheet("color: gray;")
        self.load = QPushButton("Load voices")
        self.load.clicked.connect(self._load_voices)
        self.test_natural = QPushButton("Test")
        self.test_natural.clicked.connect(self._test_natural)
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice, 1)
        voice_row.addWidget(self.load)
        voice_row.addWidget(self.test_natural)

        self.translate = QCheckBox("Say her lines in the voice's language (chat stays English)")
        self.translate.setChecked(settings["voice_translate"])
        self.translate.setToolTip("With a Japanese voice she says her lines in Japanese. Uses your chat brain to "
                                  "translate (each line only once).")
        self.translate.toggled.connect(lambda _on: self._voice_changed(self.chosen_voice))
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.form = QFormLayout()
        self.form.addRow(QLabel("<b>Windows voice</b> (free, offline)"))
        self.form.addRow("Voice", windows_row)
        self.form.addRow(QLabel("<b>Natural voice</b>"))
        self.form.addRow("From", self.source)
        self.form.addRow("Server address", self.url)
        self.form.addRow("Voice", voice_row)
        self.form.addRow("", self.language)
        self.form.addRow("", self.translate)
        note = QLabel("More Windows voices: a language's speech pack (Windows Settings › Time & language) adds some; "
                      "NaturalVoiceSAPIAdapter adds Windows' natural voices. Your own server: run Kokoro-FastAPI "
                      "(github.com/remsky/Kokoro-FastAPI) and keep the address above. Voices like af_bella or "
                      "jf_alpha (Japanese), even mixes like af_bella+af_sky.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(note)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        self.source.currentIndexChanged.connect(self._source_changed)
        self._source_changed(first=True)
        self._worker.run(self._list_windows, self._got_windows_voices)

    # ------------------------------------------------------------------ values
    @property
    def chosen_windows_voice(self) -> str:
        return self.windows_voice.currentData() if self.windows_voice.currentIndex() >= 0 else ""

    @property
    def chosen_windows_culture(self) -> str:
        return self._cultures.get(self.chosen_windows_voice, "")

    @property
    def chosen_source(self) -> str:
        return self.source.currentData()

    @property
    def chosen_voice(self) -> str:
        return self.voice.currentText().strip()

    @property
    def chosen_url(self) -> str:
        return self.url.text().strip().rstrip("/")

    def natural_config(self) -> ChatConfig:
        if self.chosen_source == "local":
            return ChatConfig(provider="local", base_url=self.chosen_url)
        return ChatConfig(provider="openai", api_key=self._openai_key)

    def _source_changed(self, *_args, first: bool = False) -> None:
        from .voice import OPENAI_VOICES, OWN_SERVER_VOICE

        own = self.chosen_source == "local"
        self.form.setRowVisible(self.url, own)
        current = self._settings["openai_voice"] if first else ""
        self.voice.clear()
        if own:
            if current in OPENAI_VOICES or not current:
                current = OWN_SERVER_VOICE
            self.voice.addItem(current)
        else:
            for name in OPENAI_VOICES:
                self.voice.addItem(name)
            if current not in OPENAI_VOICES:
                current = "nova"
        self.voice.setEditText(current)
        self.status.setText("" if own or self._openai_key else "No OpenAI key yet: add one in Chat settings.")

    # ------------------------------------------------------------------ Windows
    def _got_windows_voices(self, ok: bool, voices) -> None:
        from .voice import describe_windows_voice

        if not ok or not voices:
            return
        keep = self.chosen_windows_voice
        self.windows_voice.clear()
        self.windows_voice.addItem("Automatic (the first female voice)", "")
        for voice in voices:
            self.windows_voice.addItem(describe_windows_voice(voice), voice["name"])
            self._cultures[voice["name"]] = voice.get("culture", "")
        self.windows_voice.setCurrentIndex(max(0, self.windows_voice.findData(keep)))

    def _test_windows(self) -> None:
        self._windows.name = self.chosen_windows_voice
        try:
            self._windows.speak(self.SAMPLE)
            self.status.setText("")
        except OSError as error:
            self.status.setText(f"The Windows voice didn't start: {error}")

    # ------------------------------------------------------------------ natural
    def _busy(self, text: str) -> None:
        self.status.setText(text)
        self.load.setEnabled(False)
        self.test_natural.setEnabled(False)

    def _idle(self) -> None:
        self.load.setEnabled(True)
        self.test_natural.setEnabled(True)

    def _load_voices(self) -> None:
        from .voice import list_voices

        config = self.natural_config()
        self._busy("Connecting...")

        def done(ok: bool, value) -> None:
            self._idle()
            if not ok:
                self.status.setText(self._explain(value))
                return
            keep = self.chosen_voice
            self.voice.clear()
            for name in value:
                self.voice.addItem(name)
            self.voice.setEditText(keep if keep in value or not value else value[0])
            self.status.setText(f"✓ {len(value)} voices available." if value else "Connected, but no voices listed.")

        self._worker.run(lambda: list_voices(config), done)

    def _voice_changed(self, name: str) -> None:
        from .voice import voice_language

        language = voice_language(name) if self.chosen_source == "local" else ""
        if not language:
            self.language.setText("")
        elif "English" in language:
            self.language.setText(f"{language} voice")
        elif self.translate.isChecked():
            self.language.setText(f"{language} voice: she says her lines in {language}.")
        else:
            self.language.setText(f"{language} voice: reads her English lines the {language} way.")

    def _test_natural(self) -> None:
        from .voice import OpenAIVoice, sample_for

        natural = OpenAIVoice(self.natural_config(), voice=self.chosen_voice)
        sample = sample_for(natural.voice) if natural.own_server else self.SAMPLE
        self._busy("Asking for a sample...")

        def done(ok: bool, value) -> None:
            self._idle()
            if not ok:
                self.status.setText(self._explain(value))
                return
            self.status.setText(f"✓ Playing {natural.voice}: “{sample}”")
            try:
                self._play(value)
            except Exception as error:  # the sound card said no
                self.status.setText(f"Got the clip, but couldn't play it: {error}")

        self._worker.run(lambda: natural.synthesize(sample), done)

    def _explain(self, error) -> str:
        if isinstance(error, ValueError):
            return str(error)
        if isinstance(error, ChatError) and error.kind == "offline" and self.chosen_source == "local":
            return "Can't reach your server. Is Kokoro-FastAPI running, at this address?"
        return describe_error(error)


def describe_error(error: BaseException) -> str:
    if isinstance(error, ChatError):
        return {
            "no_key": "Paste your OpenAI API key first.",
            "auth": "That key was refused. Check it (and that it's not deleted) in your OpenAI / Anthropic account.",
            "quota": "Out of credit or rate-limited. Check billing in your OpenAI / Anthropic account.",
            "model": f"Model problem: {error.detail}",
            "vision": "This model can't see pictures. Pick one that can (for Ollama: llama3.2-vision or llava).",
            "offline": "Can't connect. Is the internet on? For Ollama: is it running?",
            "timeout": "No answer in time. Try again.",
        }.get(error.kind, f"Error: {error.detail or error.kind}")
    return f"Error: {error}"


def details_html(text: str) -> str:
    """Her longer help (steps, an example, a question) as simple rich text: code blocks get a box."""
    out = []
    for i, part in enumerate(re.split(r"```[\w+#.-]*[ \t]*\n?", text or "")):
        if i % 2:  # inside ``` ... ```
            code = "<br>".join(_keep_indent(html.escape(line)) for line in part.strip("\n").split("\n"))
            out.append('<table width="100%" cellpadding="7" cellspacing="0" bgcolor="#EEE6F7" '
                       'style="margin-top: 4px; margin-bottom: 4px;"><tr><td>'
                       f'<span style="font-family: Consolas, \'Cascadia Mono\', monospace; font-size: 9pt; '
                       f'color: #2E2340;">{code}</span></td></tr></table>')
        elif part.strip():
            escaped = html.escape(part.strip("\n"))
            escaped = re.sub(r"`([^`\n]{1,80})`", r'<span style="font-family: Consolas, monospace; '
                             r'background-color: #EEE6F7;">&nbsp;\1&nbsp;</span>', escaped)
            out.append(escaped.replace("\n", "<br>"))
    return "".join(out)


def _keep_indent(line: str) -> str:
    stripped = line.lstrip(" ")
    return "&nbsp;" * (len(line) - len(stripped)) + stripped


def _css(color: QColor, alpha: float | None = None) -> str:
    a = color.alphaF() if alpha is None else alpha
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {a:.2f})"


class ChatLogWindow(QWidget):
    """Today's chat, as bubbles you can scroll back through, with its own input box.

    A small glass window in the character's colours (like her menu). Drag it by the top bar.
    """

    sent = Signal(str)
    look_requested = Signal()
    look_stopped = Signal()
    W, H = 390, 540

    def __init__(self, name: str, theme: dict[str, str], avatar: QPixmap, smooth: bool = True):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(f"Chat with {name}")
        self.resize(self.W, self.H)
        self._accent = accent_of(theme)
        self._name = name
        self._drag_from: QPoint | None = None
        self._waiting = False
        self._lines: list[dict] = []
        self._pending: list[dict] = []  # sent, not answered yet (shown right away)
        self._notes: list[dict] = []    # her "can't connect" lines: shown, not saved
        self._watching = False  # she's watching your screen with you (buddy mode)

        # --- top bar: face, name, close
        from .menu_style import Header  # same round face as in her menu

        top = QWidget(self)
        bar = QHBoxLayout(top)
        bar.setContentsMargins(14, 12, 10, 6)
        face = QLabel()
        face.setFixedSize(40, 40)
        Header.set_avatar(_AvatarHolder(face, smooth), avatar, self._accent)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel(name)
        self.title.setStyleSheet(f"color: {INK.name()}; font-size: 11.5pt; font-weight: 600;")
        self.subtitle = QLabel("Today")
        self.subtitle.setStyleSheet(f"color: {_css(INK, 0.6)}; font-size: 8.5pt;")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Close (Esc)")
        close.setStyleSheet(f"QToolButton {{ color: {_css(INK, 0.7)}; font-size: 12pt; border: none; padding: 4px 8px;"
                            f" border-radius: 8px; }} QToolButton:hover {{ background: {_css(self._accent, 0.3)}; }}")
        close.clicked.connect(self.hide)
        bar.addWidget(face)
        bar.addLayout(titles, 1)
        bar.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self._top = top

        # --- the bubbles
        self.area = QScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area.setStyleSheet(f"""
            QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
            QScrollBar::handle:vertical {{ background: {_css(self._accent, 0.45)}; border-radius: 3px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}""")
        self.inner = QWidget()
        self.column = QVBoxLayout(self.inner)
        self.column.setContentsMargins(12, 6, 12, 6)
        self.column.setSpacing(6)
        self.area.setWidget(self.inner)

        # --- "she's watching with you" bar
        self.look_bar = QWidget(self)
        look_row = QHBoxLayout(self.look_bar)
        look_row.setContentsMargins(14, 6, 12, 0)
        self.look_label = QLabel(f"👀 {name} is watching with you")
        self.look_label.setStyleSheet(f"color: {_css(INK, 0.75)}; font-size: 8.5pt;")
        self.look_label.setToolTip("While she watches, your messages include what's on your screen right now.")
        self.stop_button = QToolButton()
        self.stop_button.setText("Stop")
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setToolTip("She stops watching your screen")
        self.stop_button.setStyleSheet(f"QToolButton {{ color: {INK.name()}; border: 1px solid {_css(self._accent, 0.5)};"
                                       f" border-radius: 9px; padding: 1px 10px; font-size: 8.5pt; }}"
                                       f" QToolButton:hover {{ background: {_css(self._accent, 0.3)}; }}")
        self.stop_button.clicked.connect(self.look_stopped)
        look_row.addWidget(self.look_label, 1)
        look_row.addWidget(self.stop_button)
        self.look_bar.hide()

        # --- the input
        bottom = QWidget(self)
        row = QHBoxLayout(bottom)
        row.setContentsMargins(12, 6, 12, 12)
        self.look_button = QToolButton()
        self.look_button.setIcon(_icon("eye", INK))
        self.look_button.setToolTip(f"Let {name} watch your screen with you")
        self.look_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.look_button.setStyleSheet(f"QToolButton {{ border: none; border-radius: 15px; min-width: 30px;"
                                       f" min-height: 30px; }} QToolButton:hover {{ background: {_css(self._accent, 0.3)}; }}")
        self.look_button.clicked.connect(self.look_requested)
        row.addWidget(self.look_button)
        self.edit = QLineEdit()
        self.edit.setMaxLength(1000)
        self.edit.setPlaceholderText(f"Say something to {name}...")
        self.edit.setStyleSheet(f"QLineEdit {{ background: {_css(QColor(255, 255, 255), 0.08)}; color: {INK.name()};"
                                f" border: 1px solid {_css(self._accent, 0.45)}; border-radius: 15px; padding: 6px 12px; }}"
                                f" QLineEdit:focus {{ border: 1px solid {_css(self._accent, 0.9)}; }}")
        self.edit.returnPressed.connect(self._send)
        self.send_button = QToolButton()
        self.send_button.setText("➤")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setStyleSheet(f"QToolButton {{ color: white; background: {_css(self._accent, 0.85)};"
                                       " border: none; border-radius: 15px; min-width: 30px; min-height: 30px;"
                                       " font-size: 12pt; } QToolButton:disabled { background: rgba(255,255,255,0.12); }")
        self.send_button.clicked.connect(self._send)
        row.addWidget(self.edit, 1)
        row.addWidget(self.send_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top)
        layout.addWidget(self.area, 1)
        layout.addWidget(self.look_bar)
        layout.addWidget(bottom)
        self._render()

    # ------------------------------------------------------------------ content
    def set_lines(self, lines: list[dict]) -> None:
        """Today's chat (from ChatSession.transcript()). Clears unanswered messages and old notes."""
        self._lines = list(lines)
        self._pending = []
        self._notes = []
        self._render()

    def add_pending(self, text: str, time_text: str = "", image: bool = False) -> None:
        self._pending.append({"role": "user", "text": text, "time": time_text, "image": image})
        self._render()

    def set_watching(self, watching: bool, left: str = "") -> None:
        """Show (or hide) the 'she's watching with you' bar. ``left``: e.g. '42 min left'."""
        self.look_label.setText(f"👀 {self._name} is watching with you" + (f"  ·  {left}" if left else ""))
        if watching == self._watching:
            return
        self._watching = watching
        self.look_bar.setVisible(watching)
        self.edit.setPlaceholderText("Ask about your screen... (or just Enter)" if watching
                                     else f"Say something to {self._name}...")
        self.look_button.setToolTip("Stop watching my screen" if watching
                                    else f"Let {self._name} watch your screen with you")

    @property
    def looking(self) -> bool:
        return self._watching

    def add_note(self, text: str) -> None:
        """Something she says that isn't part of the saved chat (e.g. 'I can't connect')."""
        self._notes.append({"role": "assistant", "text": text, "time": "", "note": True})
        self._render()

    def set_waiting(self, waiting: bool) -> None:
        self._waiting = waiting
        self.send_button.setEnabled(not waiting)
        self._render()

    def bubble_texts(self) -> list[tuple[str, str]]:
        """(role, text) of every bubble on screen, in order (handy for tests)."""
        return [(w.property("role"), w.property("bubble_text")) for w in self.inner.findChildren(QLabel)
                if w.property("role")]

    def bubble_details(self) -> list[str]:
        """The longer help under her bubbles (handy for tests)."""
        return [w.property("details") for w in self.inner.findChildren(QLabel)
                if w.property("role") == "assistant" and w.property("details")]

    def _render(self) -> None:
        while self.column.count():
            widget = self.column.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)  # gone right away (deleteLater alone waits for the event loop)
                widget.deleteLater()
        everything = self._lines + self._pending + self._notes
        if not everything and not self._waiting:
            empty = QLabel(f"No chat yet today.\nSay hi to {self._name}~")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {_css(INK, 0.5)}; font-size: 10pt; padding: 40px 0;")
            self.column.addWidget(empty)
        for line in everything:
            self._add_bubble(line)
        if self._waiting:
            self._add_bubble({"role": "assistant", "text": "...", "time": "", "typing": True})
        self.column.addStretch(1)
        QTimer.singleShot(0, self._scroll_to_end)

    def _add_bubble(self, line: dict) -> None:
        mine = line["role"] == "user"
        details = line.get("details", "")
        label = QLabel()
        if details:  # a look reply: her short line, then the steps / example / question
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setText(f"{html.escape(line['text'])}<div style='margin-top: 6px;'>{details_html(details)}</div>")
        else:
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(line["text"])
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = label.font()
        font.setPointSizeF(10)
        label.setFont(font)
        widest = int(self.W * (0.86 if details else 0.72))
        natural = label.fontMetrics().horizontalAdvance(line["text"]) + 34  # text + padding + a little slack
        label.setFixedWidth(widest if details else min(widest, max(36, natural)))  # short: snug; long: wraps
        label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        if details:  # rich text (code boxes) needs its height worked out up front, or it gets cut to one line
            label.setMinimumHeight(label.heightForWidth(label.width()))
        label.setProperty("role", "user" if mine else "assistant")
        label.setProperty("bubble_text", line["text"])  # not "text": that IS the label text
        label.setProperty("details", details)
        if mine:
            style = (f"background: {_css(self._accent, 0.85)}; color: white;"
                     " border-radius: 14px; border-bottom-right-radius: 4px;")
        else:
            faded = line.get("note") or line.get("typing")
            style = (f"background: {_css(QColor(255, 255, 255), 0.10 if faded else 0.93)};"
                     f" color: {INK.name() if faded else '#3B2F4A'};"
                     " border-radius: 14px; border-bottom-left-radius: 4px;")
        label.setStyleSheet(f"QLabel {{ {style} padding: 7px 11px; }}")
        holder = QHBoxLayout()
        holder.setContentsMargins(0, 0, 0, 0)
        if mine:
            holder.addStretch(1)
        holder.addWidget(label)
        if not mine:
            holder.addStretch(1)
        box = QWidget()
        stack = QVBoxLayout(box)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(2)
        stack.addLayout(holder)
        extra = [line.get("time", "")]
        if line.get("image"):
            extra.append("👀 with your screen")
        if line.get("about"):  # she spoke up by herself about what you opened
            about = line["about"]
            extra.append("👀 " + (about if len(about) <= 52 else about[:50].rstrip() + "…"))
        extra += [f"⏰ {when}: {what}" for when, what in line.get("reminders", [])]
        extra += [f"💭 {fact}" for fact in line.get("remembered", [])]
        extra = "   ".join(x for x in extra if x)
        if extra:
            small = QLabel(extra)
            small.setStyleSheet(f"color: {_css(INK, 0.45)}; font-size: 7.5pt; padding: 0 4px;")
            small.setAlignment(Qt.AlignmentFlag.AlignRight if mine else Qt.AlignmentFlag.AlignLeft)
            stack.addWidget(small)
        self.column.addWidget(box)

    def _scroll_to_end(self) -> None:
        bar = self.area.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _send(self) -> None:
        text = self.edit.text().strip()
        if (text or self.looking) and not self._waiting:
            self.edit.clear()
            self._notes = []
            self.sent.emit(text)

    # ------------------------------------------------------------------ window
    def open_near(self, body: QRect, available: QRect) -> None:
        x = body.left() - self.width() - 10
        if x < available.left():
            x = body.right() + 10
        y = body.bottom() - self.height()
        x = max(available.left(), min(x, available.right() - self.width()))
        y = max(available.top(), min(y, available.bottom() - self.height()))
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()
        QTimer.singleShot(0, self._scroll_to_end)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._top.geometry().contains(event.position().toPoint()):
            self._drag_from = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0, GLASS_TOP)
        gradient.setColorAt(1, GLASS_BOTTOM)
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 140), 1.2))
        painter.drawPath(path)
        line_y = self._top.geometry().bottom() + 1
        painter.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 60), 1))
        painter.drawLine(QPoint(16, line_y), QPoint(int(rect.width()) - 16, line_y))


class _AvatarHolder:
    """Lets ChatLogWindow reuse the menu header's round-face drawing on a plain QLabel."""

    def __init__(self, label: QLabel, smooth: bool):
        self.avatar = label
        self._smooth = smooth


class MemoryWindow(QWidget):
    """'What I remember about you': her facts, diary and your habits, each with a ✕ to delete it."""

    removed = Signal(str, object)  # (section, index or key)
    cleared = Signal()
    W, H = 400, 520

    def __init__(self, name: str, theme: dict[str, str], avatar: QPixmap, smooth: bool = True):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(f"What {name} remembers")
        self.resize(self.W, self.H)
        self._accent = accent_of(theme)
        self._name = name
        self._drag_from: QPoint | None = None
        from .menu_style import Header

        top = QWidget(self)
        bar = QHBoxLayout(top)
        bar.setContentsMargins(14, 12, 10, 6)
        face = QLabel()
        face.setFixedSize(40, 40)
        Header.set_avatar(_AvatarHolder(face, smooth), avatar, self._accent)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("What I remember about you")
        title.setStyleSheet(f"color: {INK.name()}; font-size: 11.5pt; font-weight: 600;")
        self.subtitle = QLabel(name)
        self.subtitle.setStyleSheet(f"color: {_css(INK, 0.6)}; font-size: 8.5pt;")
        titles.addWidget(title)
        titles.addWidget(self.subtitle)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"QToolButton {{ color: {_css(INK, 0.7)}; font-size: 12pt; border: none; padding: 4px 8px;"
                            f" border-radius: 8px; }} QToolButton:hover {{ background: {_css(self._accent, 0.3)}; }}")
        close.clicked.connect(self.hide)
        bar.addWidget(face)
        bar.addLayout(titles, 1)
        bar.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self._top = top

        self.area = QScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area.setStyleSheet(f"""
            QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
            QScrollBar::handle:vertical {{ background: {_css(self._accent, 0.45)}; border-radius: 3px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}""")
        self.inner = QWidget()
        self.column = QVBoxLayout(self.inner)
        self.column.setContentsMargins(16, 6, 12, 6)
        self.column.setSpacing(4)
        self.area.setWidget(self.inner)

        bottom = QWidget(self)
        row = QHBoxLayout(bottom)
        row.setContentsMargins(16, 6, 14, 12)
        hint = QLabel(f"Tell {name} “remember that…” or “forget that…” in chat.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_css(INK, 0.5)}; font-size: 8pt;")
        self.clear_button = QToolButton()
        self.clear_button.setText("Forget everything")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setStyleSheet(f"QToolButton {{ color: {INK.name()}; border: 1px solid {_css(self._accent, 0.5)};"
                                        f" border-radius: 10px; padding: 3px 10px; font-size: 8.5pt; }}"
                                        f" QToolButton:hover {{ background: rgba(232, 143, 143, 0.35); }}")
        self.clear_button.clicked.connect(self._confirm_clear)
        row.addWidget(hint, 1)
        row.addWidget(self.clear_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top)
        layout.addWidget(self.area, 1)
        layout.addWidget(bottom)

    # ------------------------------------------------------------------ content
    def show_memory(self, memory, today, enabled: bool = True) -> None:
        """Fill the window from a memory.Memory."""
        from .memory import _day_label, _habit_text

        while self.column.count():
            widget = self.column.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.subtitle.setText(self._name if enabled else f"{self._name} · remembering is switched off")
        if memory.empty:
            empty = QLabel(f"Nothing yet.\nChat with {self._name}, tell her what you like,\n"
                           "or let her watch with you~")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {_css(INK, 0.5)}; font-size: 10pt; padding: 50px 0;")
            self.column.addWidget(empty)
        if memory.facts:
            self._heading("About you")
            for i in reversed(range(len(memory.facts))):
                self._row(memory.facts[i]["text"], "facts", i)
        if memory.days:
            self._heading("Our days")
            for i in reversed(range(len(memory.days))):
                day = memory.days[i]
                when = _day_label(day["date"], today)
                self._row(f"{when[0].upper()}{when[1:]}: {day['summary']}", "days", i)
        habits = sorted(memory.habits.items(), key=lambda kv: (kv[1]["count"], kv[1]["last"]), reverse=True)
        if habits:
            self._heading("What you often do (while I watch with you)")
            for key, habit in habits[:20]:
                text = _habit_text(habit)
                self._row(f"{text[0].upper()}{text[1:]}  ·  {habit['count']}x", "habits", key)
        self.column.addStretch(1)
        self.clear_button.setEnabled(not memory.empty)

    def rows(self) -> list[tuple[str, str]]:
        """(section, text) of every row on screen (handy for tests)."""
        return [(w.property("section"), w.text()) for w in self.inner.findChildren(QLabel) if w.property("section")]

    def delete_buttons(self) -> list[QToolButton]:
        return [b for b in self.inner.findChildren(QToolButton) if b.property("section")]

    def _heading(self, text: str) -> None:
        label = QLabel(text)
        label.setStyleSheet(f"color: {self._accent.name()}; font-size: 9pt; font-weight: 600; padding-top: 10px;")
        self.column.addWidget(label)

    def _row(self, text: str, section: str, key) -> None:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setProperty("section", section)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setStyleSheet(f"color: {INK.name()}; font-size: 9.5pt; padding: 3px 0;")
        remove = QToolButton()
        remove.setText("✕")
        remove.setToolTip("Forget this")
        remove.setProperty("section", section)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setStyleSheet(f"QToolButton {{ color: {_css(INK, 0.45)}; border: none; padding: 2px 6px;"
                             f" border-radius: 6px; }} QToolButton:hover {{ color: {INK.name()};"
                             f" background: {_css(self._accent, 0.3)}; }}")
        remove.clicked.connect(lambda _=False, s=section, k=key: self.removed.emit(s, k))
        row.addWidget(label, 1)
        row.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
        self.column.addWidget(holder)

    def _confirm_clear(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(QMessageBox.Icon.Question, "Forget everything?",
                          f"{self._name} will forget everything she remembers about you. This can't be undone.",
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.cleared.emit()

    # ------------------------------------------------------------------ window
    def open_near(self, body: QRect, available: QRect) -> None:
        x = body.left() - self.width() - 10
        if x < available.left():
            x = body.right() + 10
        y = body.bottom() - self.height()
        x = max(available.left(), min(x, available.right() - self.width()))
        y = max(available.top(), min(y, available.bottom() - self.height()))
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._top.geometry().contains(event.position().toPoint()):
            self._drag_from = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0, GLASS_TOP)
        gradient.setColorAt(1, GLASS_BOTTOM)
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 140), 1.2))
        painter.drawPath(path)
        line_y = self._top.geometry().bottom() + 1
        painter.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 60), 1))
        painter.drawLine(QPoint(16, line_y), QPoint(int(rect.width()) - 16, line_y))
