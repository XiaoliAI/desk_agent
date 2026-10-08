from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from config.logger import setup_logging
from core.agent.state import FileEmailState
from core.agent.task_repository import TaskRepository
from core.agent.task_helpers import (
    FILE_EMAIL_TASK_TYPE,
    is_cancel,
    is_confirm,
    selection_index,
)
from plugins_func.functions.send_file_email import (
    get_email_config,
    get_owner_id,
    send_email_sync,
    validate_file_path,
)


TAG = "langgraph.file_email"
logger = setup_logging()


class FileEmailGraph:
    """LangGraph orchestration for an existing file-email task."""

    def __init__(self, conn):
        self.conn = conn
        self.repository = TaskRepository()
        self.graph = self._build_graph()

    def _owner_id(self) -> str:
        return get_owner_id(self.conn)

    def _log_node(self, node: str, state: FileEmailState) -> None:
        logger.bind(tag=TAG).info(
            "进入节点: node={}, owner={}",
            node,
            self._owner_id(),
        )

    def load_task(
        self,
        state: FileEmailState,
    ) -> dict[str, Any]:
        self._log_node("load_task", state)
        task = self.repository.get_latest_task(
            self._owner_id(),
            status="waiting_selection",
            task_type=FILE_EMAIL_TASK_TYPE,
        )
        if task:
            return {
                "current_step": "load_task",
                "task": task,
                "task_status": "waiting_selection",
                "error": "",
            }

        for status in ("waiting_confirmation", "pending"):
            task = self.repository.get_latest_task(
                self._owner_id(),
                status=status,
                task_type=FILE_EMAIL_TASK_TYPE,
            )
            if task:
                return {
                    "current_step": "load_task",
                    "task": task,
                    "task_status": status,
                    "error": "",
                }

        return {
            "current_step": "load_task",
            "task_status": "none",
            "result": "",
            "error": "",
        }

    @staticmethod
    def route_loaded(state: FileEmailState) -> str:
        status = state.get("task_status")
        if status == "waiting_selection":
            return "selection"
        if status in {"waiting_confirmation", "pending"}:
            return "confirmation"
        return "none"

    def select_file(
        self,
        state: FileEmailState,
    ) -> dict[str, Any]:
        self._log_node("select_file", state)
        task = state.get("task") or {}
        payload = task.get("payload") or {}
        query = state.get("query", "")

        if is_cancel(query):
            self.repository.cancel_task(task["id"], self._owner_id())
            return {
                "current_step": "select_file",
                "result": "邮件发送任务已取消。",
                "error": "",
            }

        candidates = payload.get("candidates", [])
        index = selection_index(
            query,
            len(candidates),
        )
        if index is None:
            return {
                "current_step": "select_file",
                "result": "请回复文件编号，例如“1”。",
                "error": "",
            }

        selected = candidates[index]
        new_payload = dict(payload)
        new_payload.update(
            {
                "file_path": selected["file_path"],
                "file_name": selected["file_name"],
                "selected_index": index + 1,
            }
        )
        updated_task = self.repository.update_task(
            task["id"],
            self._owner_id(),
            status="waiting_confirmation",
            payload=new_payload,
        )

        return {
            "current_step": "select_file",
            "task": updated_task,
            "result": (
                f"已选择“{selected['file_name']}”，准备发送到"
                f"{new_payload['receiver']}。请回复“确认发送”或“取消发送”。"
            ),
            "error": "",
        }

    def decide_confirmation(
        self,
        state: FileEmailState,
    ) -> dict[str, Any]:
        self._log_node("decide_confirmation", state)
        query = state.get("query", "")

        if is_cancel(query):
            return {
                "current_step": "decide_confirmation",
                "action": "cancel",
                "error": "",
            }

        if is_confirm(query):
            return {
                "current_step": "decide_confirmation",
                "action": "send",
                "error": "",
            }

        return {
            "current_step": "decide_confirmation",
            "action": "finish",
            "result": "文件已准备好，请回复“确认发送”或“取消发送”。",
            "error": "",
        }

    @staticmethod
    def route_confirmation(state: FileEmailState) -> str:
        return str(state.get("action", "finish"))

    def cancel_task(
        self,
        state: FileEmailState,
    ) -> dict[str, Any]:
        self._log_node("cancel_task", state)
        task = state.get("task") or {}
        cancelled = bool(
            task
            and self.repository.cancel_task(
                task["id"],
                self._owner_id(),
            )
        )
        return {
            "current_step": "cancel_task",
            "result": (
                "邮件发送任务已取消。"
                if cancelled
                else "这个邮件任务已经执行、取消或正在执行。"
            ),
            "error": "",
        }

    def send_file(
        self,
        state: FileEmailState,
    ) -> dict[str, Any]:
        self._log_node("send_file", state)
        task = state.get("task") or {}
        payload = task.get("payload") or {}

        if not self.repository.claim_task(
            task["id"],
            self._owner_id(),
            ("waiting_confirmation", "pending"),
        ):
            return {
                "current_step": "send_file",
                "result": "这个邮件任务已经执行、取消或正在执行。",
                "error": "task claim failed",
            }

        try:
            file_path = validate_file_path(
                self.conn,
                payload["file_path"],
            )
            send_email_sync(
                file_path,
                payload["receiver"],
                payload.get("subject", "Desk Agent 文件"),
                payload.get("body", "请查收附件。"),
                get_email_config(self.conn),
            )
            self.repository.complete_task(
                task["id"],
                {
                    "file_name": file_path.name,
                    "receiver": payload["receiver"],
                },
            )
            return {
                "current_step": "send_file",
                "result": (
                    f"文件{file_path.name}已发送到"
                    f"{payload['receiver']}。"
                ),
                "error": "",
            }
        except Exception as error:
            self.repository.fail_task(task["id"], str(error))
            return {
                "current_step": "send_file",
                "result": f"邮件发送失败：{error}",
                "error": str(error),
            }

    @staticmethod
    def finish(
        state: FileEmailState,
    ) -> dict[str, Any]:
        return {
            "current_step": state.get("current_step", "finished"),
            "result": state.get("result") or state.get("error", ""),
        }

    def _build_graph(self):
        builder = StateGraph(FileEmailState)

        builder.add_node("load_task", self.load_task)
        builder.add_node("select_file", self.select_file)
        builder.add_node("decide_confirmation", self.decide_confirmation)
        builder.add_node("cancel_task", self.cancel_task)
        builder.add_node("send_file", self.send_file)
        builder.add_node("finish", self.finish)

        builder.add_edge(START, "load_task")
        builder.add_conditional_edges(
            "load_task",
            self.route_loaded,
            {
                "selection": "select_file",
                "confirmation": "decide_confirmation",
                "none": END,
            },
        )
        builder.add_edge("select_file", "finish")
        builder.add_conditional_edges(
            "decide_confirmation",
            self.route_confirmation,
            {
                "cancel": "cancel_task",
                "send": "send_file",
                "finish": "finish",
            },
        )
        builder.add_edge("cancel_task", "finish")
        builder.add_edge("send_file", "finish")
        builder.add_edge("finish", END)

        return builder.compile()

    def invoke(
        self,
        state: FileEmailState,
    ) -> FileEmailState:
        return self.graph.invoke(state)

    async def ainvoke(
        self,
        state: FileEmailState,
    ) -> FileEmailState:
        return await self.graph.ainvoke(state)
