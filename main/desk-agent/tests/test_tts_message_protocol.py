import asyncio
import json
import unittest
from types import SimpleNamespace

from core.handle.sendAudioHandle import sendAudioMessage
from core.providers.tts.dto.dto import SentenceType


class StubLogger:
    def bind(self, **_kwargs):
        return self

    def info(self, *_args, **_kwargs):
        return None


class StubWebSocket:
    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(message)


class TtsMessageProtocolTests(unittest.TestCase):
    def test_follow_up_segments_are_marked_for_append(self):
        websocket = StubWebSocket()
        connection = SimpleNamespace(
            tts=SimpleNamespace(tts_audio_first_sentence=True),
            logger=StubLogger(),
            sentence_id="sentence-1",
            session_id="session-1",
            websocket=websocket,
            calling=False,
            close_after_chat=False,
        )

        async def send_segments():
            await sendAudioMessage(
                connection,
                SentenceType.FIRST,
                None,
                "第一段",
                "sentence-1",
            )
            await sendAudioMessage(
                connection,
                SentenceType.FIRST,
                None,
                "第二段",
                "sentence-1",
            )

        asyncio.run(send_segments())

        messages = [json.loads(item) for item in websocket.messages]
        self.assertEqual(len(messages), 2)
        self.assertFalse(messages[0]["append"])
        self.assertTrue(messages[1]["append"])


if __name__ == "__main__":
    unittest.main()
