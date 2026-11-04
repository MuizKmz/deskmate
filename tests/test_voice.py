import base64
import unittest
from unittest import mock

from deskmate import voice as V
from deskmate.chat import ChatConfig
from tests.fake_openai import FakeOpenAI


def run_now(work, done):
    """Instead of a thread: do the work right away (tests only)."""
    try:
        done(True, work())
    except Exception as error:
        done(False, error)


class CleanTextTests(unittest.TestCase):
    def test_decorations_are_not_read_out(self):
        self.assertEqual(V.clean_for_speech("*yawn*... good morning~"), "yawn, good morning")
        self.assertEqual(V.clean_for_speech("Hehe~ ✨ you're back!"), "Hehe you're back!")
        self.assertEqual(V.clean_for_speech("Mmh… okay"), "Mmh, okay")
        self.assertEqual(V.clean_for_speech("~~~"), "")
        self.assertEqual(len(V.clean_for_speech("a" * 1000)), V.MAX_SPOKEN)


class WindowsVoiceTests(unittest.TestCase):
    def test_the_hidden_powershell_reads_text_from_its_input(self):
        command = V.powershell_command()
        script = base64.b64decode(command[-1]).decode("utf-16-le")
        self.assertIn("SpeechSynthesizer", script)
        self.assertIn("[Console]::In.ReadToEnd()", script)  # the text is never put inside the command

    def test_speak_and_stop(self):
        popen = mock.MagicMock()
        process = popen.return_value
        process.poll.return_value = None  # still talking
        windows = V.WindowsVoice(popen=popen)
        windows.speak("hello")
        process.stdin.write.assert_called_once_with(b"\nhello")  # no name: the first female voice
        windows.speak("again")  # a new line stops the old one first
        process.kill.assert_called_once()
        windows.stop()
        self.assertEqual(process.kill.call_count, 2)
        windows.name = "Microsoft Haruka Desktop"
        windows.speak("konnichiwa")
        process.stdin.write.assert_called_with("Microsoft Haruka Desktop\nkonnichiwa".encode("utf-8"))

    def test_listing_the_installed_voices(self):
        script = base64.b64decode(V.powershell_command(V._PS_LIST)[-1]).decode("utf-16-le")
        self.assertIn("GetInstalledVoices", script)

        def answers(stdout):
            return lambda *_args, **_kw: mock.Mock(stdout=stdout.encode("utf-8"))

        voices = V.list_windows_voices(answers('[{"name":"Microsoft Zira Desktop","gender":"Female","culture":"en-US"},'
                                               '{"name":"Microsoft David Desktop","gender":"Male","culture":"en-US"}]'))
        self.assertEqual([v["name"] for v in voices], ["Microsoft Zira Desktop", "Microsoft David Desktop"])
        self.assertEqual(V.describe_windows_voice(voices[0]), "Microsoft Zira Desktop (en-US, female)")
        one = V.list_windows_voices(answers('{"name":"Microsoft Haruka Desktop","gender":"Female","culture":"ja-JP"}'))
        self.assertEqual([v["name"] for v in one], ["Microsoft Haruka Desktop"])  # PowerShell's lone-object JSON
        self.assertEqual(V.list_windows_voices(answers("not json")), [])

        def broken(*_args, **_kw):
            raise OSError("no powershell")

        self.assertEqual(V.list_windows_voices(broken), [])


class OpenAIVoiceTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOpenAI()
        self.addCleanup(self.fake.close)
        self.config = ChatConfig(provider="openai", api_key=self.fake.key, base_url=self.fake.url)

    def test_picks_a_voice_model_and_gets_a_wav_clip(self):
        natural = V.OpenAIVoice(self.config, voice="shimmer")
        self.assertEqual(natural.synthesize("hi there"), FakeOpenAI.WAV)
        self.assertEqual(natural.model, "gpt-4o-mini-tts")
        sent = self.fake.requests[-1]
        self.assertEqual((sent["voice"], sent["input"], sent["response_format"]), ("shimmer", "hi there", "wav"))
        self.assertIn("softly", sent["instructions"])  # newer models are told how she talks

    def test_older_models_get_no_style_instructions(self):
        natural = V.OpenAIVoice(self.config, model="tts-1", voice="not-a-voice")
        natural.synthesize("hi")
        self.assertNotIn("instructions", self.fake.requests[-1])
        self.assertEqual(self.fake.requests[-1]["voice"], "nova")  # unknown voice names fall back

    def test_your_own_server_like_kokoro(self):
        self.fake.require_key = False  # it runs on your PC: no key
        self.fake.MODELS = ["kokoro"]
        own = ChatConfig(provider="local", base_url=self.fake.url)
        natural = V.OpenAIVoice(own, voice="jf_alpha")
        self.assertEqual(natural.synthesize("konnichiwa"), FakeOpenAI.WAV)
        sent, headers = self.fake.requests[-1], self.fake.headers[-1]
        self.assertEqual((sent["model"], sent["voice"]), ("kokoro", "jf_alpha"))
        self.assertNotIn("instructions", sent)  # OpenAI-only extra
        self.assertIs(sent["stream"], False)  # one whole clip, not a stream
        self.assertNotIn("authorization", headers)
        self.assertEqual(V.list_voices(own), ["af_bella", "af_heart", "jf_alpha"])
        self.assertEqual(V.list_voices(self.config), list(V.OPENAI_VOICES))
        self.assertEqual(V.OpenAIVoice(own, voice="nova").voice, V.OWN_SERVER_VOICE)  # an OpenAI name: not here
        self.assertEqual(V.OpenAIVoice(self.config, voice="af_bella").voice, "nova")   # and the other way round

    def test_clips_are_checked_and_streamed_wavs_fixed(self):
        import struct

        good = FakeOpenAI.WAV
        self.assertEqual(V.fix_wav(good), good)
        streamed = bytearray(good)
        struct.pack_into("<I", streamed, 4, 0xFFFFFFFF)   # "unknown" sizes, like a streamed WAV
        struct.pack_into("<I", streamed, 40, 0xFFFFFFFF)
        fixed = V.fix_wav(bytes(streamed))
        self.assertEqual(struct.unpack_from("<I", fixed, 4)[0], len(good) - 8)
        self.assertEqual(struct.unpack_from("<I", fixed, 40)[0], len(good) - 44)
        raw = V.fix_wav(good[44:])  # Kokoro's "pcm": raw samples get a WAV header
        self.assertEqual((raw[:4], len(raw)), (b"RIFF", len(good)))
        silent = good[:44] + bytes(len(good) - 44)
        with self.assertRaisesRegex(ValueError, "silent"):
            V.fix_wav(silent)
        for wrong, why in ((b"", "empty"), (b"ID3\x04" + bytes(5000), "MP3"), (b'{"detail": "voice not found"}', "text"),
                           (good[:44], "empty")):
            with self.assertRaisesRegex(ValueError, why):
                V.fix_wav(wrong)

    def test_kokoro_voice_languages(self):
        self.assertEqual(V.voice_language("af_bella"), "American English")
        self.assertEqual(V.voice_language("zf_xiaoyi"), "Chinese")
        self.assertEqual(V.voice_language("jf_alpha+af_sky"), "Japanese")
        self.assertEqual(V.voice_language("nova"), "")
        self.assertEqual(V.sample_for("jf_alpha"), V.SAMPLES["Japanese"])
        self.assertEqual(V.sample_for("bm_george"), V.SAMPLES["English"])
        self.assertEqual(V.sample_for("custom"), V.SAMPLES["English"])

    def test_model_choice(self):
        self.assertEqual(V.pick_tts_model(["tts-1-hd", "tts-1", "gpt-5-mini"]), "tts-1")
        self.assertEqual(V.pick_tts_model(["gpt-5-mini"]), "")


