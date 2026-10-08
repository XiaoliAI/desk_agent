from typing import TYPE_CHECKING

from config.logger import setup_logging
from plugins_func.file_utils import resolve_requested_file
from plugins_func.functions.generate_report import normalize_editor, open_document
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


OPEN_FILE_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "open_file",
        "description": (
            "打开Desk Agent安全目录中的本地文件。"
            "适用于用户要求打开文件、用Word或WPS打开报告、"
            "打开刚才生成的报告。文件名可以省略扩展名。"
            "只能打开data/desktop_files和data/reports中的白名单文件，"
            "不能打开任意系统路径或执行程序。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": (
                        "要打开的文件名，可以省略后缀。"
                        "例如AI学习总结、项目说明、刚才生成的报告。"
                    ),
                },
                "editor": {
                    "type": "string",
                    "enum": ["default", "word", "wps"],
                    "description": (
                        "打开文件的程序。default为系统默认程序，"
                        "word为Microsoft Word，wps为WPS。"
                    ),
                },
            },
            "required": ["file_name"],
        },
    },
}


@register_function(
    "open_file",
    OPEN_FILE_FUNCTION_DESC,
    ToolType.SYSTEM_CTL,
)
def open_file(
    conn: "ConnectionHandler",
    file_name: str,
    editor: str = "default",
):
    """Open a whitelisted file with the default app, Word, or WPS."""
    file_path, error_message = resolve_requested_file(conn, file_name)
    if error_message:
        logger.bind(tag=TAG).warning(
            f"打开文件参数校验失败: {error_message}"
        )
        return ActionResponse(
            action=Action.RESPONSE,
            result=error_message,
            response=error_message,
        )

    normalized_editor = normalize_editor(editor)
    if normalized_editor not in {"default", "word", "wps"}:
        message = "打开程序只支持default、word或wps"
        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    try:
        editor_name = open_document(conn, file_path, normalized_editor)
        message = f"已使用{editor_name}打开{file_path.name}"
        logger.bind(tag=TAG).info(
            f"打开文件成功: path={file_path}, editor={normalized_editor}"
        )
        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )
    except Exception as error:
        message = f"打开文件失败：{error}"
        logger.bind(tag=TAG).error(
            f"打开文件失败: path={file_path}, editor={normalized_editor}, error={error}"
        )
        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )
