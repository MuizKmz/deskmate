"""The chat window (a little text box next to her) and the Chat settings dialog."""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QToolButton, QVBoxLayout, QWidget,
)

from .chat import OLLAMA_URL, ChatConfig, ChatError, list_models, mask, pick_model


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

    def __init__(self, name: str, theme: dict[str, str]):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(f"Chat with {name}")
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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 8, 8)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.send_button)
        self.resize(300, 46)
        self._waiting = False

    def set_waiting(self, waiting: bool) -> None:
        """While she's thinking, you can type but not send (one question at a time)."""
        self._waiting = waiting
        self.send_button.setEnabled(not waiting)
        self.send_button.setText("…" if waiting else "➤")

    def _send(self) -> None:
        text = self.edit.text().strip()
        if text and not self._waiting:
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
    """Choose OpenAI or Ollama, paste the key, pick a model, and test it."""

    def __init__(self, settings, current_key: str, name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Chat with {name}: settings")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(460)
        self._settings = settings
        self._key = current_key
        self._worker = Background(self)

        self.provider = QComboBox()
        self.provider.addItem("OpenAI (needs an API key)", "openai")
        self.provider.addItem("Ollama (free, runs on this PC)", "ollama")
        self.provider.setCurrentIndex(0 if settings["chat_provider"] == "openai" else 1)

        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(f"saved: {mask(current_key)}  (leave empty to keep it)" if current_key
                                    else "sk-...  (paste your key here)")
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
        note = QLabel("The key is saved only on this PC (in your DeskMate settings folder), "
                      "never in the project folder. Tip: set a monthly spending limit in your OpenAI account.")
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
    def chosen_key(self) -> str:
        return self.key.text().strip() or self._key

    @property
    def chosen_model(self) -> str:
        return self.model.currentText().strip()

    def config(self) -> ChatConfig:
        ollama = self.chosen_provider == "ollama"
        return ChatConfig(provider=self.chosen_provider, model=self.chosen_model,
                          api_key="" if ollama else self.chosen_key,
                          base_url=self.url.text().strip() if ollama else "")

    def _provider_changed(self) -> None:
        ollama = self.chosen_provider == "ollama"
        self.form.setRowVisible(self.key, not ollama)
        self.form.setRowVisible(self.url, ollama)
        self.model.clear()
        current = self._settings["ollama_model" if ollama else "chat_model"]
        if current:
            self.model.addItem(current)
        self.model.setEditText(current)
        self.status.setText("Install Ollama from ollama.com, then run:  ollama pull llama3.2" if ollama else "")

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


def describe_error(error: BaseException) -> str:
    if isinstance(error, ChatError):
        return {
            "no_key": "Paste your OpenAI API key first.",
            "auth": "That key was refused. Check it (and that it's not deleted) on platform.openai.com.",
            "quota": "Out of credit or rate-limited. Check billing on platform.openai.com.",
            "model": f"Model problem: {error.detail}",
            "offline": "Can't connect. Is the internet on? For Ollama: is it running?",
            "timeout": "No answer in time. Try again.",
        }.get(error.kind, f"Error: {error.detail or error.kind}")
    return f"Error: {error}"
