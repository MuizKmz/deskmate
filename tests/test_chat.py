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

    def test_reminder_tags_are_taken_out_of_the_reply(self):
        self.fake.reply = '[happy] Okay~ I\'ll tell you at 3! <remind when="3pm">the meeting</remind>'
        session = self.session()
        self.assertEqual(session.ask("remind me at 3pm about the meeting"), ("happy", "Okay~ I'll tell you at 3!"))
        self.assertEqual(session.last_reminders, [("3pm", "the meeting")])
        self.assertIn('<remind when="3pm">', session.history[-1]["content"])  # so she knows it's set
        self.assertIn("<remind", C.persona_prompt({}, "Yuki"))  # the real prompt tells her how
        self.fake.reply = "[talk] Nothing to remind."
        session.ask("hi")
        self.assertEqual(session.last_reminders, [])
        self.assertEqual(C.parse_reply('[happy] ok <remind when="3pm">cut off'), ("happy", "ok cut off"))

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
        self.assertEqual(set(C.OFFLINE_LINES), {"no_key", "auth", "quota", "model", "vision", "offline", "timeout",
                                                 "server"})

    def test_claude(self):
        session = self.session(provider="claude", model="")
        self.fake.reply = "[blush] Ehehe~ hi!"
        self.assertEqual(session.ask("hello", "It is morning."), ("blush", "Ehehe~ hi!"))
        self.assertEqual(session.config.model, "claude-haiku-5-5")  # picked: quick and cheap
        sent, headers = self.fake.requests[-1], self.fake.headers[-1]
        self.assertIn("You are Testy.", sent["system"])  # the persona goes in "system"...
        self.assertIn("It is morning.", sent["system"])
        self.assertEqual(sent["messages"], [{"role": "user", "content": "hello"}])  # ...not in the messages
        self.assertGreater(sent["max_tokens"], 0)
        self.assertEqual(headers.get("x-api-key"), self.fake.key)  # Anthropic's key header, not "Bearer"
        self.assertIsNone(headers.get("authorization"))
        session.ask("again")
        self.assertEqual([m["role"] for m in self.fake.requests[-1]["messages"]], ["user", "assistant", "user"])
        with self.assertRaises(C.ChatError) as caught:
            self.session(provider="claude", api_key="sk-ant-wrong").ask("hi")
        self.assertEqual(caught.exception.kind, "auth")

    def test_picking_a_claude_model(self):
        models = ["claude-3-5-haiku-20241022", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
        self.assertEqual(C.pick_model(models, "claude"), "claude-haiku-5-5")
        self.assertEqual(C.pick_model(["claude-sonnet-5-5", "claude-opus-5-5"], "claude"), "claude-sonnet-5-5")
        self.assertEqual(C.pick_model(["claude-3-5-haiku-20241022"], "claude"), "claude-3-5-haiku-20241022")
        self.assertEqual(C.ChatConfig(provider="claude").url, C.CLAUDE_URL)
        self.assertTrue(C.ChatConfig(provider="claude").needs_key)

    LOOK_REPLY = ("[surprised] Ah, a typo on line 3~ you wrote pritn!\n---\n"
                  "1. Click line 3.\n2. Change pritn to print:\n```python\n    print('hi')\n```\nThen run it again!")

    def test_while_she_watches_your_messages_include_the_screen(self):
        session = self.session()
        shot = C.Snapshot(b"\xff\xd8fake-jpeg", 800, 450)
        self.fake.reply = self.LOOK_REPLY
        mood, reply = session.ask("", "Right now they're on: VS Code: main.py", shot)  # Enter = "have a look"
        self.assertEqual((mood, reply), ("surprised", "Ah, a typo on line 3~ you wrote pritn!"))
        self.assertIn("```python\n    print('hi')\n```", session.last_details)  # code keeps its indent
        sent = self.fake.requests[-1]
        self.assertIn("watch their screen", sent["messages"][0]["content"])  # the watching instructions
        self.assertIn("VS Code: main.py", sent["messages"][0]["content"])
        text, picture = sent["messages"][-1]["content"]
        self.assertEqual(text, {"type": "text", "text": C.LOOK_TEXT})
        self.assertEqual(picture["image_url"]["url"], "data:image/jpeg;base64,/9hmYWtlLWpwZWc=")
        # The chat log gets the short line and the help; the picture itself is never stored.
        user, her = session.transcript()
        self.assertTrue(user["image"])
        self.assertEqual(her["text"], reply)
        self.assertTrue(her["details"].startswith("1. Click line 3."))
        self.assertNotIn("/9hmYWtl", (self.tmp / "chat.json").read_text(encoding="utf-8"))
        # Just chatting while she watches: a normal reply, no help section.
        self.fake.reply = "[happy] Ehehe, you're welcome~"
        self.assertEqual(session.ask("thanks!", "", shot), ("happy", "Ehehe, you're welcome~"))
        self.assertEqual(session.last_details, "")
        self.assertEqual(self.fake.requests[-1]["messages"][1]["content"],
                         "(my screen was attached) " + C.LOOK_TEXT)  # earlier turns: text only
        # Not watching: plain chat, no picture, no watching instructions.
        session.ask("bye")
        self.assertEqual(self.fake.requests[-1]["messages"][-1]["content"], "bye")
        self.assertNotIn("watch their screen", self.fake.requests[-1]["messages"][0]["content"])

    def test_buddy_reactions(self):
        session = self.session()
        self.fake.reply = "[happy] Ooh, lo-fi beats~ is this your study playlist?"
        said = session.react("Chrome: lofi hip hop radio - YouTube", "It is evening.", C.Snapshot(b"x", 1, 1))
        self.assertEqual(said, ("happy", "Ooh, lo-fi beats~ is this your study playlist?"))
        sent = self.fake.requests[-1]
        self.assertIn("buddy", sent["messages"][0]["content"])
        self.assertIn("[skip]", sent["messages"][0]["content"])
        self.assertIn("lofi hip hop radio", sent["messages"][-1]["content"][0]["text"])
        self.assertEqual(session.history, [])  # not saved until it's really shown...
        session.remember_reaction("Chrome: lofi hip hop radio - YouTube", *said)
        # ...then it's part of today's chat, so you can answer her ("yes!") and she knows what about.
        self.assertEqual(session.transcript()[-1]["about"], "Chrome: lofi hip hop radio - YouTube")
        self.assertEqual(len(session.transcript()), 1)  # her glance isn't shown as something you said
        self.fake.reply = "[happy] Yay, same~"
        session.ask("yes I love it")
        self.assertIn("lofi", self.fake.requests[-1]["messages"][1]["content"])
        # She asks something: answers you could tap come along (taken out of her line).
        self.fake.reply = "[happy] Ooh, is this your study playlist? <replies>Yes, I love it!|Just background</replies>"
        self.assertEqual(session.react("Chrome: lofi - YouTube"), ("happy", "Ooh, is this your study playlist?"))
        self.assertEqual(session.last_replies, ["Yes, I love it!", "Just background"])
        self.fake.reply = "[happy] Ado now? Villain hits hard~"
        session.react("Spotify: Ado - Villain", music=True)
        self.assertEqual(session.last_replies, ["Yes!", "Not really"])  # a question, but no answers given
        sent = self.fake.requests[-1]["messages"]
        self.assertIn("a new song started playing", sent[0]["content"])
        self.assertEqual(sent[-1]["content"], "(Now playing: Spotify: Ado - Villain)")
        self.fake.reply = "[happy] Nice spreadsheet."
        session.react("Excel: budget.xlsx")
        self.assertEqual(session.last_replies, [])
        self.assertEqual(C.extract_replies("Hi <replies>a|b|c|d</replies>"), ("Hi", ["a", "b", "c"]))
        self.assertEqual(C.extract_replies("Hi <replies>Yes!|"), ("Hi", ["Yes!"]))  # cut off: still fine
        # Nothing worth saying: she stays quiet and nothing is added.
        self.fake.reply = "[skip]"
        self.assertIsNone(session.react("Excel: budget.xlsx"))
        self.assertEqual(len(session.history), 4)  # only the remembered ones
        self.assertIsInstance(self.fake.requests[-1]["messages"][-1]["content"], str)  # no picture: text only

    def test_claude_looks_too(self):
        session = self.session(provider="claude", model="claude-haiku-5-5")
        self.fake.reply = self.LOOK_REPLY
        self.assertEqual(session.ask("what's wrong?", "", C.Snapshot(b"\xff\xd8fake-jpeg", 800, 450))[0], "surprised")
        sent = self.fake.requests[-1]
        picture, text = sent["messages"][-1]["content"]  # Anthropic: the picture first, then the question
        self.assertEqual(picture, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                                "data": "/9hmYWtlLWpwZWc="}})
        self.assertEqual(text, {"type": "text", "text": "what's wrong?"})
        self.assertGreaterEqual(sent["max_tokens"], 1000)  # room for steps and an example
        self.assertIn("watch their screen", sent["system"])

    def test_a_model_that_cant_see(self):
        session = self.session()
        self.fake.status, self.fake.error = 400, "Invalid content type. image_url is only supported by certain models."
        with self.assertRaises(C.ChatError) as caught:
            session.ask("look", "", C.Snapshot(b"x", 1, 1))
        self.assertEqual(caught.exception.kind, "vision")

    def test_splitting_a_look_reply(self):
        self.assertEqual(C.split_look_reply("[happy] Looks fine~"), ("[happy] Looks fine~", ""))
        head, details = C.split_look_reply("[talk] Hmm.\n  ---  \n## Steps\n**Do** this.\n\n\n\nThen that.")
        self.assertEqual((head, details), ("[talk] Hmm.", "Steps\nDo this.\n\nThen that."))
        long = "[talk] " + "This part is long. " * 30  # forgot the --- : the log still gets all of it
        head, details = C.split_look_reply(long)
        self.assertEqual(head, long.strip())
        self.assertTrue(details.startswith("This part is long."))
        self.assertNotIn("[talk]", details)
        cut = C.clean_details("```\n" + "x = 1\n" * 600)
        self.assertLessEqual(len(cut), C.MAX_DETAILS_CHARS + 10)
        self.assertEqual(cut.count("```") % 2, 0)  # a cut code block is still closed

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
            C.save_key(path, "sk-ant-zyxwvutsrq", "anthropic")  # a second key...
            self.assertEqual(C.load_key(path), "sk-abcdefghijklmnop")  # ...doesn't erase the first
            self.assertEqual(C.load_key(path, "anthropic"), "sk-ant-zyxwvutsrq")
            with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-env"}, clear=True):
                self.assertEqual(C.load_key(Path(home) / "none.json", "anthropic"), "sk-ant-env")
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
