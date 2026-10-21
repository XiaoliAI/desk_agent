import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import Mock, patch

from api import feishu_webhook


class FeishuWebhookTests(unittest.TestCase):
    def setUp(self):
        feishu_webhook.WEBHOOK_URL = "https://example.test/hook/test"
        feishu_webhook.WEBHOOK_SECRET = "test-secret"

    def test_generate_sign_matches_official_algorithm(self):
        timestamp = 1599360473
        key = f"{timestamp}\ntest-secret".encode("utf-8")
        expected = base64.b64encode(
            hmac.new(key, digestmod=hashlib.sha256).digest()
        ).decode("utf-8")

        self.assertEqual(
            feishu_webhook.generate_webhook_sign(timestamp, "test-secret"),
            expected,
        )

    @patch("api.feishu_webhook.time.time", return_value=1599360473)
    @patch("api.feishu_webhook.requests.post")
    def test_send_text_uses_signed_webhook(self, post, _time):
        post.return_value = Mock(
            status_code=200,
            json=lambda: {"code": 0, "msg": "success"},
        )

        feishu_webhook.send_feishu_webhook_text(
            "任务完成",
            mention_open_id="ou_test",
        )

        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["msg_type"], "text")
        self.assertIn('<at user_id="ou_test">', payload["content"]["text"])
        self.assertEqual(payload["timestamp"], "1599360473")
        self.assertTrue(payload["sign"])

    @patch("api.feishu_webhook.requests.post")
    def test_webhook_error_is_reported(self, post):
        post.return_value = Mock(
            status_code=200,
            json=lambda: {"code": 19021, "msg": "sign match fail"},
        )

        with self.assertRaisesRegex(RuntimeError, "19021"):
            feishu_webhook.send_feishu_webhook_text("任务失败")

    def test_long_text_is_limited_without_cutting_utf8(self):
        result = feishu_webhook._truncate_utf8("中" * 100, max_bytes=64)

        result.encode("utf-8")
        self.assertIn("已截断", result)
        self.assertLessEqual(len(result.encode("utf-8")), 64)


if __name__ == "__main__":
    unittest.main()
