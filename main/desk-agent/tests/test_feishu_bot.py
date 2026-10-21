import unittest
from unittest.mock import patch

from api import feishu_bot
from api.desk_agent_client import AgentSession


class FeishuBotReplyTests(unittest.TestCase):
    def setUp(self):
        self.original_reply_mode = feishu_bot.REPLY_MODE
        self.original_mention_sender = feishu_bot.WEBHOOK_MENTION_SENDER

    def tearDown(self):
        feishu_bot.REPLY_MODE = self.original_reply_mode
        feishu_bot.WEBHOOK_MENTION_SENDER = self.original_mention_sender

    def test_numbered_selection_is_forwarded_without_email_rewrite(self):
        session = AgentSession("test-open-id")
        session.selection_candidates = ["10.18.pdf", "10.12.pdf"]

        self.assertEqual(session._normalize_selection("1"), "1")
        self.assertEqual(session._normalize_selection("2"), "2")

    @patch("api.feishu_bot.reply_feishu_text_with_oauth")
    @patch("api.feishu_bot.send_feishu_webhook_text")
    @patch("api.feishu_bot.is_webhook_configured", return_value=True)
    def test_auto_mode_prefers_configured_webhook(
        self,
        _configured,
        send_webhook,
        send_oauth,
    ):
        feishu_bot.REPLY_MODE = "auto"
        feishu_bot.WEBHOOK_MENTION_SENDER = True

        feishu_bot.reply_agent_result("om_test", "ou_test", "执行完成")

        send_webhook.assert_called_once_with(
            "执行完成",
            mention_open_id="ou_test",
        )
        send_oauth.assert_not_called()

    @patch("api.feishu_bot.reply_feishu_text_with_oauth")
    @patch("api.feishu_bot.send_feishu_webhook_text")
    @patch("api.feishu_bot.is_webhook_configured", return_value=False)
    def test_auto_mode_falls_back_to_oauth_without_webhook(
        self,
        _configured,
        send_webhook,
        send_oauth,
    ):
        feishu_bot.REPLY_MODE = "auto"

        feishu_bot.reply_agent_result("om_test", "ou_test", "执行完成")

        send_oauth.assert_called_once_with("om_test", "执行完成")
        send_webhook.assert_not_called()


if __name__ == "__main__":
    unittest.main()
