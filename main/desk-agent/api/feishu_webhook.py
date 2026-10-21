import base64
import hashlib
import hmac
import time
from typing import Any

import requests

from api.config import get_config_value, get_feishu_config


FEISHU_CONFIG = get_feishu_config()
WEBHOOK_URL = get_config_value(
    FEISHU_CONFIG,
    "webhook_url",
    "FEISHU_WEBHOOK_URL",
)
WEBHOOK_SECRET = get_config_value(
    FEISHU_CONFIG,
    "webhook_secret",
    "FEISHU_WEBHOOK_SECRET",
)
WEBHOOK_TIMEOUT_SECONDS = 15
MAX_TEXT_BYTES = 18 * 1024


def is_webhook_configured() -> bool:
    return bool(WEBHOOK_URL)


def generate_webhook_sign(timestamp: int, secret: str) -> str:
    """Generate a signature using Feishu's custom-bot algorithm."""
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _truncate_utf8(text: str, max_bytes: int = MAX_TEXT_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    suffix = "\n\n[回复内容过长，已截断]"
    suffix_bytes = suffix.encode("utf-8")
    body = encoded[: max(max_bytes - len(suffix_bytes), 0)]
    while body:
        try:
            return body.decode("utf-8") + suffix
        except UnicodeDecodeError:
            body = body[:-1]
    return suffix.strip()


def _response_data(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as error:
        raise RuntimeError(
            f"飞书 Webhook 返回了无效响应（HTTP {response.status_code}）"
        ) from error
    if not isinstance(data, dict):
        raise RuntimeError("飞书 Webhook 返回格式错误")
    return data


def send_feishu_webhook_text(text: str, mention_open_id: str = "") -> None:
    if not WEBHOOK_URL:
        raise RuntimeError("飞书自定义机器人 webhook_url 未配置")

    content = str(text or "").strip()
    if not content:
        return
    if mention_open_id:
        content = f'<at user_id="{mention_open_id}">用户</at> {content}'

    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": _truncate_utf8(content)},
    }
    if WEBHOOK_SECRET:
        timestamp = int(time.time())
        payload.update(
            {
                "timestamp": str(timestamp),
                "sign": generate_webhook_sign(timestamp, WEBHOOK_SECRET),
            }
        )

    response = requests.post(
        WEBHOOK_URL,
        json=payload,
        timeout=WEBHOOK_TIMEOUT_SECONDS,
    )
    data = _response_data(response)
    code = data.get("code", data.get("StatusCode", 0))
    if response.status_code >= 400 or code not in (0, "0", None):
        detail = data.get("msg") or data.get("StatusMessage") or response.status_code
        raise RuntimeError(f"飞书 Webhook 回复失败：code={code}, {detail}")


def main() -> None:
    if not is_webhook_configured():
        raise RuntimeError(
            "请先在 data/.config.yaml 配置 plugins.feishu.webhook_url"
        )
    send_feishu_webhook_text("Desk Agent 飞书 Webhook 回复通道测试成功")
    print("飞书 Webhook 测试消息发送成功")


if __name__ == "__main__":
    main()
