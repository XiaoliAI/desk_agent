import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import SentenceType


class StubTTS(TTSProviderBase):
    def __init__(self, audio=None, error=None, text_only=False):
        super().__init__({"output_dir": "tmp/"}, delete_audio_file=True)
        self.audio = audio
        self.error = error
        self.current_sentence_id = "sentence-1"
        self.conn = SimpleNamespace(
            features={"text_only": text_only},
            sample_rate=24000,
            sentence_id="sentence-1",
        )
        self.opus_encoder = object()

    async def text_to_speak(self, text, output_file):
        if self.error:
            raise self.error
        return self.audio


class TtsTextDeliveryTests(unittest.TestCase):
    @staticmethod
    def _queue_items(tts):
        items = []
        while not tts.tts_audio_queue.empty():
            items.append(tts.tts_audio_queue.get_nowait())
        return items

    def test_text_is_queued_when_synthesis_fails(self):
        tts = StubTTS(error=RuntimeError("service unavailable"))

        tts.to_tts_stream("已找到五个文件")

        items = self._queue_items(tts)
        self.assertEqual(len(items), 1)
        sentence_type, audio, text, sentence_id = items[0]
        self.assertEqual(sentence_type, SentenceType.FIRST)
        self.assertIsNone(audio)
        self.assertEqual(text, "已找到五个文件")
        self.assertEqual(sentence_id, "sentence-1")

    @patch("core.providers.tts.base.audio_bytes_to_data_stream")
    def test_text_is_queued_once_when_synthesis_succeeds(self, convert):
        tts = StubTTS(audio=b"audio")

        tts.to_tts_stream("正常回复")

        convert.assert_called_once()
        items = self._queue_items(tts)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][2], "正常回复")

    def test_text_only_client_receives_text_once(self):
        tts = StubTTS(text_only=True)

        tts.to_tts_stream("纯文本回复")

        items = self._queue_items(tts)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][2], "纯文本回复")


if __name__ == "__main__":
    unittest.main()
