import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from core.agent.task_repository import TaskRepository
from core.agent.task_memory import get_task_owner_id
from plugins_func.functions.replace_document_text import SUPPORTED_EXTENSIONS
from plugins_func.functions.search_local_files import (
    get_allowed_extensions,
    get_allowed_roots,
    is_inside,
    search_files,
)


EDIT_DOCUMENT_SEND_TASK_TYPE = "edit_document_and_send"
FILE_EMAIL_TASK_TYPE = "send_file_email"


def get_task_owner(conn) -> str:
    for attribute in ("device_id", "client_id", "session_id"):
        value = getattr(conn, attribute, None)
        if value:
            return str(value)
    return "local-user"


def selection_index(text: str, count: int) -> int | None:
    value = str(text or "").strip().casefold()
    match = re.search(r"(?:第\s*)?(\d+)", value)
    if match:
        index = int(match.group(1))
    else:
        numbers = {
            "零": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        index = next(
            (number for word, number in numbers.items() if word in value),
            None,
        )

    if index is None or not 1 <= index <= count:
        return None
    return index - 1


def is_cancel(text: str) -> bool:
    value = re.sub(r"\s+", "", str(text or "").casefold())
    return any(
        word in value
        for word in ("取消", "不要", "别发", "不用", "不发")
    )


def is_confirm(text: str) -> bool:
    value = re.sub(r"\s+", "", str(text or "").casefold())
    return any(
        word in value
        for word in ("确认", "可以发送", "发送吧", "发吧", "执行")
    )


def docx_contains_text(path: Path, query: str) -> bool:
    if path.suffix.lower() != ".docx" or not query:
        return False
    try:
        with zipfile.ZipFile(path, "r") as package:
            for name in package.namelist():
                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                root = ElementTree.fromstring(package.read(name))
                if query in "".join(root.itertext()):
                    return True
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError):
        return False
    return False


def content_candidates(conn, old_text: str) -> list[Path]:
    candidates = []
    for root in get_allowed_roots(conn):
        for current_dir, directory_names, file_names in os.walk(root):
            directory_names[:] = [
                name
                for name in directory_names
                if name not in {".git", ".venv", "__pycache__", "node_modules"}
            ]
            for file_name in file_names:
                if file_name.startswith("~$"):
                    continue
                path = (Path(current_dir) / file_name).resolve()
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                if path.suffix.lower() == ".docx" and docx_contains_text(
                    path,
                    old_text,
                ):
                    candidates.append(path)
    return candidates


def find_edit_candidates(
    conn,
    file_query: str,
    old_text: str,
) -> list[Path]:
    query = str(file_query or "").strip()
    allowed = get_allowed_extensions(conn) & SUPPORTED_EXTENSIONS
    paths = []

    recent_alias = any(
        marker in query
        for marker in ("找到的", "刚刚", "刚才", "上次", "之前")
    )
    if recent_alias:
        repository = TaskRepository()
        for task in repository.get_active_tasks(
            get_task_owner_id(conn),
            limit=10,
        ):
            payload = task.get("payload") or {}
            recent_items = []
            if payload.get("file_path"):
                recent_items.append(payload["file_path"])
            recent_items.extend(
                item.get("file_path", "")
                for item in payload.get("candidates", [])
                if isinstance(item, dict)
            )
            for raw_path in recent_items:
                path = Path(str(raw_path)).resolve()
                if (
                    path.is_file()
                    and path.suffix.lower() in allowed
                    and not path.name.startswith("~$")
                    and any(
                        is_inside(path, root)
                        for root in get_allowed_roots(conn)
                    )
                    and path not in paths
                ):
                    paths.append(path)
        if paths:
            return paths[:5]

    if query:
        paths = [
            item["path"]
            for item in search_files(conn, query)
            if item["path"].suffix.lower() in allowed
            and not item["path"].name.startswith("~$")
        ]

    if not paths:
        paths = content_candidates(conn, old_text)

    unique = []
    for path in paths:
        path = path.resolve()
        if path not in unique:
            unique.append(path)
    return unique[:5]


def build_edit_prompt(task: dict, status: str) -> str:
    payload = task["payload"]
    if status == "waiting_selection":
        lines = ["找到多个可能的 Word 文件，请先选择："]
        lines.extend(
            f"{index}. {item['file_name']}"
            for index, item in enumerate(payload["candidates"], start=1)
        )
        lines.append("选择后，我会展示修改内容并等待确认。")
        return "\n".join(lines)

    return (
        f"已找到文件“{payload['file_name']}”。\n"
        f"将把“{payload['old_text']}”修改为“{payload['new_text']}”，"
        f"然后发送到 {payload['receiver']}。\n"
        "请回复“确认”执行，或回复“取消”。"
    )
