"""Her Settings window: everything you can change, in one glass window with tabs.

Changes apply right away (no Save button): each control calls the same Controller method the
old menu items called, and ``refresh()`` reads the current settings back into the controls.
"""

from __future__ import annotations

import time
from datetime import date

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__
from .glass import GlassWindow, Switch, button_style, css, label_style
from .menu_style import INK
from .menu_style import icon as _icon

REPO_URL = "https://github.com/MuizKmz/deskmate"
TABS = [("general", "General", "settings"), ("chat", "Chat", "chat"), ("voice", "Voice", "sparkle"),
        ("buddy", "Buddy", "eye"), ("memory", "Memory", "heart"), ("about", "About", "sun")]


class SettingsWindow(GlassWindow):
    def __init__(self, controller):
        pack = controller.pack
        super().__init__("Settings", pack.name, pack.theme, controller.icon.pixmap(96),
                         smooth=pack.meta.get("smooth", True), size=QSize(600, 500))
        self.c = controller
        self._switches: dict[str, Switch] = {}
        a = self.accent

        self.tabs = QListWidget()
        self.tabs.setFixedWidth(140)
        self.tabs.setIconSize(QSize(18, 18))
        self.tabs.setFrameShape(QFrame.Shape.NoFrame)
        self.tabs.setStyleSheet(f"""
            QListWidget {{ background: transparent; outline: none; }}
            QListWidget::item {{ color: {INK.name()}; padding: 8px 10px; border-radius: 10px; margin: 1px 0; }}
            QListWidget::item:hover {{ background: {css(a, 0.18)}; }}
            QListWidget::item:selected {{ background: {css(a, 0.38)}; color: white; }}""")
        self.pages = QStackedWidget()
        for key, label, icon_name in TABS:
            item = QListWidgetItem(_icon(icon_name, QColor(INK)), label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.tabs.addItem(item)
            self.pages.addWidget(self._scroll(getattr(self, f"_page_{key}")()))
        self.tabs.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.tabs.setCurrentRow(0)

        row = QHBoxLayout(self.body)
        row.setContentsMargins(12, 10, 12, 14)
        row.setSpacing(10)
        row.addWidget(self.tabs)
        row.addWidget(self.pages, 1)
        self.refresh()

    # ---------------------------------------------------------------- building
    def show_tab(self, key: str) -> None:
        for i, (name, _label, _icon_name) in enumerate(TABS):
            if name == key:
                self.tabs.setCurrentRow(i)

    def _scroll(self, page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setStyleSheet(f"""
            QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
            QScrollBar::handle:vertical {{ background: {css(self.accent, 0.45)}; border-radius: 3px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}""")
        area.setWidget(page)
        return area

    def _page(self, heading: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(8, 4, 8, 8)
        column.setSpacing(4)
        title = QLabel(heading)
        title.setStyleSheet(label_style(12, bold=True))
        column.addWidget(title)
        return page, column

    def _row(self, column: QVBoxLayout, title: str, description: str, control: QWidget) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 6, 0, 6)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        name = QLabel(title)
        name.setStyleSheet(label_style(10))
        texts.addWidget(name)
        if description:
            small = QLabel(description)
            small.setWordWrap(True)
            small.setStyleSheet(label_style(8.5, 0.55))
            texts.addWidget(small)
        row.addLayout(texts, 1)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(holder)
        return holder

    def _switch(self, column, key: str, title: str, description: str, slot) -> Switch:
        switch = Switch(self.accent)
        switch.toggled.connect(slot)
        self._switches[key] = switch
        self._row(column, title, description, switch)
        return switch

    def _combo(self, items: list[tuple[str, str]], slot) -> QComboBox:
        combo = QComboBox()
        for value, label in items:
            combo.addItem(label, value)
        combo.setMinimumWidth(170)
        a = self.accent
        combo.setStyleSheet(f"QComboBox {{ color: {INK.name()}; background: rgba(255,255,255,0.06);"
                            f" border: 1px solid {css(a, 0.5)}; border-radius: 10px; padding: 4px 10px; }}"
                            f" QComboBox QAbstractItemView {{ color: {INK.name()}; background: #241C30;"
                            f" selection-background-color: {css(a, 0.45)}; border: 1px solid {css(a, 0.5)}; }}")
        combo.activated.connect(lambda _i: slot(combo.currentData()))
        return combo

    def _button(self, text: str, slot, strong: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(button_style(self.accent, strong))
        button.clicked.connect(lambda _=False: slot())
        return button

    def _buttons(self, column: QVBoxLayout, *buttons: QPushButton) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 4)
        for button in buttons:
            row.addWidget(button)
        row.addStretch(1)
        column.addLayout(row)

    def _info(self, column: QVBoxLayout) -> QLabel:
        label = QLabel("")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setStyleSheet(label_style(9, 0.75) + f" background: {css(self.accent, 0.12)};"
                            " border-radius: 10px; padding: 8px 10px;")
        column.addWidget(label)
        return label

    # ------------------------------------------------------------------- pages
    def _page_general(self) -> QWidget:
        from . import autostart, perch
        from .settings import SIZES

        c, name = self.c, self.c.pack.name
        page, column = self._page("General")
        self.size = self._combo([(s, s.title()) for s in SIZES], c._set_size)
        self._row(column, "Size", f"How big {name} is on your screen.", self.size)
        self._switch(column, "always_on_top", "Always on top", "Stays above your other windows.", c._set_on_top)
        self._switch(column, "gravity", "Gravity", "Falls down to the taskbar (and can be thrown).", c._set_gravity)
        self._switch(column, "wander", "Wander around", "Takes a little walk now and then.", c._set_wander)
        if perch.supported():
            self._switch(column, "perch", "Sit on windows", "Lands on the top edge of your windows.", c._set_perch)
        self._switch(column, "chatty", "Chit-chat now and then", "Says little things on her own.", c._set_chatty)
        self._switch(column, "reminders", "Care reminders", "Water, breaks, and bedtime nudges.", c._set_reminders)
        if autostart.supported():
            self._switch(column, "autostart", "Start with Windows", f"{name} is there when you sign in.",
                         c._set_autostart)
        self._buttons(column, self._button("Move her back to the corner", c.companion.reset_position))
        column.addStretch(1)
        return page

    def _page_chat(self) -> QWidget:
        c = self.c
        page, column = self._page("Chat")
        self.chat_info = self._info(column)
        self._buttons(column, self._button("Chat settings...", self._chat_settings, strong=True),
                      self._button("Today's chat", c.open_chat_log))
        self._buttons(column, self._button("Forget today's chat", c._forget_chat))
        column.addStretch(1)
        return page

    def _page_voice(self) -> QWidget:
        c = self.c
        page, column = self._page("Voice")
        self.voice = self._combo([("off", "Off"), ("windows", "Windows voice (free)"), ("openai", "Natural voice")],
                                 self._set_voice)
        self._row(column, "Her voice", "Off, the free Windows voice, or a natural one.", self.voice)
        self.voice_lines = self._combo([("all", "Everything"), ("chat", "Only chat replies")], c._set_voice_lines)
        self._row(column, "Says out loud", "Her bubble always shows the text.", self.voice_lines)
        self.voice_info = self._info(column)
        self._buttons(column, self._button("Voice settings...", self._voice_settings, strong=True))
        column.addStretch(1)
        return page

    def _page_buddy(self) -> QWidget:
        c = self.c
        page, column = self._page("Buddy mode")
        intro = QLabel(f"{c.pack.name} watches what you're doing (with your permission, every time) and reacts "
                       "like a friend next to you: the videos, songs and apps you open. Never private windows, "
                       "banking or calls.")
        intro.setWordWrap(True)
        intro.setStyleSheet(label_style(9, 0.7))
        column.addWidget(intro)
        self.buddy_info = self._info(column)
        self.watch_button = self._button("Watch with me...", self._toggle_watching, strong=True)
        self._buttons(column, self.watch_button)
        self._switch(column, "watch_badge", "Show the 👁 sign while she watches", "A small sign by her head.",
                     lambda on: c._set("watch_badge", bool(on)))
        column.addStretch(1)
        return page

    def _page_memory(self) -> QWidget:
        c = self.c
        page, column = self._page("Memory")
        self._switch(column, "remember", "Remember me across days",
                     "Things you tell her, a little diary, and what you often do.", c._set_remember)
        self.memory_info = self._info(column)
        self._buttons(column, self._button("What I remember about you", c.open_memory, strong=True))
        column.addStretch(1)
        return page

    def _page_about(self) -> QWidget:
        c = self.c
        page, column = self._page("About")
        version = QLabel(f"{APP_NAME} {__version__}")
        version.setStyleSheet(label_style(11, bold=True))
        column.addWidget(version)
        link = QLabel(f'<a href="{REPO_URL}" style="color: {self.accent.name()};">{REPO_URL}</a>')
        link.setOpenExternalLinks(True)
        column.addWidget(link)
        self._switch(column, "update_check", "Check for updates", "Once a day, she looks for a newer version.",
                     c._set_update_check)
        self._buttons(column, self._button("Check now", lambda: c.check_for_updates(manual=True)),
                      self._button("What's new", c.show_whats_new))
        self._buttons(column, self._button("Run setup again", c.start_setup),
                      self._button("Open settings && logs folder", c._open_data_folder))
        column.addStretch(1)
        return page

    # ----------------------------------------------------------------- actions
    def _chat_settings(self) -> None:
        self.c.open_chat_settings()
        self.refresh()

    def _voice_settings(self) -> None:
        self.c.open_voice_settings()
        self.refresh()

    def _set_voice(self, mode: str) -> None:
        self.c._set_voice(mode)
        self.refresh()

    def _toggle_watching(self) -> None:
        self.c.toggle_watching()
        self.refresh()

    # ----------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Show the current settings (called when opened, and after anything changes)."""
        from . import autostart

        c, s = self.c, self.c.settings
        values = {key: s[key] for key in ("always_on_top", "gravity", "wander", "perch", "chatty", "reminders",
                                          "watch_badge", "remember", "update_check")}
        values["autostart"] = autostart.is_enabled() if "autostart" in self._switches else False
        for key, switch in self._switches.items():
            switch.blockSignals(True)
            switch.setChecked(bool(values.get(key)))
            switch.blockSignals(False)
            switch.update()
        for combo, value in ((self.size, s["size"]), (self.voice, s["voice"]), (self.voice_lines, s["voice_lines"])):
            combo.setCurrentIndex(max(0, combo.findData(value)))

        from .chat import MODEL_SETTINGS

        provider = s["chat_provider"]
        brain = {"openai": "OpenAI", "claude": "Claude", "ollama": "Ollama (on this PC)"}.get(provider, provider)
        model = s[MODEL_SETTINGS[provider]] or "picked automatically"
        ready = (not c.chat.config.needs_key) or bool(c.chat.config.api_key)
        self.chat_info.setText(f"Chat brain: {brain}  ·  model: {model}" +
                               ("" if ready else "\nNo key yet: open Chat settings to add one."))

        if s["tts_source"] == "builtin":
            ready = "downloaded" if c.voice_pack().installed else "not downloaded yet"
            natural = f"built-in voice pack ({ready}), voice {s['openai_voice']}"
        elif s["tts_source"] == "local":
            natural = f"your own server ({s['tts_url']}), voice {s['openai_voice']}"
        else:
            natural = f"OpenAI, voice {s['openai_voice']}"
        windows = s["windows_voice"] or "automatic (first female voice)"
        language = c._spoken_language()
        self.voice_info.setText(f"Windows voice: {windows}\nNatural voice: {natural}" +
                                (f"\nShe says her lines in {language} (the chat stays English)." if language else ""))

        if c.watch is not None:
            left = c.watch.left(time.monotonic())
            self.buddy_info.setText("She's watching with you now" + (f"  ·  {left}" if left else "  ·  until you stop"))
            self.watch_button.setText("Stop watching")
        else:
            self.buddy_info.setText("She isn't watching right now.")
            self.watch_button.setText("Watch with me...")

        memory = c.memory
        habits = len(memory.frequent(date.today(), limit=999))
        self.memory_info.setText(
            (f"She remembers {len(memory.facts)} thing{'s' if len(memory.facts) != 1 else ''} about you, "
             f"{len(memory.days)} day{'s' if len(memory.days) != 1 else ''} in her diary, and "
             f"{habits} habit{'s' if habits != 1 else ''}.") if not memory.empty else "Nothing yet.")
