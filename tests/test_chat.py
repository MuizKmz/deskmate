import os
import random
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from deskmate import brain as B
from deskmate import chat as C
from deskmate.brain import Brain
from tests.fake_openai import FakeOpenAI


class ModelPickTests(unittest.TestCase):
    def test_picks_the_newest_mini_chat_model(self):
        models = ["gpt-4o-mini-transcribe", "text-embedding-3-small", "gpt-5-mini", "gpt-5.4-mini",
                  "gpt-5.4-mini-2026-03-01", "gpt-6.1-sol", "o4-mini", "dall-e-3"]
        self.assertEqual(C.pick_model(models), "gpt-5.4-mini")

    def test_falls_back_when_there_is_no_mini(self):
        self.assertEqual(C.pick_model(["gpt-6-luna", "gpt-6.1-sol"]), "gpt-6-luna")
        self.assertEqual(C.pick_model(["gpt-6.1-sol", "whisper-1"]), "gpt-6.1-sol")
        self.assertEqual(C.pick_model([]), "")
        self.assertEqual(C.pick_model(["llama3.2:latest"], "ollama"), "llama3.2:latest")


class ReplyTests(unittest.TestCase):
    def test_mood_tag_is_split_off(self):
        self.assertEqual(C.parse_reply("[blush] W-what? Thanks..."), ("blush", "W-what? Thanks..."))
        self.assertEqual(C.parse_reply("  [HAPPY]  Yay~"), ("happy", "Yay~"))

    def test_unknown_or_missing_mood_means_talk(self):
        self.assertEqual(C.parse_reply("[angry] Hmph."), ("talk", "Hmph."))
        self.assertEqual(C.parse_reply("Just words"), ("talk", "Just words"))
        self.assertEqual(C.parse_reply(""), ("talk", "..."))

    def test_markdown_and_long_answers_are_tidied_for_the_bubble(self):
        mood, text = C.parse_reply("[talk] **Sure!** Here's `code`")
        self.assertEqual(text, "Sure! Here's code")
        long = "[talk] " + "This is a sentence. " * 40
        _, text = C.parse_reply(long)
        self.assertLessEqual(len(text), C.MAX_REPLY_CHARS)
        self.assertTrue(text.endswith("."))

    def test_persona_and_situation(self):
        prompt = C.persona_prompt({"personality": "sleepy", "persona": "You love tea.", "catchphrase": "Mmh"}, "Yuki")
        for bit in ("You are Yuki", "sleepy", "You love tea.", "Mmh", "[happy]"):
            self.assertIn(bit, prompt)
        text = C.situation(datetime(2026, 10, 30, 1, 30), "sleepy", 95)
        self.assertIn("late at night", text)
        self.assertIn("95 minutes", text)
        self.assertNotIn("minutes", C.situation(datetime(2026, 10, 30, 9), "idle", 10))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOpenAI()
        self.addCleanup(self.fake.close)
        self.tmp = Path(tempfile.mkdtemp())
        self.day = date(2026, 10, 30)

    def session(self, **config):
        settings = dict(provider="openai", model="gpt-5.4-mini", api_key=self.fake.key, base_url=self.fake.url)
        settings.update(config)
        return C.ChatSession(C.ChatConfig(**settings), "You are Testy.", path=self.tmp / "chat.json",
                             today=lambda: self.day)

    def test_ask_sends_persona_context_and_history(self):
        session = self.session()
        self.assertEqual(session.ask("hello", "It is morning."), ("happy", "Ehehe, hi there~"))
        sent = self.fake.requests[-1]
        self.assertEqual(sent["model"], "gpt-5.4-mini")
        self.assertEqual(sent["messages"][0]["role"], "system")
        self.assertIn("You are Testy.", sent["messages"][0]["content"])
        self.assertIn("It is morning.", sent["messages"][0]["content"])
        self.assertEqual(sent["messages"][-1], {"role": "user", "content": "hello"})
        self.fake.reply = "[pouty] You forgot already?"
        session.ask("what did I say?")
        self.assertEqual([m["content"] for m in self.fake.requests[-1]["messages"][1:3]],
                         ["hello", "[happy] Ehehe, hi there~"])

    def test_she_remembers_today_but_not_yesterday(self):
        self.session().ask("my meeting is at 3")
        again = self.session()  # e.g. after a restart
        self.assertEqual(again.history[0]["content"], "my meeting is at 3")
        self.day = date(2026, 10, 31)
        self.assertEqual(self.session().history, [])
        again.forget()
        self.assertEqual(again.history, [])

    def test_a_new_day_starts_fresh_even_without_a_restart(self):
        session = self.session()
        session.ask("hi")
        self.day = date(2026, 10, 31)
        self.assertEqual(len(session.messages("morning!")), 2)  # system + this message only

    def test_model_is_picked_automatically_when_empty(self):
        session = self.session(model="")
        session.ask("hi")
        self.assertEqual(session.config.model, "gpt-5.4-mini")
        self.assertEqual(self.fake.requests[-1]["model"], "gpt-5.4-mini")

    def test_errors_become_friendly_kinds(self):
        with self.assertRaises(C.ChatError) as caught:
            self.session(api_key="").ask("hi")
        self.assertEqual(caught.exception.kind, "no_key")
        with self.assertRaises(C.ChatError) as caught:
            self.session(api_key="sk-wrong-key-000").ask("hi")
        self.assertEqual(caught.exception.kind, "auth")
        self.fake.status = 429
        with self.assertRaises(C.ChatError) as caught:
            self.session().ask("hi")
        self.assertEqual(caught.exception.kind, "quota")
        with self.assertRaises(C.ChatError) as caught:
            self.session(base_url="http://127.0.0.1:9/v1").ask("hi")  # nothing listens there
        self.assertEqual(caught.exception.kind, "offline")
        self.assertEqual(set(C.OFFLINE_LINES), {"no_key", "auth", "quota", "model", "offline", "timeout", "server"})

    def test_ollama_needs_no_key(self):
        config = C.ChatConfig(provider="ollama")
        self.assertFalse(config.needs_key)
        self.assertEqual(config.url, C.OLLAMA_URL)


class KeyTests(unittest.TestCase):
    def test_key_is_saved_apart_and_read_back(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / "secrets.json"
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-environment"}):
                self.assertEqual(C.load_key(path), "sk-from-environment")
            C.save_key(path, "  sk-abcdefghijklmnop  ")
            self.assertEqual(C.load_key(path), "sk-abcdefghijklmnop")
            self.assertEqual(C.mask("sk-abcdefghijklmnop"), "sk-...mnop")
            path.write_text("{broken", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(C.load_key(path), "")


class BrainChatTests(unittest.TestCase):
    def make(self):
        lines = {key: [f"<{key}>"] for key in ("random", "water", "break", "wander", "wake", "ignored")}
        return Brain(lines, now=0.0, rng=random.Random(2), wallclock=lambda: datetime(2026, 10, 30, 12))

    def test_chatting_wakes_her_and_ends_a_pout(self):
        brain = self.make()
        brain.set_manual_sleep(0, True)
        brain.on_chat_sent(5)
        self.assertFalse(brain.asleep)
        brain.base = "pouty"
        brain.on_chat_sent(6)
        self.assertEqual(brain.base, "idle")

    def test_reply_shows_with_its_mood(self):
        brain = self.make()
        brain.drain_speech()
        brain.on_chat_reply(10, "blush", "W-what?")
        self.assertEqual([s.text for s in brain.drain_speech()], ["W-what?"])
        self.assertEqual(brain.expression(10.5), "blush")

    def test_no_random_chatter_or_strolls_while_you_chat(self):
        brain = self.make()
        brain.on_chat_reply(1, "talk", "hi")
        brain.drain_speech()
        for t in range(1, 80, 5):
            brain.last_interaction = t
            brain.tick(t, user_idle=1)
        self.assertEqual(brain.drain_speech(), [])
        self.assertNotIn("wander", brain.drain_animations())


if __name__ == "__main__":
    unittest.main()
