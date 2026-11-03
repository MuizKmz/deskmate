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
        process.stdin.write.assert_called_once_with(b"hello")
        windows.speak("again")  # a new line stops the old one first
        process.kill.assert_called_once()
        windows.stop()
        self.assertEqual(process.kill.call_count, 2)


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
