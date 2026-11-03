"""The chat window (a little text box next to her) and the Chat settings dialog."""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from .chat import OLLAMA_URL, ChatConfig, ChatError, list_models, mask, pick_model
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
        self.history_button = QToolButton(self)
        self.history_button.setIcon(_icon("clock", self._accent.darker(130)))
        self.history_button.setToolTip("Today's chat")
        self.history_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_button.setAutoRaise(True)
        self.history_button.clicked.connect(self.history_requested)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.addWidget(self.history_button)
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


def _css(color: QColor, alpha: float | None = None) -> str:
    a = color.alphaF() if alpha is None else alpha
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {a:.2f})"


class ChatLogWindow(QWidget):
    """Today's chat, as bubbles you can scroll back through, with its own input box.

    A small glass window in the character's colours (like her menu). Drag it by the top bar.
    """

    sent = Signal(str)
    W, H = 360, 500

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

        # --- the input
        bottom = QWidget(self)
        row = QHBoxLayout(bottom)
        row.setContentsMargins(12, 6, 12, 12)
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
        layout.addWidget(bottom)
        self._render()

    # ------------------------------------------------------------------ content
    def set_lines(self, lines: list[dict]) -> None:
        """Today's chat (from ChatSession.transcript()). Clears unanswered messages and old notes."""
        self._lines = list(lines)
        self._pending = []
        self._notes = []
        self._render()

    def add_pending(self, text: str, time_text: str = "") -> None:
        self._pending.append({"role": "user", "text": text, "time": time_text})
        self._render()

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
        return [(w.property("role"), w.property("text")) for w in self.inner.findChildren(QLabel)
                if w.property("role")]

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
        label = QLabel(line["text"])
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = label.font()
        font.setPointSizeF(10)
        label.setFont(font)
        widest = int(self.W * 0.72)
        natural = label.fontMetrics().horizontalAdvance(line["text"]) + 34  # text + padding + a little slack
        label.setFixedWidth(min(widest, max(36, natural)))  # short text: snug bubble; long text: wraps at 72%
        label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        label.setProperty("role", "user" if mine else "assistant")
        label.setProperty("text", line["text"])
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
        extra += [f"⏰ {when}: {what}" for when, what in line.get("reminders", [])]
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
        if text and not self._waiting:
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
