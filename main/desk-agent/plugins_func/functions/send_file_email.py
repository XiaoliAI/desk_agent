import asyncio
import mimetypes
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import TYPE_CHECKING

from config.logger import setup_logging
from core.agent.task_repository import TaskRepository
from plugins_func.file_utils import is_inside
from plugins_func.functions.search_local_files import (
    display_path,
    get_allowed_extensions,
    get_allowed_roots,
    search_files,
)
from plugins_func.register import (
    Action,
    ActionResponse,
    ToolType,
    register_function,
)

if TYPE_CHECKING:
    from core.connection import ConnectionHandler


TAG = __name__
logger = setup_logging()


TASK_TYPE = "send_file_email"
DEFAULT_MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024


def get_owner_id(conn) -> str:
    for attribute in ("device_id", "client_id", "session_id"):
        value = getattr(conn, attribute, None)
        if value:
            return str(value)
    return "local-user"


def get_email_config(conn) -> dict:
    return (
        conn.config
        .get("plugins", {})
        .get("file_email", {})
    )


def validate_email(address: str) -> str:
    address = str(address or "").strip()
    _, parsed_address = parseaddr(address)

    if parsed_address != address:
        raise ValueError("收件邮箱格式不正确")

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
        raise ValueError("收件邮箱格式不正确")

    return address


def get_default_receiver(conn) -> str:
    config = get_email_config(conn)
    receiver = str(
        config.get("default_receiver")
        or os.getenv("DESK_AGENT_SMTP_USER", "")
    ).strip()

    if not receiver:
        raise ValueError(
            "没有配置默认收件邮箱，请在data/.config.yaml的"
            "plugins.file_email.default_receiver中配置"
        )

    return validate_email(receiver)


def validate_file_path(conn, file_path: str) -> Path:
    path = Path(file_path).resolve()

    if not path.is_file():
        raise FileNotFoundError("文件不存在，可能已经被移动或删除")

    roots = get_allowed_roots(conn)

    if not any(is_inside(path, root) for root in roots):
        raise PermissionError("文件不在允许访问的安全目录中")

    if path.suffix.lower() not in get_allowed_extensions(conn):
        raise ValueError(f"暂不允许发送{path.suffix}文件")

    config = get_email_config(conn)

    try:
        max_size = int(
            config.get(
                "max_attachment_size_bytes",
                DEFAULT_MAX_ATTACHMENT_SIZE,
            )
        )
    except (TypeError, ValueError):
        max_size = DEFAULT_MAX_ATTACHMENT_SIZE

    if path.stat().st_size > max_size:
        raise ValueError("附件超过允许的大小限制")

    return path


async def find_file_candidates(conn, file_name: str) -> list[Path]:
    query = str(file_name or "").strip()

    if not query:
        raise ValueError("文件名不能为空")

    results = await asyncio.to_thread(search_files, conn, query)

    if not results:
        raise FileNotFoundError(
            f"安全目录中没有找到与“{query}”相关的文件"
        )

    query_name = Path(query).name.casefold()

    exact_matches = [
        item["path"]
        for item in results
        if item["path"].name.casefold() == query_name
    ]

    if len(exact_matches) == 1:
        return [validate_file_path(conn, str(exact_matches[0]))]

    if len(results) > 1:
        return [
            validate_file_path(conn, str(item["path"]))
            for item in results[:5]
        ]

    return [validate_file_path(conn, str(results[0]["path"]))]


async def resolve_file(conn, file_name: str) -> Path:
    candidates = await find_file_candidates(conn, file_name)
    if len(candidates) != 1:
        raise ValueError("找到多个相似文件，请先选择具体文件")
    return candidates[0]


def get_smtp_settings(config: dict | None = None):
    config = config or {}
    host = (
        os.getenv("DESK_AGENT_SMTP_HOST", "").strip()
        or str(config.get("smtp_host", "")).strip()
    )
    user = (
        os.getenv("DESK_AGENT_SMTP_USER", "").strip()
        or str(config.get("smtp_user", "")).strip()
    )
    password = (
        os.getenv("DESK_AGENT_SMTP_PASSWORD", "").strip()
        or str(config.get("smtp_password", "")).strip()
    )

    if not host or not user or not password:
        raise RuntimeError(
            "未配置SMTP，请设置DESK_AGENT_SMTP_HOST、"
            "DESK_AGENT_SMTP_USER和DESK_AGENT_SMTP_PASSWORD"
        )

    try:
        port = int(
            os.getenv(
                "DESK_AGENT_SMTP_PORT",
                str(config.get("smtp_port", "465")),
            )
        )
    except ValueError:
        port = 465

    return host, port, user, password


def send_email_sync(
    file_path: Path,
    receiver: str,
    subject: str,
    body: str,
    smtp_config: dict | None = None,
):
    host, port, user, password = get_smtp_settings(smtp_config)

    message = EmailMessage()
    message["From"] = user
    message["To"] = receiver
    message["Subject"] = subject
    message.set_content(body)

    content_type, _ = mimetypes.guess_type(file_path.name)
    if content_type and "/" in content_type:
        maintype, subtype = content_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    message.add_attachment(
        file_path.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=file_path.name,
    )

    context = ssl.create_default_context()

    if port == 465:
        with smtplib.SMTP_SSL(
            host,
            port,
            timeout=30,
            context=context,
        ) as server:
            server.login(user, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(user, password)
            server.send_message(message)


PREPARE_EMAIL_DESC = {
    "type": "function",
    "function": {
        "name": "prepare_file_email",
        "description": (
            "搜索安全目录中的本地文件，创建一个待确认的邮件发送任务。"
            "只创建发送计划，不会立即发送邮件。"
            "用户必须之后明确说确认发送，才能真正发送附件。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "要发送的本地文件名，可以使用模糊名称",
                },
                "receiver": {
                    "type": "string",
                    "description": (
                        "收件人的邮箱地址。用户说‘发到我的邮箱’时省略此参数，"
                        "系统会使用配置的默认邮箱"
                    ),
                },
                "subject": {
                    "type": "string",
                    "description": "邮件主题，可选",
                },
                "body": {
                    "type": "string",
                    "description": "邮件正文，可选",
                },
            },
            "required": ["file_name"],
        },
    },
}


