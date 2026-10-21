import json
import unittest
from unittest.mock import Mock, patch

from api import feishu_api


class FeishuApiTests(unittest.TestCase):
    def setUp(self):
        feishu_api.APP_ID = "test-app"
        feishu_api.APP_SECRET = "test-secret"
        feishu_api.TOKEN_SCOPE = "im:message:send_as_bot"
        feishu_api._cached_token = ""
        feishu_api._token_expires_at = 0

    @patch("api.feishu_api.requests.post")
    def test_token_uses_oauth_endpoint_and_caches_result(self, post):
        post.return_value = Mock(
            status_code=200,
            json=lambda: {"code": 0, "access_token": "test-token", "expires_in": 7200},
        )

        self.assertEqual(feishu_api.get_tenant_access_token(), "test-token")
        self.assertEqual(feishu_api.get_tenant_access_token(), "test-token")
        post.assert_called_once_with(
            feishu_api.TOKEN_URL,
            json={
                "grant_type": "client_credentials",
                "client_id": "test-app",
                "client_secret": "test-secret",
                "scope": "im:message:send_as_bot",
            },
            timeout=15,
        )

    @patch("api.feishu_api.requests.post")
    def test_reply_uses_bearer_token_and_reply_endpoint(self, post):
        feishu_api._cached_token = "test-token"
        feishu_api._token_expires_at = 9999999999
        post.return_value = Mock(status_code=200, json=lambda: {"code": 0})

        feishu_api.reply_feishu_text("message/1", "回复内容")

        url, = post.call_args.args
        self.assertEqual(
            url,
            f"{feishu_api.OPEN_API_BASE_URL}/im/v1/messages/message%2F1/reply",
        )
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(
            json.loads(post.call_args.kwargs["json"]["content"]),
            {"text": "回复内容"},
        )

    @patch("api.feishu_api.requests.post")
    def test_token_error_does_not_expose_response_token(self, post):
        post.return_value = Mock(
            status_code=403,
            json=lambda: {
                "code": 21001,
                "msg": "Access denied by access control policy",
                "access_token": "must-not-be-printed",
            },
        )

        with self.assertRaisesRegex(RuntimeError, "21001") as raised:
            feishu_api.get_tenant_access_token()
        self.assertNotIn("must-not-be-printed", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
