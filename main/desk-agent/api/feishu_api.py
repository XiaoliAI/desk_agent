import json
import threading
import time
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import requests

from api.config import get_config_value, get_feishu_config


FEISHU_CONFIG = get_feishu_config()
APP_ID = get_config_value(FEISHU_CONFIG, "app_id", "FEISHU_APP_ID")
APP_SECRET = get_config_value(FEISHU_CONFIG, "app_secret", "FEISHU_APP_SECRET")
OPEN_API_BASE_URL = "https://open.feishu.cn/open-apis"
TOKEN_URL = "https://accounts.feishu.cn/oauth/v3/token"
TOKEN_SCOPE = get_config_value(
    FEISHU_CONFIG,
    "oauth_scope",
    "FEISHU_OAUTH_SCOPE",
    "im:message:send_as_bot",
)
_token_lock = threading.Lock()
_cached_token = ""
_token_expires_at = 0.0


def _response_data(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as error:
        raise RuntimeError(
            f"Feishu API returned invalid JSON (HTTP {response.status_code})"
        ) from error
    if not isinstance(data, dict):
        raise RuntimeError("Feishu API returned an invalid response object")
    return data


def get_tenant_access_token() -> str:
    global _cached_token, _token_expires_at

    if not APP_ID or not APP_SECRET:
        raise RuntimeError("飞书 App ID 或 App Secret 未配置")

    with _token_lock:
        now = time.monotonic()
        if _cached_token and now < _token_expires_at:
            return _cached_token

        response = requests.post(
            TOKEN_URL,
            json={
                "grant_type": "client_credentials",
                "client_id": APP_ID,
                "client_secret": APP_SECRET,
                "scope": TOKEN_SCOPE,
            },
            timeout=15,
        )
        data = _response_data(response)
        code = data.get("code", 0)
        token = data.get("access_token")
        if response.status_code >= 400 or code not in (0, "0") or not token:
            detail = data.get("error_description") or data.get("msg") or data.get("error")
            raise RuntimeError(
                f"获取飞书 tenant_access_token 失败：code={code}, {detail or response.status_code}"
            )

        expires_in = max(int(data.get("expires_in", 0)), 0)
        _cached_token = str(token)
        _token_expires_at = time.monotonic() + max(expires_in - 120, 0)
        return _cached_token


def reply_feishu_text(message_id: str, text: str) -> None:
    token = get_tenant_access_token()
    response = requests.post(
        f"{OPEN_API_BASE_URL}/im/v1/messages/{quote(message_id, safe='')}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
            "uuid": str(uuid5(NAMESPACE_URL, f"desk-agent:{message_id}")),
        },
        timeout=15,
    )
    data = _response_data(response)
    code = data.get("code", 0)
    if response.status_code >= 400 or code not in (0, "0"):
        detail = data.get("msg") or data.get("error_description") or response.status_code
        raise RuntimeError(f"飞书消息回复失败：code={code}, {detail}")