class SpeakerTests(unittest.TestCase):
    def make(self, mode="windows", everything=False, openai_fails=False):
        windows = mock.MagicMock()
        windows.available.return_value = True
        natural = mock.MagicMock()
        if openai_fails:
            natural.synthesize.side_effect = RuntimeError("offline")
        else:
            natural.synthesize.return_value = b"RIFFwav"
        return V.Speaker(windows, natural, run_now, mode=mode, everything=everything), windows, natural

    def test_off_means_silent(self):
        speaker, windows, natural = self.make(mode="off")
        self.assertFalse(speaker.say("hi", "chat"))
        windows.speak.assert_not_called()

    def test_only_chat_replies_unless_asked_for_everything(self):
        speaker, windows, _ = self.make()
        self.assertFalse(speaker.say("Good morning~", "line"))
        self.assertTrue(speaker.say("Hehe~ hi!", "chat"))
        windows.speak.assert_called_once_with("Hehe hi!")
        speaker.everything = True
        self.assertTrue(speaker.say("Good morning~", "line"))

    def test_quiet_while_youre_in_a_call(self):
        speaker, windows, _ = self.make(everything=True)
        in_call = [True]
        speaker.hush = lambda: in_call[0]
        self.assertFalse(speaker.say("Good luck~", "chat"))
        windows.speak.assert_not_called()
        in_call[0] = False
        self.assertTrue(speaker.say("Good luck~", "chat"))

        def broken():
            raise OSError("can't tell")

        speaker.hush = broken  # can't tell? she speaks rather than going mute forever
        self.assertTrue(speaker.say("hi", "line"))
        self.assertTrue(V.Speaker(windows, None, run_now, mode="windows").everything)  # every line, by default

    def test_saying_lines_in_the_voices_language(self):
        speaker, windows, natural = self.make(mode="windows", everything=True)
        speaker.language = lambda: "Japanese"
        speaker.say("Welcome back~", "chat", spoken="おかえり～")
        windows.speak.assert_called_with("おかえり～")  # the version her brain wrote with the reply
        asked = []
        speaker.translate = lambda text, language: asked.append((text, language)) or "お水を飲んでね"
        speaker.say("Drink some water~", "line")  # a fixed line: translated
        self.assertEqual(asked, [("Drink some water", "Japanese")])
        windows.speak.assert_called_with("お水を飲んでね")

        def offline(text, language):
            raise RuntimeError("no chat brain")

        speaker.translate = offline
        speaker.say("Stretch time!", "line")
        windows.speak.assert_called_with("Stretch time!")  # can't translate: English it is
        speaker.language = lambda: ""
        speaker.say("Hi!", "chat", spoken="やあ")
        windows.speak.assert_called_with("Hi!")  # an English voice says the English
        speaker, windows, natural = self.make(mode="openai", openai_fails=True)
        speaker.language = lambda: "Japanese"
        speaker.say("Welcome back~", "chat", spoken="おかえり～")
        natural.synthesize.assert_called_with("おかえり～")
        windows.speak.assert_called_once_with("Welcome back")  # the fallback voice gets the English
        self.assertEqual(V.culture_language("ja-JP"), "Japanese")
        self.assertEqual(V.culture_language("en-US"), "")
        self.assertEqual(V.culture_language("ms-MY"), "Malay")

    def test_openai_voice_and_falling_back_to_windows(self):
        speaker, windows, natural = self.make(mode="openai")
        speaker.say("hi", "chat")
        natural.play.assert_called_once_with(b"RIFFwav")
        windows.speak.assert_not_called()
        speaker, windows, natural = self.make(mode="openai", openai_fails=True)
        speaker.say("hi", "chat")
        windows.speak.assert_called_once_with("hi")  # no internet? the Windows voice says it

    def test_a_late_clip_for_an_old_line_is_not_played(self):
        waiting = []
        windows, natural = mock.MagicMock(), mock.MagicMock()
        natural.synthesize.return_value = b"RIFF"
        speaker = V.Speaker(windows, natural, lambda work, done: waiting.append((work, done)), mode="openai")
        speaker.say("first", "chat")
        speaker.say("second", "chat")
        for work, done in waiting:  # both clips arrive now, in order
            done(True, work())
        natural.play.assert_called_once()  # only the newest line is spoken


if __name__ == "__main__":
    unittest.main()
