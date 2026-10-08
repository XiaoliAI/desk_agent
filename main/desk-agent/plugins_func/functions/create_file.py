from pathlib import Path
from typing import TYPE_CHECKING

from config.logger import setup_logging
from plugins_func.register import (
    register_function,
    ToolType,
    ActionResponse,
    Action,
)

if TYPE_CHECKING:
    from core.connection import ConnectionHandler


TAG = __name__
logger = setup_logging()


CREATE_FILE_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "create_file",
        "description": (
            "创建一个本地文件。"
            "文件会保存到Desk Agent的安全工作目录。"
            "支持txt、md、json、csv文件。"
            "当用户要求创建文件、写入笔记、保存文本或生成简单文档时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": (
                        "文件名，例如学习计划.txt、项目说明.md、数据.csv。"
                        "必须包含支持的扩展名。"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "要写入文件的内容。如果没有指定内容，可以为空字符串。",
                },
            },
            "required": ["file_name"],
        },
    },
}


DEFAULT_ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
}


def get_create_file_config(conn):
    """读取创建文件工具配置。"""
    return (
        conn.config
        .get("plugins", {})
        .get("create_file", {})
    )


def get_storage_root(conn) -> Path:
    """获取文件保存根目录。"""
    config = get_create_file_config(conn)

    configured_dir = config.get(
        "storage_dir",
        "data/desktop_files",
    )

    project_root = Path(__file__).resolve().parents[2]
    storage_root = (project_root / configured_dir).resolve()

    storage_root.mkdir(parents=True, exist_ok=True)

    return storage_root


def get_allowed_extensions(conn):
    """获取允许的文件扩展名。"""
    config = get_create_file_config(conn)

    extensions = config.get(
        "allowed_extensions",
        list(DEFAULT_ALLOWED_EXTENSIONS),
    )

    normalized_extensions = set()

    for extension in extensions:
        extension = str(extension).strip().lower()

        if not extension:
            continue

        if not extension.startswith("."):
            extension = "." + extension

        normalized_extensions.add(extension)

    return normalized_extensions or DEFAULT_ALLOWED_EXTENSIONS


def get_max_file_size(conn) -> int:
    """获取文件最大大小，默认1MB。"""
    config = get_create_file_config(conn)

    try:
        max_size = int(config.get("max_size_bytes", 1024 * 1024))
    except (TypeError, ValueError):
        max_size = 1024 * 1024

    return max(1, max_size)


def validate_file_name(conn, file_name: str):
    """校验文件名并返回安全路径。"""
    if not file_name or not str(file_name).strip():
        return None, "文件名不能为空"

    file_name = str(file_name).strip()

    if "\x00" in file_name:
        return None, "文件名包含非法字符"

    # 不允许传入绝对路径
    candidate = Path(file_name)

    if candidate.is_absolute():
        return None, "暂不允许使用绝对路径"

    # 禁止路径穿越
    if ".." in candidate.parts:
        return None, "文件名不能包含..路径"

    # Windows文件名不能包含这些字符
    invalid_chars = set('<>:"|?*')

    if any(char in file_name for char in invalid_chars):
        return None, "文件名包含Windows不允许的字符"

    # 第一版不允许用户直接写目录
    if "/" in file_name or "\\" in file_name:
        return None, "第一版只支持创建文件名，不支持创建子目录"

    if file_name in {".", ".."}:
        return None, "文件名无效"

    suffix = Path(file_name).suffix.lower()

    if not suffix:
        return None, "文件名必须包含扩展名，例如.txt或.md"

    allowed_extensions = get_allowed_extensions(conn)

    if suffix not in allowed_extensions:
        allowed_text = "、".join(sorted(allowed_extensions))
        return None, f"暂不支持{suffix}文件，只支持：{allowed_text}"

    storage_root = get_storage_root(conn)
    target_path = (storage_root / file_name).resolve()

    # 再次确认最终路径没有离开安全目录
    try:
        target_path.relative_to(storage_root)
    except ValueError:
        return None, "文件路径不安全"

    return target_path, None


@register_function(
    "create_file",
    CREATE_FILE_FUNCTION_DESC,
    ToolType.SYSTEM_CTL,
)
def create_file(
    conn: "ConnectionHandler",
    file_name: str,
    content: str = "",
):
    """创建文件并写入内容。"""
    target_path, error_message = validate_file_name(conn, file_name)

    if error_message:
        logger.bind(tag=TAG).warning(
            f"创建文件参数校验失败: {error_message}"
        )

        return ActionResponse(
            action=Action.RESPONSE,
            result=error_message,
            response=error_message,
        )

    content = "" if content is None else str(content)

    max_file_size = get_max_file_size(conn)
    content_size = len(content.encode("utf-8"))

    if content_size > max_file_size:
        message = (
            f"文件内容太大，当前为{content_size}字节，"
            f"最大允许{max_file_size}字节"
        )

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    try:
        # 使用utf-8写入，newline=""避免额外修改换行符
        target_path.write_text(
            content,
            encoding="utf-8",
            newline="",
        )

        message = (
            f"文件创建成功：{target_path.name}。"
            f"保存位置：{target_path}"
        )

        logger.bind(tag=TAG).info(
            f"创建文件成功: path={target_path}, size={content_size}"
        )

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    except OSError as error:
        message = f"创建文件失败：{error}"

        logger.bind(tag=TAG).error(message)

        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )