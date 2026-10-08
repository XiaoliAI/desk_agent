from typing import TYPE_CHECKING

from config.logger import setup_logging
from core.agent.document_task_service import DocumentTaskService
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


CREATE_REPORT_FROM_FILE_DESC = {
    "type": "function",
    "function": {
        "name": "create_report_from_file",
        "description": (
            "为读取已有文件并生成新Word报告的复合任务创建执行计划。"
            "此工具只创建计划，不立即生成或打开文件。"
            "创建后必须等待用户明确说确认执行。"
            "单独读取使用read_file，单独写报告使用generate_report，"
            "单独打开文件使用open_file。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_file": {
                    "type": "string",
                    "description": "源文件的模糊名称，例如AI学习总结",
                },
                "topic": {
                    "type": "string",
                    "description": "新报告主题，例如AI学习情况",
                },
                "word_count": {
                    "type": "integer",
                    "description": "目标字数，默认300，范围20到2000",
                },
                "editor": {
                    "type": "string",
                    "enum": ["default", "word", "wps"],
                    "description": "确认执行后使用的打开程序",
                },
            },
            "required": ["source_file", "topic"],
        },
    },
}


MANAGE_DOCUMENT_TASK_DESC = {
    "type": "function",
    "function": {
        "name": "manage_document_task",
        "description": (
            "管理最近创建的文档任务。"
            "用户说确认执行、开始执行时action使用confirm；"
            "用户说取消任务时使用cancel；"
            "用户询问任务状态时使用status。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["confirm", "cancel", "status"],
                    "description": "确认、取消或查询任务",
                },
                "task_id": {
                    "type": "string",
                    "description": "可选任务ID；省略时操作当前用户最新任务",
                },
            },
            "required": ["action"],
        },
    },
}


@register_function(
    "create_report_from_file",
    CREATE_REPORT_FROM_FILE_DESC,
    ToolType.SYSTEM_CTL,
)
def create_report_from_file(
    conn: "ConnectionHandler",
    source_file: str,
    topic: str,
    word_count: int = 300,
    editor: str = "default",
):
    try:
        service = DocumentTaskService(conn)
        task = service.create_plan(
            source_file,
            topic,
            word_count,
            editor,
        )
        payload = task["payload"]
        message = (
            f"任务计划已创建，编号{task['id'][:8]}。"
            f"将读取{payload['source_name']}，"
            f"生成约{payload['word_count']}字的{payload['topic']}报告，"
            f"然后使用{payload['editor']}打开。"
            "请说确认执行或取消任务。"
        )
        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )
    except Exception as error:
        message = f"创建任务计划失败：{error}"
        logger.bind(tag=TAG).error(message)
        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )


@register_function(
    "manage_document_task",
    MANAGE_DOCUMENT_TASK_DESC,
    ToolType.SYSTEM_CTL,
)
async def manage_document_task(
    conn: "ConnectionHandler",
    action: str,
    task_id: str | None = None,
):
    service = DocumentTaskService(conn)
    action = str(action or "").strip().lower()

    try:
        if action == "confirm":
            confirmed_id, result = await service.confirm(task_id)
            message = (
                f"任务{confirmed_id[:8]}执行完成。"
                f"{result['message']}"
            )
        elif action == "cancel":
            cancelled_id = service.cancel(task_id)
            message = f"任务{cancelled_id[:8]}已取消"
        elif action == "status":
            task = service.get_status(task_id)
            message = (
                f"任务{task['id'][:8]}当前状态为{task['status']}，"
                f"任务主题是{task['payload'].get('topic', '未命名')}"
            )
            if task.get("error"):
                message += f"，失败原因：{task['error']}"
        else:
            raise ValueError("action只支持confirm、cancel或status")

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )
    except Exception as error:
        message = f"任务操作失败：{error}"
        logger.bind(tag=TAG).error(message)
        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )