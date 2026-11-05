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
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__
from .glass import GlassWindow, Switch, button_style, css, label_style
from .menu_style import INK
from .menu_style import icon as _icon

REPO_URL = "https://github.com/MuizKmz/deskmate"
TABS = [("general", "General", "settings"), ("chat", "Chat", "chat"), ("voice", "Voice", "sparkle"),
        ("buddy", "Buddy", "eye"), ("day", "My day", "chart"), ("fun", "Fun", "game"), ("memory", "Memory", "heart"),
        ("about", "About", "sun")]
COUNTRIES = [("auto", "Automatic (from Windows)"), ("MY", "Malaysia"), ("SG", "Singapore"), ("ID", "Indonesia"),
             ("BN", "Brunei"), ("TH", "Thailand"), ("PH", "Philippines"), ("JP", "Japan"), ("KR", "South Korea"),
             ("AU", "Australia"), ("GB", "United Kingdom"), ("US", "United States"), ("", "None")]


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

    def _field(self, placeholder: str, slot, width: int = 170) -> QLineEdit:
        """A small text box; ``slot(text)`` when you press Enter or leave it."""
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setFixedWidth(width)
        edit.setStyleSheet(f"QLineEdit {{ color: {INK.name()}; background: rgba(255,255,255,0.06);"
                           f" border: 1px solid {css(self.accent, 0.5)}; border-radius: 10px; padding: 4px 10px; }}")
        edit.editingFinished.connect(lambda: slot(edit.text()))
        return edit

    def _heading(self, column: QVBoxLayout, text: str) -> None:
        label = QLabel(text)
        label.setStyleSheet(label_style(10, 0.85, bold=True) + " margin-top: 10px;")
        column.addWidget(label)

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
        self._switch(column, "stuck_help", "Offer help when I'm stuck",
                     "If you've been fighting an error for a while, she offers to take a look.",
                     lambda on: c._set("stuck_help", bool(on)))
        column.addStretch(1)
        return page

    def _page_day(self) -> QWidget:
        from .weather import CREDIT

        c, name = self.c, self.c.pack.name
        page, column = self._page("My day")

        self._heading(column, "🍅 Focus timer")
        self.focus_length = self._combo([(m, f"{m} minutes") for m in (15, 25, 30, 45, 50, 60, 90)],
                                        lambda m: c._set("focus_minutes", int(m)))
        self._row(column, "Focus length", f"Right-click {name} › Focus. She keeps quiet while you work.",
                  self.focus_length)
        self._switch(column, "focus_nudge", "Nudge me if I drift off",
                     "A gentle word if you wander to YouTube or games while focusing.",
                     lambda on: c._set("focus_nudge", bool(on)))
        self.focus_button = self._button("Start focusing", self._toggle_focus, strong=True)
        self._buttons(column, self.focus_button)

        self._heading(column, "🌙 Evening wrap-up")
        self._switch(column, "day_log", "Keep a little log of my day",
                     "App names and minutes, songs, focus. Only on this PC, never window titles.", self._set_day_log)
        self._switch(column, "wrapup", "Evening wrap-up", f"{name} tells you about your day.",
                     lambda on: c._set("wrapup", bool(on)))
        self.wrapup_hour = self._combo([(h, f"from {h % 12 or 12} {'pm' if h >= 12 else 'am'}") for h in
                                        range(17, 24)], lambda h: c._set("wrapup_hour", int(h)))
        self._row(column, "When", "Once a day, after this time.", self.wrapup_hour)
        self._buttons(column, self._button("My day", c.day.open_day), self._button("Clear the log", self._clear_log))

        self._heading(column, "🎉 Special days")
        self._switch(column, "special_days", "Special days", "Your birthday, holidays, payday, Fridays.",
                     lambda on: c._set("special_days", bool(on)))
        self.birthday = self._field("e.g. 31 Dec", self._set_birthday)
        self._row(column, "Your birthday", "Day and month.", self.birthday)
        from .dayhelper import system_country

        here = system_country()
        names = dict(COUNTRIES)
        countries = [("auto", f"Automatic ({names.get(here, here or 'unknown')})")] + COUNTRIES[1:]
        self.country = self._combo(countries, lambda v: c._set("country", v))
        self._row(column, "Holidays from", "Hari Raya, Chinese New Year, Deepavali, Merdeka...", self.country)
        self.region = self._field("e.g. JHR", lambda t: c._set("region", t.strip().upper()[:10]), 130)
        self._row(column, "State", "For state holidays (JHR, SGR, KUL, PNG...).", self.region)
        self.payday = self._combo([(0, "Don't mention")] + [(d, f"Day {d}") for d in range(1, 31)] +
                                  [(31, "Last day of the month")], lambda d: c._set("payday", int(d)))
        self._row(column, "Payday", "", self.payday)

        self._heading(column, "🌤 Weather")
        self.city = self._field("e.g. Johor Bahru", self._set_city)
        self._row(column, "Your city", "Morning weather, and a heads-up before rain.", self.city)
        self.weather_info = self._info(column)
        self._buttons(column, self._button("Check now", self._check_weather))
        credit = QLabel(f'<a href="https://open-meteo.com/" style="color: {self.accent.name()};">{CREDIT}</a>')
        credit.setOpenExternalLinks(True)
        credit.setStyleSheet(label_style(8, 0.6))
        column.addWidget(credit)
        column.addStretch(1)
        return page

    def _page_fun(self) -> QWidget:
        from PySide6.QtWidgets import QProgressBar

        c, name = self.c, self.c.pack.name
        page, column = self._page("Fun")
        self._heading(column, f"💗 You and {name}")
        self.bond_info = self._info(column)
        self.bond_bar = QProgressBar()
        self.bond_bar.setRange(0, 1000)
        self.bond_bar.setTextVisible(False)
        self.bond_bar.setFixedHeight(8)
        self.bond_bar.setStyleSheet(f"QProgressBar {{ background: rgba(255,255,255,0.08); border: none;"
                                    f" border-radius: 4px; }} QProgressBar::chunk {{ background: {css(self.accent)};"
                                    " border-radius: 4px; }")
        column.addWidget(self.bond_bar)
        hint = QLabel("Grows with pats, chats, focus sessions, games and dancing together. It never goes down.")
        hint.setWordWrap(True)
        hint.setStyleSheet(label_style(8.5, 0.55))
        column.addWidget(hint)

        self._heading(column, "🎀 Outfit")
        self.outfit = self._combo([("", "Nothing")], self._set_outfit)
        self._row(column, "Wearing", "More unlock as your bond grows.", self.outfit)
        self._switch(column, "outfit_seasonal", "Dress up on special days",
                     "A party hat on your birthday, a Santa hat at Christmas, a witch hat on Halloween.",
                     self._set_seasonal)

        self._heading(column, "🎵 Dancing")
        self._switch(column, "dance", "Dance to my music",
                     "When Spotify or YouTube Music is playing. On the beat, if Windows lets her hear how loud it is.",
                     lambda on: c._set("dance", bool(on)))

        self._heading(column, "🎮 Play")
        self._buttons(column, self._button("Rock, paper, scissors", c.fun.rock_paper_scissors),
                      self._button("Tic-tac-toe", c.fun.tic_tac_toe))
        self._buttons(column, self._button("Hide and seek", self._hide_and_seek),
                      self._button("Dance!", c.fun.dance))
        column.addStretch(1)
        return page

    def _set_outfit(self, key: str) -> None:
        self.c.fun.set_outfit(key)
        self.refresh()

    def _set_seasonal(self, on: bool) -> None:
        self.c._set("outfit_seasonal", bool(on))
        self.c.fun.apply_outfit()

    def _hide_and_seek(self) -> None:
        self.close()  # (out of the way: she needs the screen)
        self.c.fun.hide_and_seek()

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

    def _refresh_fun(self) -> None:
        from .outfits import OUTFITS

        c, s = self.c, self.c.settings
        level = c.fun.level()
        days = c.fun.bond.days_together(c.pack.id, c.fun.today())
        self.bond_info.setText(f"{level.name}  ·  level {level.number}"
                               + (f"  ·  {level.next_at - level.points} points to the next" if level.next_at else "")
                               + f"\nTogether for {days} day{'s' if days != 1 else ''}")
        self.bond_bar.setValue(int(level.progress * 1000))
        self.outfit.blockSignals(True)
        self.outfit.clear()
        self.outfit.addItem("Nothing", "")
        model = self.outfit.model()
        for outfit in OUTFITS:
            if not outfit.level:
                continue
            locked = outfit.level > level.number
            self.outfit.addItem(f"🔒 {outfit.name} (Lv {outfit.level})" if locked else f"{outfit.emoji} {outfit.name}",
                                outfit.key)
            if locked:
                model.item(self.outfit.count() - 1).setEnabled(False)
        index = self.outfit.findData(s["outfit"])
        if index < 0 or not model.item(index).isEnabled():
            index = 0  # (not unlocked with this character)
        self.outfit.setCurrentIndex(index)
        self.outfit.blockSignals(False)

    def _toggle_focus(self) -> None:
        if self.c.day.focus is not None:
            self.c.day.stop_focus()
        else:
            self.c.day.start_focus()
        self.refresh()

    def _set_day_log(self, on: bool) -> None:
        self.c._set("day_log", bool(on))

    def _clear_log(self) -> None:
        self.c.day.clear_log()
        self.weather_info.setText("Cleared: today's log starts fresh.")

    def _set_birthday(self, text: str) -> None:
        from .days import valid_birthday

        value = valid_birthday(text)
        if value is None:
            self.birthday.setToolTip("Hmm, that's not a date. Try 31 Dec or 31/12.")
            self.birthday.setProperty("bad", True)
            self.birthday.setStyleSheet(self.birthday.styleSheet() + " QLineEdit { border: 1px solid #E06C75; }")
            return
        if self.birthday.property("bad"):
            self.birthday.setProperty("bad", False)
            self.birthday.setStyleSheet(self.birthday.styleSheet().replace(" QLineEdit { border: 1px solid #E06C75; }", ""))
        self.birthday.setToolTip("")
        self.c._set("birthday", value)
        self.refresh()

    def _set_city(self, text: str) -> None:
        city = text.strip()[:80]
        if city != self.c.settings["weather_city"]:
            self.c._set("weather_city", city)
            self.c.day.city_changed()
            if city:
                self._check_weather()
            else:
                self.weather_info.setText("No weather (no city).")

    def _check_weather(self) -> None:
        city = self.c.settings["weather_city"]
        if not city:
            self.weather_info.setText("Type your city first.")
            return
        self.weather_info.setText(f"Looking at the sky over {city}...")

        def done(ok: bool, value) -> None:
            try:
                self.weather_info.setText(f"{value.emoji} {value.line()}" if ok else str(value))
            except RuntimeError:
                pass  # (the window was closed meanwhile)

        self.c.day.city_changed()
        self.c.day.fetch_weather(city, done)

    def _toggle_watching(self) -> None:
        self.c.toggle_watching()
        self.refresh()

    # ----------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Show the current settings (called when opened, and after anything changes)."""
        from . import autostart

        c, s = self.c, self.c.settings
        values = {key: s[key] for key in self._switches if key in s}
        values["autostart"] = autostart.is_enabled() if "autostart" in self._switches else False
        for key, switch in self._switches.items():
            switch.blockSignals(True)
            switch.setChecked(bool(values.get(key)))
            switch.blockSignals(False)
            switch.update()
        for combo, value in ((self.size, s["size"]), (self.voice, s["voice"]), (self.voice_lines, s["voice_lines"]),
                             (self.focus_length, s["focus_minutes"]), (self.wrapup_hour, s["wrapup_hour"]),
                             (self.country, s["country"]), (self.payday, s["payday"])):
            combo.setCurrentIndex(max(0, combo.findData(value)))
        if self.focus_length.findData(s["focus_minutes"]) < 0:
            self.focus_length.addItem(f"{s['focus_minutes']} minutes", s["focus_minutes"])
            self.focus_length.setCurrentIndex(self.focus_length.count() - 1)
        for edit, value in ((self.birthday, _pretty_birthday(s["birthday"])), (self.region, s["region"]),
                            (self.city, s["weather_city"])):
            if not edit.hasFocus():
                edit.setText(value)
        self._refresh_fun()
        focus = c.day.focus
        self.focus_button.setText("Start focusing" if focus is None else
                                  f"Stop ({focus.clock(time.monotonic())} left)" if focus.focusing else "End the break")
        if not s["weather_city"]:
            self.weather_info.setText("Type your city to get the weather in the morning.")
        elif c.day.weather is None and not self.weather_info.text():
            self.weather_info.setText("Not checked yet: press Check now.")
        elif c.day.weather is not None:
            w = c.day.weather
            self.weather_info.setText(f"{w.emoji} {w.place}: {w.temperature:.0f}°, {w.words} (up to {w.high:.0f}°)")

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


def _pretty_birthday(value: str) -> str:
    """"12-31" -> "31 Dec"."""
    if not value:
        return ""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month, day = (int(n) for n in value.split("-"))
    return f"{day} {months[month - 1]}"