MANAGE_EMAIL_DESC = {
    "type": "function",
    "function": {
        "name": "manage_file_email_task",
        "description": (
            "管理邮件发送任务。用户说确认发送时使用confirm，"
            "用户说取消发送时使用cancel，"
            "用户询问邮件任务状态时使用status。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["confirm", "cancel", "status"],
                },
                "task_id": {
                    "type": "string",
                    "description": "可选的任务编号",
                },
            },
            "required": ["action"],
        },
    },
}


@register_function(
    "prepare_file_email",
    PREPARE_EMAIL_DESC,
    ToolType.SYSTEM_CTL,
)
async def prepare_file_email(
    conn: "ConnectionHandler",
    file_name: str,
    receiver: str = "",
    subject: str = "",
    body: str = "",
):
    try:
        receiver_text = str(receiver or "").strip()
        if receiver_text in {
            "",
            "我的邮箱",
            "我邮箱",
            "默认邮箱",
            "自己的邮箱",
        }:
            receiver = get_default_receiver(conn)
        else:
            receiver = validate_email(receiver_text)
        file_candidates = await find_file_candidates(conn, file_name)
        subject = str(subject).strip()
        body = str(body).strip() or "请查收附件。"

        repository = TaskRepository()
        owner_id = get_owner_id(conn)
        task_status = (
            "waiting_confirmation" if len(file_candidates) == 1
            else "waiting_selection"
        )
        first_path = file_candidates[0]
        payload = {
            "query": file_name,
            "file_path": str(first_path) if len(file_candidates) == 1 else "",
            "file_name": first_path.name if len(file_candidates) == 1 else "",
            "receiver": receiver,
            "subject": subject or f"Desk Agent文件：{first_path.name}",
            "body": body,
            "candidates": [
                {"file_path": str(path), "file_name": path.name}
                for path in file_candidates
            ],
        }

        task = repository.create_task(
            owner_id,
            TASK_TYPE,
            payload,
            status=task_status,
        )

        if len(file_candidates) == 1:
            message = (
                f"已找到文件“{first_path.name}”，准备发送到{receiver}。"
                "请说“确认发送”或“取消发送”。"
                f"任务编号：{task['id'][:8]}"
            )
        else:
            lines = ["找到多个相似文件，请回复编号选择："]
            lines.extend(
                f"{index}. {path.name} | {display_path(path)}"
                for index, path in enumerate(file_candidates, start=1)
            )
            lines.append("选择后还需要回复“确认发送”。")
            message = "\n".join(lines)

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    except Exception as error:
        logger.bind(tag=TAG).error(
            f"创建邮件任务失败: {error}"
        )
        message = f"创建邮件任务失败：{error}"

        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )


@register_function(
    "manage_file_email_task",
    MANAGE_EMAIL_DESC,
    ToolType.SYSTEM_CTL,
)
async def manage_file_email_task(
    conn: "ConnectionHandler",
    action: str,
    task_id: str | None = None,
):
    repository = TaskRepository()
    owner_id = get_owner_id(conn)
    action = str(action or "").strip().lower()

    try:
        if task_id:
            task = repository.get_task(task_id, owner_id)
        else:
            task = None
            if action in {"confirm", "cancel"}:
                for status in ("waiting_confirmation", "pending"):
                    task = repository.get_latest_task(
                        owner_id,
                        status=status,
                        task_type=TASK_TYPE,
                    )
                    if task:
                        break
            else:
                task = repository.get_latest_task(
                    owner_id,
                    task_type=TASK_TYPE,
                )

        if not task:
            raise ValueError("没有找到邮件任务")

        if task["task_type"] != TASK_TYPE:
            raise ValueError("当前任务不是邮件发送任务")

        if action == "cancel":
            if not repository.cancel_task(task["id"], owner_id):
                raise ValueError("任务已经执行、取消或正在运行")

            message = f"邮件任务{task['id'][:8]}已取消"

        elif action == "status":
            message = (
                f"邮件任务{task['id'][:8]}当前状态为{task['status']}"
            )

        elif action == "confirm":
            if not repository.claim_task(
                task["id"],
                owner_id,
                ("pending", "waiting_confirmation"),
            ):
                raise ValueError("任务已经执行、取消或正在运行")

            payload = task["payload"]

            try:
                file_path = validate_file_path(
                    conn,
                    payload["file_path"],
                )

                await asyncio.to_thread(
                    send_email_sync,
                    file_path,
                    payload["receiver"],
                    payload["subject"],
                    payload["body"],
                    get_email_config(conn),
                )

                result = {
                    "file_name": file_path.name,
                    "receiver": payload["receiver"],
                }

                repository.complete_task(task["id"], result)
                message = (
                    f"文件{file_path.name}已发送到"
                    f"{payload['receiver']}"
                )

            except Exception as error:
                repository.fail_task(task["id"], str(error))
                raise

        else:
            raise ValueError(
                "action只能是confirm、cancel或status"
            )

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    except Exception as error:
        logger.bind(tag=TAG).error(
            f"邮件任务操作失败: {error}"
        )
        message = f"邮件任务操作失败：{error}"

        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )
