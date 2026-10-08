import asyncio
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING

from config.logger import setup_logging
from plugins_func.file_utils import get_project_root, is_inside
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


SEARCH_LOCAL_FILES_DESC = {
    "type": "function",
    "function": {
        "name": "search_local_files",
        "description": (
            "在用户配置允许的本地目录中搜索文件。"
            "支持根据模糊文件名、主题或关键词查找文件。"
            "适用于用户说查找电脑文件、搜索桌面文件、寻找简历或报告时。"
            "只能搜索配置中的目录，不能搜索任意系统路径。"
            "搜索结果只返回候选文件，不会自动打开、发送或删除文件。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "要搜索的文件名或关键词，例如AI报告、"
                        "桌面上的简历、最近下载的项目文档。"
                    ),
                },
            },
            "required": ["query"],
        },
    },
}


DEFAULT_ALLOWED_DIRECTORIES = [
    "data/desktop_files",
    "data/reports",
]

DEFAULT_ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".docx",
    ".doc",
    ".pdf",
    ".xlsx",
    ".xls",
    ".pptx",
    ".jpg",
    ".jpeg",
    ".png",
    ".zip",
}

QUERY_NOISE_WORDS = (
    "帮我",
    "请",
    "查找",
    "搜索",
    "寻找",
    "找一下",
    "找找",
    "电脑上的",
    "电脑里",
    "电脑中的",
    "本地的",
    "桌面上的",
    "桌面里",
    "下载目录里的",
    "下载文件夹里的",
    "文件",
    "文档",
)

MAX_SEARCH_RESULTS = 10
DEFAULT_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
DEFAULT_SCAN_TIMEOUT_SECONDS = 8
DEFAULT_MAX_SCAN_FILES = 20000

SKIP_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "AppData",
    "Local Settings",
    "Application Data",
    "$RECYCLE.BIN",
    "System Volume Information",
}

def get_search_config(conn):
    return (
        conn.config
        .get("plugins", {})
        .get("local_file_search", {})
    )


def normalize_text(value: str) -> str:
    value = str(value or "").casefold()
    return re.sub(r"[\s_\-—–·.。]+", "", value)


def normalize_query(value: str) -> str:
    normalized = normalize_text(value)

    for word in QUERY_NOISE_WORDS:
        normalized = normalized.replace(normalize_text(word), "")

    return normalized


def get_allowed_extensions(conn):
    config = get_search_config(conn)
    extensions = config.get(
        "allowed_extensions",
        list(DEFAULT_ALLOWED_EXTENSIONS),
    )

    result = set()

    for extension in extensions:
        extension = str(extension).strip().lower()

        if not extension:
            continue

        if not extension.startswith("."):
            extension = "." + extension

        result.add(extension)

    return result or DEFAULT_ALLOWED_EXTENSIONS


def get_allowed_roots(conn):
    config = get_search_config(conn)
    directories = config.get(
        "allowed_directories",
        DEFAULT_ALLOWED_DIRECTORIES,
    )

    if not isinstance(directories, list):
        directories = DEFAULT_ALLOWED_DIRECTORIES

    project_root = get_project_root()
    roots = []

    for directory in directories:
        directory = Path(str(directory))

        if directory.is_absolute():
            root = directory.resolve()
        else:
            root = (project_root / directory).resolve()

        if root.is_dir():
            roots.append(root)

    return roots


def get_max_file_size(conn) -> int:
    config = get_search_config(conn)

    try:
        value = int(
            config.get(
                "max_file_size_bytes",
                DEFAULT_MAX_FILE_SIZE_BYTES,
            )
        )
    except (TypeError, ValueError):
        value = DEFAULT_MAX_FILE_SIZE_BYTES

    return max(1, value)


def get_max_results(conn) -> int:
    config = get_search_config(conn)

    try:
        value = int(
            config.get(
                "max_results",
                MAX_SEARCH_RESULTS,
            )
        )
    except (TypeError, ValueError):
        value = MAX_SEARCH_RESULTS

    return max(1, min(value, 50))

def get_scan_timeout_seconds(conn) -> float:
    config = get_search_config(conn)

    try:
        value = float(
            config.get(
                "scan_timeout_seconds",
                DEFAULT_SCAN_TIMEOUT_SECONDS,
            )
        )
    except (TypeError, ValueError):
        value = DEFAULT_SCAN_TIMEOUT_SECONDS

    return max(1.0, min(value, 30.0))


def get_max_scan_files(conn) -> int:
    config = get_search_config(conn)

    try:
        value = int(
            config.get(
                "max_scan_files",
                DEFAULT_MAX_SCAN_FILES,
            )
        )
    except (TypeError, ValueError):
        value = DEFAULT_MAX_SCAN_FILES

    return max(100, min(value, 200000))



def score_file(query: str, file_path: Path) -> float:
    query_text = normalize_query(query)
    if not query_text:
        return 0.0

    # Compare both the complete name and the stem. A query containing
    # ".docx" must rank the exact file above a same-stem PDF or DOC file.
    scores = []
    for file_text in (normalize_text(file_path.name), normalize_text(file_path.stem)):
        if not file_text:
            continue
        if query_text == file_text:
            scores.append(1.0)
        elif file_text.startswith(query_text):
            scores.append(0.95)
        elif query_text in file_text:
            scores.append(0.88)
        else:
            scores.append(SequenceMatcher(None, query_text, file_text).ratio() * 0.8)
    return max(scores, default=0.0)


def format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"

    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"

    return f"{size / 1024 / 1024:.1f} MB"


def display_path(file_path: Path) -> str:
    project_root = get_project_root()

    try:
        return str(file_path.relative_to(project_root))
    except ValueError:
        return str(file_path)


def search_files(conn, query: str):
    allowed_extensions = get_allowed_extensions(conn)
    allowed_roots = get_allowed_roots(conn)
    max_file_size = get_max_file_size(conn)
    max_results = get_max_results(conn)
    scan_timeout = get_scan_timeout_seconds(conn)
    max_scan_files = get_max_scan_files(conn)

    deadline = time.monotonic() + scan_timeout
    scanned_files = 0
    stopped_reason = ""

    candidates = []

    def handle_walk_error(error):
        logger.bind(tag=TAG).debug(
            f"跳过无法访问的目录: {error}"
        )

    for root in allowed_roots:
        if time.monotonic() >= deadline:
            stopped_reason = "timeout"
            break

        try:
            for current_dir, directory_names, file_names in os.walk(
                root,
                topdown=True,
                followlinks=False,
                onerror=handle_walk_error,
            ):
                if time.monotonic() >= deadline:
                    stopped_reason = "timeout"
                    break

                directory_names[:] = [
                    name
                    for name in directory_names
                    if name not in SKIP_DIRECTORY_NAMES
                    and not name.startswith(".")
                ]

                for file_name in file_names:
                    if time.monotonic() >= deadline:
                        stopped_reason = "timeout"
                        break

                    scanned_files += 1

                    if scanned_files > max_scan_files:
                        stopped_reason = "max_scan_files"
                        break

                    candidate = Path(current_dir) / file_name

                    try:
                        # Word lock files are not user documents.
                        if candidate.name.startswith("~$"):
                            continue
                        if candidate.suffix.lower() not in allowed_extensions:
                            continue

                        resolved_path = candidate.resolve()

                        if not is_inside(resolved_path, root):
                            continue

                        stat = resolved_path.stat()

                        if stat.st_size > max_file_size:
                            continue

                        score = score_file(query, resolved_path)

                        if score < 0.45:
                            continue

                        candidates.append(
                            {
                                "path": resolved_path,
                                "score": score,
                                "mtime": stat.st_mtime,
                            }
                        )

                    except OSError:
                        continue

                if stopped_reason:
                    break

        except OSError as error:
            logger.bind(tag=TAG).debug(
                f"扫描目录失败，已跳过: root={root}, error={error}"
            )
            continue

        if stopped_reason:
            break

    unique_candidates = {}

    for item in candidates:
        path_key = str(item["path"])
        old_item = unique_candidates.get(path_key)

        if old_item is None or item["score"] > old_item["score"]:
            unique_candidates[path_key] = item

    candidates = list(unique_candidates.values())

    candidates.sort(
        key=lambda item: (
            item["score"],
            item["mtime"],
        ),
        reverse=True,
    )

    logger.bind(tag=TAG).info(
        f"本地文件搜索扫描完成: query={query}, "
        f"scanned={scanned_files}, matches={len(candidates)}, "
        f"stop_reason={stopped_reason or 'complete'}"
    )

    return candidates[:max_results]


@register_function(
    "search_local_files",
    SEARCH_LOCAL_FILES_DESC,
    ToolType.SYSTEM_CTL,
)
async def search_local_files(
    conn: "ConnectionHandler",
    query: str,
):
    query = str(query or "").strip()

    if not query:
        message = "搜索关键词不能为空"

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    try:
        results = await asyncio.to_thread(
    search_files,
    conn,
    query,
)

        if not results:
            message = f"没有找到与“{query}”相关的文件"

            return ActionResponse(
                action=Action.RESPONSE,
                result=message,
                response=message,
            )

        lines = [
            f"找到{len(results)}个相关文件，请用户选择要操作的文件："
        ]

        for index, item in enumerate(results, start=1):
            path = item["path"]
            stat = path.stat()

            lines.append(
                f"{index}. {path.name} | "
                f"路径：{display_path(path)} | "
                f"大小：{format_file_size(stat.st_size)}"
            )

        message = "\n".join(lines)

        logger.bind(tag=TAG).info(
            f"本地文件搜索成功: query={query}, count={len(results)}"
        )

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    except Exception as error:
        message = f"搜索本地文件失败：{error}"

        logger.bind(tag=TAG).error(message)

        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )
