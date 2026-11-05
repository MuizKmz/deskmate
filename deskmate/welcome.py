"""First-run setup ("Hi! Let's set me up~") and the "What's new" window after an update."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from . import __version__
from .glass import GlassWindow, button_style, css, label_style
from .menu_style import INK

WHATS_NEW = {
    "0.9.0": [
        ("🎵", "She dances", "When Spotify or YouTube Music plays, she dances, on the beat. Or right-click › Play › "
                            "Dance!"),
        ("💗", "Your bond", "Grows with pats, chats, focus and games. She gets a little closer as it does."),
        ("🎀", "Outfits", "A bow, cat ears, headphones, a crown... unlocked by your bond. Party hat on your "
                         "birthday!"),
        ("🎮", "Mini-games", "Rock, paper, scissors, tic-tac-toe and hide and seek (right-click › Play)."),
    ],
    "0.8.0": [
        ("🍅", "Focus timer", "Right-click her › Focus. She keeps quiet, counts down, cheers at the end, and nudges you "
                             "if you drift off to YouTube."),
        ("🌙", "Your day", "An evening wrap-up of your day (right-click › My day anytime). App names only, kept on "
                          "this PC."),
        ("🎉", "Special days", "Your birthday, Hari Raya, Deepavali, Merdeka, payday, Fridays."),
        ("🌤", "Weather", "Set your city in Settings › My day: the morning weather, and a heads-up before rain."),
        ("🧩", "Stuck helper", "In buddy mode, if you've been fighting an error for a while, she offers to look."),
    ],
    "0.7.0": [
        ("🧠", "Claude as a chat brain", "Next to OpenAI and Ollama (Settings › Chat)."),
        ("👀", "Watch with me (buddy mode)", "She notices what you open, hears your music, and reacts like a friend. "
                                            "Only when you allow it."),
        ("💭", "She remembers you", "Your birthday, your projects, your songs, and a little diary of your days."),
        ("🔊", "More voices", "Any Windows voice, or a free natural voice pack that runs on this PC (no setup). A "
                             "Japanese voice can even say her lines in Japanese."),
        ("👄", "She moves her mouth", "Her lips move in time with her voice while she talks."),
        ("⚙️", "A Settings window", "Everything in one place (right-click › Settings)."),
    ],
}


class _Choices(QWidget):
    """A column of big option buttons; one can be chosen."""

    def __init__(self, accent, options: list[tuple[str, str, str]], on_choose):
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 4, 0, 4)
        column.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, title, description in options:
            button = QPushButton(f"{title}\n{description}" if description else title)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                f"QPushButton {{ text-align: left; color: {INK.name()}; background: rgba(255,255,255,0.05);"
                f" border: 1px solid {css(accent, 0.35)}; border-radius: 12px; padding: 8px 14px; }}"
                f" QPushButton:hover {{ background: {css(accent, 0.2)}; }}"
                f" QPushButton:checked {{ background: {css(accent, 0.4)}; border: 1px solid {css(accent, 0.9)}; }}")
            button.clicked.connect(lambda _=False, k=key: on_choose(k))
            self.group.addButton(button)
            column.addWidget(button)
            self.buttons[key] = button

    def choose(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)


class SetupWizard(GlassWindow):
    """Four short steps: chat brain, voice, buddy mode, done. Every step can be skipped."""

    STEPS = ("hello", "chat", "voice", "buddy", "done")

    def __init__(self, controller):
        pack = controller.pack
        super().__init__("Let's set me up~", f"{pack.name} · takes a minute", pack.theme, controller.icon.pixmap(96),
                         smooth=pack.meta.get("smooth", True), size=QSize(500, 470))
        self.c = controller
        self.pages = QStackedWidget()
        for step in self.STEPS:
            self.pages.addWidget(getattr(self, f"_step_{step}")())

        self.skip = self._button("Skip setup", self.finish)
        self.back = self._button("Back", lambda: self.go(self.pages.currentIndex() - 1))
        self.next = self._button("Next", lambda: self.go(self.pages.currentIndex() + 1), strong=True)
        nav = QHBoxLayout()
        nav.addWidget(self.skip)
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(22, 12, 22, 16)
        layout.addWidget(self.pages, 1)
        layout.addLayout(nav)
        self.go(0)

    # ------------------------------------------------------------- navigation
    @property
    def step(self) -> str:
        return self.STEPS[self.pages.currentIndex()]

    def go(self, index: int) -> None:
        if index >= len(self.STEPS):
            self.finish()
            return
        self.pages.setCurrentIndex(max(0, index))
        last = self.pages.currentIndex() == len(self.STEPS) - 1
        self.back.setVisible(self.pages.currentIndex() > 0)
        self.skip.setVisible(not last)
        self.next.setText("Done" if last else "Next")
        self._refresh()

    def finish(self) -> None:
        self.c._set("setup_done", True)
        self.close()
        self.c._event(lambda now: self.c.brain.say(now, "All set~ Right-click me anytime for more!", "happy"))

    # ------------------------------------------------------------------ steps
    def _button(self, text: str, slot, strong: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(button_style(self.accent, strong))
        button.clicked.connect(lambda _=False: slot())
        return button

    def _step(self, title: str, text: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(title)
        heading.setStyleSheet(label_style(13, bold=True))
        body = QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet(label_style(9.5, 0.8))
        column.addWidget(heading)
        column.addWidget(body)
        return page, column

    def _status(self, column: QVBoxLayout) -> QLabel:
        label = QLabel("")
        label.setWordWrap(True)
        label.setStyleSheet(label_style(9, 0.75))
        column.addWidget(label)
        return label

    def _step_hello(self) -> QWidget:
        name = self.c.pack.name
        page, column = self._step(f"Hi! I'm {name}~",
                                  "I live on your desktop and keep you company. Let's pick how I think and how I "
                                  "sound. Every step can be skipped, and you can change it all later in Settings.")
        column.addStretch(1)
        return page

    def _step_chat(self) -> QWidget:
        page, column = self._step("How should I think?", "To chat with you I need a chat brain.")
        self.chat_choices = _Choices(self.accent, [
            ("openai", "OpenAI", "Smart and quick. Needs an OpenAI API key (a fraction of a cent per message)."),
            ("claude", "Claude", "Smart and kind. Needs an Anthropic API key."),
            ("ollama", "Ollama", "Free, runs on this PC. Install Ollama first (ollama.com)."),
            ("skip", "Not now", "I'll still do my thing, just without chatting."),
        ], self._choose_chat)
        column.addWidget(self.chat_choices)
        self.chat_status = self._status(column)
        column.addStretch(1)
        return page

    def _step_voice(self) -> QWidget:
        page, column = self._step("How should I sound?", "My speech bubble always shows the text.")
        self.voice_choices = _Choices(self.accent, [
            ("off", "Quiet", "Text only."),
            ("windows", "Windows voice", "Free and offline, a little robotic."),
            ("openai", "Natural voice (OpenAI)", "Sounds real. Uses your OpenAI key."),
            ("builtin", "Natural voice (free voice pack)", "Free and offline. A one-time download (~130 MB)."),
        ], self._choose_voice)
        column.addWidget(self.voice_choices)
        self.voice_status = self._status(column)
        self.voice_test = self._button("Test", self._test_voice)
        self.voice_more = self._button("More voice settings...", self._voice_settings)
        row = QHBoxLayout()
        row.addWidget(self.voice_test)
        row.addWidget(self.voice_more)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)
        return page

    def _step_buddy(self) -> QWidget:
        name = self.c.pack.name
        page, column = self._step("Want me to watch with you?",
                                  f"In buddy mode, {name} notices what you're doing (the video, the song, the app) "
                                  "and reacts like a friend next to you. She asks your permission every time, never "
                                  "looks at private windows or banking, and you can stop it with one click.")
        self.buddy_status = self._status(column)
        row = QHBoxLayout()
        row.addWidget(self._button("Try it now", self._try_buddy, strong=True))
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)
        return page

    def _step_done(self) -> QWidget:
        name = self.c.pack.name
        page, column = self._step("All set!", "")
        tips = QLabel("• <b>Right-click me</b> for everything: chat, watch with me, reminders, settings.<br>"
                      "• <b>Drag me</b> anywhere, or throw me (I'll land on your windows).<br>"
                      "• <b>Click me</b> to say hi. Tell me “remember that…” in chat and I will.<br>"
                      f"• Change anything later in <b>Settings</b>. Have fun with {name}~")
        tips.setWordWrap(True)
        tips.setStyleSheet(label_style(9.5, 0.85))
        column.addWidget(tips)
        column.addStretch(1)
        return page

    # ---------------------------------------------------------------- actions
    def _refresh(self) -> None:
        s, c = self.c.settings, self.c
        ready = (not c.chat.config.needs_key) or bool(c.chat.config.api_key)
        brain = {"openai": "OpenAI", "claude": "Claude", "ollama": "Ollama"}.get(s["chat_provider"], "")
        self.chat_status.setText(f"✓ Ready: {brain}" if ready and brain else "")
        own = s["voice"] == "openai" and s["tts_source"] in ("builtin", "local")
        voice = "builtin" if own else s["voice"]  # (your own server counts too: it's set up in voice settings)
        self.voice_choices.choose(voice)
        self.voice_test.setEnabled(s["voice"] != "off")
        self.buddy_status.setText("✓ She's watching with you." if c.watch is not None else "")

    def _choose_chat(self, provider: str) -> None:
        if provider == "skip":
            self.go(self.pages.currentIndex() + 1)
            return
        self.c._set("chat_provider", provider)
        self.c.open_chat_settings()
        self._refresh()

    def _choose_voice(self, choice: str) -> None:
        if choice == "builtin":
            from .voice import OPENAI_VOICES, OWN_SERVER_VOICE

            self.c._set("tts_source", "builtin")
            if self.c.settings["openai_voice"] in OPENAI_VOICES:
                self.c._set("openai_voice", OWN_SERVER_VOICE)  # OpenAI's names mean nothing to the pack
            self.c.speaker = self.c._make_speaker()
            if self.c.voice_pack().installed:
                self.c._set_voice("openai")
            else:
                self.c._set("voice", "openai")
                self.c.speaker.mode = "openai"
                self.c.open_voice_settings()  # where the Download button is
        else:
            if choice == "openai":
                self.c._set("tts_source", "openai")
                self.c.speaker = self.c._make_speaker()
            self.c._set_voice(choice)
        self._refresh()
        self.voice_status.setText("" if choice == "off" else "Tap Test to hear me.")

    def _test_voice(self) -> None:
        self.c.speaker.say("Hi~ This is my voice. Do you like it?", "chat")

    def _voice_settings(self) -> None:
        self.c.open_voice_settings()
        self._refresh()

    def _try_buddy(self) -> None:
        self.c.start_watching()
        self._refresh()


class WhatsNewWindow(GlassWindow):
    """Shown once after an update: what's new in this version."""

    def __init__(self, controller, version: str = __version__):
        pack = controller.pack
        super().__init__(f"What's new in {version}", f"{pack.name} got an update~", pack.theme,
                         controller.icon.pixmap(96), smooth=pack.meta.get("smooth", True), size=QSize(460, 440))
        self.c = controller
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(20, 10, 20, 16)
        layout.setSpacing(8)
        self.items = WHATS_NEW.get(version, [])
        for emoji, title, text in self.items:
            row = QHBoxLayout()
            mark = QLabel(emoji)
            mark.setFixedWidth(28)
            mark.setStyleSheet("font-size: 15pt;")
            words = QLabel(f"<b>{title}</b><br><span style='color: {css(INK, 0.7)};'>{text}</span>")
            words.setWordWrap(True)
            words.setStyleSheet(label_style(9.5))
            row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(words, 1)
            layout.addLayout(row)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for text, slot, strong in (("Open Settings", self._settings, False), ("Nice~", self.close, True)):
            button = QPushButton(text)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(button_style(self.accent, strong))
            button.clicked.connect(lambda _=False, f=slot: f())
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def _settings(self) -> None:
        self.close()
        self.c.open_settings()
