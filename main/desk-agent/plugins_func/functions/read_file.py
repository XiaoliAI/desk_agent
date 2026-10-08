import html
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from config.logger import setup_logging
from plugins_func.file_utils import resolve_requested_file as resolve_safe_file
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


READ_FILE_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "读取Desk Agent安全目录中的本地文件，并根据用户要求进行总结、提炼或回答。"
            "支持txt、md、json、csv和docx文件。"
            "当用户说读取、查看、总结、分析刚才生成的文件时调用。"
            "只能读取Desk Agent工作目录中的文件，不能读取任意系统文件。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": (
                        "文件名，可以带后缀，也可以不带后缀。"
                        "例如test.txt、项目说明、AI学习报告、"
                        "data/reports/AI汇报.docx。"
                    ),
                },
                "question": {
                    "type": "string",
                    "description": (
                        "可选。用户希望对文件执行的操作，例如总结文件、"
                        "提取关键点、回答文件中的问题。"
                    ),
                },
            },
            "required": ["file_name"],
        },
    },
}


def get_read_file_config(conn):
    return conn.config.get("plugins", {}).get("read_file", {})


def get_limits(conn):
    config = get_read_file_config(conn)

    try:
        max_bytes = int(config.get("max_file_size_bytes", 2 * 1024 * 1024))
    except (TypeError, ValueError):
        max_bytes = 2 * 1024 * 1024

    try:
        max_chars = int(config.get("max_chars", 12000))
    except (TypeError, ValueError):
        max_chars = 12000

    return max(1, max_bytes), max(1, max_chars)


def extract_docx_text(path: Path) -> str:
    """使用标准库提取Word文档中的段落文本。"""
    with zipfile.ZipFile(path, "r") as archive:
        document_xml = archive.read("word/document.xml")

    root = ElementTree.fromstring(document_xml)
    paragraphs = []

    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        parts = []
        for text_node in paragraph.iter(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
        ):
            parts.append(text_node.text or "")
        paragraph_text = "".join(parts).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    return "\n".join(paragraphs)


def read_file_content(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return extract_docx_text(path)

    return path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )


def clean_content(content: str, max_chars: int) -> tuple[str, bool]:
    content = str(content or "").replace("\x00", "").strip()
    content = html.unescape(content)

    if len(content) <= max_chars:
        return content, False

    return content[:max_chars].rstrip() + "\n[文件内容已截断]", True


@register_function(
    "read_file",
    READ_FILE_FUNCTION_DESC,
    ToolType.SYSTEM_CTL,
)
def read_file(
    conn: "ConnectionHandler",
    file_name: str,
    question: str = "",
):
    """读取安全目录中的文件，并把内容交给LLM继续处理。"""
    file_path, error_message = resolve_safe_file(conn, file_name)

    if error_message:
        logger.bind(tag=TAG).warning(
            f"读取文件参数校验失败: {error_message}"
        )
        return ActionResponse(
            action=Action.RESPONSE,
            result=error_message,
            response=error_message,
        )

    max_bytes, max_chars = get_limits(conn)

    try:
        if file_path.stat().st_size > max_bytes:
            message = (
                f"文件过大，当前限制为{max_bytes}字节，"
                "请先缩小文件后再读取"
            )
            return ActionResponse(
                action=Action.RESPONSE,
                result=message,
                response=message,
            )

        content = read_file_content(file_path)
        content, truncated = clean_content(content, max_chars)

        if not content:
            message = f"文件{file_path.name}为空，没有可读取的内容"
            return ActionResponse(
                action=Action.RESPONSE,
                result=message,
                response=message,
            )

        operation = str(question or "").strip()
        operation_hint = (
            f"\n用户希望执行的操作：{operation}"
            if operation
            else "\n请根据用户原始请求处理这份文件"
        )

        result = (
            f"文件名：{file_path.name}\n"
            f"文件类型：{file_path.suffix.lower()}\n"
            f"文件内容：\n{content}"
            f"{operation_hint}"
        )

        if truncated:
            result += (
                f"\n提示：文件内容超过{max_chars}字符，已经截断。"
                "请明确告诉用户当前分析基于截断内容。"
            )

        logger.bind(tag=TAG).info(
            f"读取文件成功: path={file_path}, chars={len(content)}, "
            f"truncated={truncated}"
        )

        return ActionResponse(
            action=Action.REQLLM,
            result=result,
            response=None,
        )

    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        message = f"读取文件失败：{error}"
        logger.bind(tag=TAG).error(message)
        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )
