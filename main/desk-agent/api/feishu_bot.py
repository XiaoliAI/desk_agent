import json
import threading
import time
from typing import Any

from api.desk_agent_client import send_agent_command
from api.feishu_api import reply_feishu_text as reply_feishu_text_with_oauth
from api.feishu_webhook import (
    is_webhook_configured,
    send_feishu_webhook_text,
)
import lark_oapi as lark

from api.config import (
    get_config_value,
    get_feishu_config,
)


FEISHU_CONFIG = get_feishu_config()
_seen_message_ids = {}
_seen_message_lock = threading.Lock()
_message_ttl_seconds = 600
APP_ID = get_config_value(
    FEISHU_CONFIG,
    "app_id",
    "FEISHU_APP_ID",
)
APP_SECRET = get_config_value(
    FEISHU_CONFIG,
    "app_secret",
    "FEISHU_APP_SECRET",
)
REPLY_MODE = get_config_value(
    FEISHU_CONFIG,
    "reply_mode",
    "FEISHU_REPLY_MODE",
    "auto",
).lower()
WEBHOOK_MENTION_SENDER = bool(FEISHU_CONFIG.get("webhook_mention_sender", True))


def get_allowed_open_ids() -> set[str]:
    configured = FEISHU_CONFIG.get("allowed_open_ids", [])
    if not isinstance(configured, list):
        return set()
    return {
        str(item).strip()
        for item in configured
        if str(item).strip()
    }


def require_config():
    missing = []
    if not APP_ID:
        missing.append("feishu.app_id")
    if not APP_SECRET:
        missing.append("feishu.app_secret")

    if missing:
        raise RuntimeError(
            "请先在data/.config.yaml配置："
            + ", ".join(missing)
        )


def extract_text(data: Any) -> str:
    try:
        content = json.loads(data.event.message.content)
    except (AttributeError, TypeError, json.JSONDecodeError):
        return ""

    return str(content.get("text", "")).strip()


def get_sender_open_id(data: Any) -> str:
    try:
        return str(
            data.event.sender.sender_id.open_id or ""
        ).strip()
    except AttributeError:
        return ""


def get_sender_type(data: Any) -> str:
    try:
        return str(data.event.sender.sender_type or "").strip().lower()
    except AttributeError:
        return ""


def get_message_id(data: Any) -> str:
    try:
        return str(data.event.message.message_id or "").strip()
    except AttributeError:
        return ""


def claim_message(message_id: str) -> bool:
    if not message_id:
        return False

    now = time.monotonic()
    with _seen_message_lock:
        expired = [
            key
            for key, timestamp in _seen_message_ids.items()
            if now - timestamp > _message_ttl_seconds
        ]
        for key in expired:
            _seen_message_ids.pop(key, None)

        if message_id in _seen_message_ids:
            return False

        _seen_message_ids[message_id] = now
        return True


def reply_agent_result(message_id: str, sender_open_id: str, result: str) -> None:
    use_webhook = REPLY_MODE == "webhook" or (
        REPLY_MODE == "auto" and is_webhook_configured()
    )
    if use_webhook:
        mention_open_id = sender_open_id if WEBHOOK_MENTION_SENDER else ""
        send_feishu_webhook_text(result, mention_open_id=mention_open_id)
        return

    if REPLY_MODE not in {"auto", "oauth"}:
        raise RuntimeError(
            "feishu.reply_mode 仅支持 auto、webhook 或 oauth"
        )
    reply_feishu_text_with_oauth(message_id, result)


def handle_message(data: Any) -> None:
    sender_type = get_sender_type(data)
    if sender_type and sender_type != "user":
        print(f"忽略非用户飞书消息：sender_type={sender_type}")
        return

    sender_open_id = get_sender_open_id(data)
    message_id = get_message_id(data)
    allowed_open_ids = get_allowed_open_ids()

    if allowed_open_ids and sender_open_id not in allowed_open_ids:
        print(f"忽略未授权飞书用户：{sender_open_id}")
        return

    command = extract_text(data)
    if not command:
        return

    print(f"收到飞书指令：{command}")

    try:
      result = send_agent_command(
         command=command,
         open_id=sender_open_id,
    )
    except Exception as error:
      result = f"Desk Agent调用失败：{error}"

    if not message_id:
        print("飞书事件缺少message_id，无法回复")
        return

    try:
        reply_agent_result(message_id, sender_open_id, result)
    except Exception as error:
        print(f"飞书回复异常：{error}")


def main():
    require_config()
    if REPLY_MODE == "webhook" and not is_webhook_configured():
        raise RuntimeError(
            "feishu.reply_mode=webhook，但 webhook_url 未配置"
        )
    active_reply_mode = (
        "webhook"
        if REPLY_MODE == "webhook"
        or (REPLY_MODE == "auto" and is_webhook_configured())
        else "oauth"
    )
    print(f"飞书回复通道：{active_reply_mode}")

    def on_message_receive(data: Any) -> None:
        message_id = get_message_id(data)
        if not claim_message(message_id):
            print(f"忽略重复飞书消息：{message_id}")
            return

        threading.Thread(
            target=handle_message,
            args=(data,),
            daemon=True,
        ).start()

    event_handler = (
        lark.EventDispatcherHandler
        .builder("", "", lark.LogLevel.INFO)
        .register_p2_im_message_receive_v1(on_message_receive)
        .build()
    )

    ws_client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )

    print("飞书机器人已启动，等待消息...")
    ws_client.start()


if __name__ == "__main__":
    main()
