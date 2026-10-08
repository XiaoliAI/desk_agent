from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from config.logger import setup_logging
from core.agent.task_helpers import (
    EDIT_DOCUMENT_SEND_TASK_TYPE,
    build_edit_prompt,
    find_edit_candidates,
    is_cancel,
    is_confirm,
    selection_index,
)


TAG = "langgraph.document_edit_send"
logger = setup_logging()
from core.agent.state import EditSendWorkflowState
from core.agent.task_repository import TaskRepository
from plugins_func.functions.replace_document_text import (
    _output_path,
    _replace_document,
)
from plugins_func.functions.send_file_email import (
    get_default_receiver,
    get_email_config,
    send_email_sync,
    validate_file_path,
)


class DocumentEditSendGraph:
    """LangGraph orchestration for document edit and email tasks."""

    def __init__(self, conn):
        self.conn = conn
        self.repository = TaskRepository()
        self.graph = self._build_graph()

    def _owner_id(self) -> str:
        for attribute in ("device_id", "client_id", "session_id"):
            value = getattr(self.conn, attribute, None)
            if value:
                return str(value)
        return "local-user"

    def _log_node(self, node: str, state: EditSendWorkflowState) -> None:
        logger.bind(tag=TAG).info(
            "进入节点: node={}, mode={}, owner={}",
            node,
            state.get("mode", "continue"),
            self._owner_id(),
        )

    @staticmethod
    def route(state: EditSendWorkflowState) -> str:
        if str(state.get("mode", "start")).strip() == "continue":
            return "continue"
        return "start"

    def search_file(
        self,
        state: EditSendWorkflowState,
    ) -> dict[str, Any]:
        self._log_node("search_file", state)
        entities = state.get("entities") or {}
        old_text = str(entities.get("old_text") or "").strip()
        new_text = str(entities.get("new_text") or "")
        file_query = str(entities.get("file_query") or "").strip()

        if not old_text:
            return {
                "current_step": "search_file",
                "result": "请说明要修改的原内容。",
                "error": "old_text is missing",
            }

        if not new_text:
            return {
                "current_step": "search_file",
                "result": "请说明要替换成的新内容。",
                "error": "new_text is missing",
            }

        try:
            candidates = find_edit_candidates(
                self.conn,
                file_query,
                old_text,
            )
            if not candidates:
                return {
                    "current_step": "search_file",
                    "result": (
                        f"没有找到包含“{old_text}”的可修改 Word 文件。"
                    ),
                    "error": "no candidates",
                }

            return {
                "current_step": "search_file",
                "candidates": [
                    {
                        "file_path": str(path),
                        "file_name": path.name,
                    }
                    for path in candidates
                ],
                "error": "",
            }
        except Exception as error:
            return {
                "current_step": "search_file",
                "result": f"搜索文件失败：{error}",
                "error": str(error),
            }

    def create_task(
        self,
        state: EditSendWorkflowState,
    ) -> dict[str, Any]:
        self._log_node("create_task", state)
        if state.get("error"):
            return {}

        entities = state.get("entities") or {}
        candidates = state.get("candidates") or []
        payload = {
            "file_query": str(entities.get("file_query") or "").strip(),
            "old_text": str(entities.get("old_text") or "").strip(),
            "new_text": str(entities.get("new_text") or ""),
            "receiver": get_default_receiver(self.conn),
            "candidates": candidates,
        }

        if len(candidates) == 1:
            payload.update(candidates[0])
            status = "waiting_confirmation"
        else:
            status = "waiting_selection"

        task = self.repository.create_task(
            self._owner_id(),
            EDIT_DOCUMENT_SEND_TASK_TYPE,
            payload,
            status=status,
        )

        return {
            "current_step": "create_task",
            "task": task,
            "payload": payload,
            "result": build_edit_prompt(task, status),
            "error": "",
        }

    def load_task(
        self,
        state: EditSendWorkflowState,
    ) -> dict[str, Any]:
        self._log_node("load_task", state)
        task = self.repository.get_latest_task(
            self._owner_id(),
            status="waiting_selection",
            task_type=EDIT_DOCUMENT_SEND_TASK_TYPE,
        )
        if task:
            return {
                "current_step": "load_task",
                "task": task,
                "task_status": "waiting_selection",
                "error": "",
            }

        task = self.repository.get_latest_task(
            self._owner_id(),
            status="waiting_confirmation",
            task_type=EDIT_DOCUMENT_SEND_TASK_TYPE,
        )
        if task:
            return {
                "current_step": "load_task",
                "task": task,
                "task_status": "waiting_confirmation",
                "error": "",
            }

        return {
            "current_step": "load_task",
            "task_status": "none",
            "result": "",
            "error": "",
        }

    @staticmethod
    def route_loaded(state: EditSendWorkflowState) -> str:
        status = state.get("task_status")
        if status == "waiting_selection":
            return "selection"
        if status == "waiting_confirmation":
            return "confirmation"
        return "none"

    def select_file(
        self,
        state: EditSendWorkflowState,
    ) -> dict[str, Any]:
        self._log_node("select_file", state)
        task = state.get("task") or {}
        payload = task.get("payload") or {}
        query = state.get("query", "")

        if is_cancel(query):
            self.repository.cancel_task(task["id"], self._owner_id())
            return {
                "current_step": "select_file",
                "result": "文件修改任务已取消。",
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
            "payload": new_payload,
            "result": build_edit_prompt(
                {"payload": new_payload},
                "waiting_confirmation",
            ),
            "error": "",
        }

    def decide_confirmation(
        self,
        state: EditSendWorkflowState,
    ) -> dict[str, Any]:
        self._log_node("decide_confirmation", state)
        query = state.get("query", "")
        task = state.get("task") or {}

        if is_cancel(query):
            return {"action": "cancel", "current_step": "decide_confirmation"}

        if is_confirm(query):
            return {"action": "execute", "current_step": "decide_confirmation"}

        return {
            "action": "finish",
            "current_step": "decide_confirmation",
            "result": build_edit_prompt(
                task,
                "waiting_confirmation",
            ),
            "error": "",
        }

    def route_confirmation(self, state: EditSendWorkflowState) -> str:
        return str(state.get("action", "finish"))

    def cancel_task(
        self,
        state: EditSendWorkflowState,
    ) -> dict[str, Any]:
        self._log_node("cancel_task", state)
        task = state.get("task") or {}
        if task and self.repository.cancel_task(task["id"], self._owner_id()):
            result = "文件修改任务已取消。"
        else:
            result = "这个文件任务已经执行、取消或正在执行。"
        return {
            "current_step": "cancel_task",
            "result": result,
            "error": "",
        }

    def edit_document(
        self,
        state: EditSendWorkflowState,
    ) -> dict[str, Any]:
        self._log_node("edit_document", state)
        task = state.get("task") or {}
        payload = task.get("payload") or {}
        target = None

        if not self.repository.claim_task(
            task["id"],
            self._owner_id(),
            ("waiting_confirmation",),
        ):
            return {
                "current_step": "edit_document",
                "result": "这个文件任务已经执行、取消或正在执行。",
                "error": "task claim failed",
            }

        try:
            source = validate_file_path(
                self.conn,
                payload["file_path"],
            )
            target = _output_path(self.conn, source, "")
            _replace_document(
                source,
                target,
                payload["old_text"],
                payload["new_text"],
            )
            return {
                "current_step": "edit_document",
                "source_path": str(source),
                "target_path": str(target),
                "error": "",
            }
        except Exception as error:
            self.repository.fail_task(task["id"], str(error))
            if target is not None and target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
            return {
                "current_step": "edit_document",
                "result": f"文件修改失败：{error}",
                "error": str(error),
            }

    @staticmethod
    def route_after_edit(state: EditSendWorkflowState) -> str:
        return "failed" if state.get("error") else "send"

    def send_file(
        self,
        state: EditSendWorkflowState,
    ) -> dict[str, Any]:
        self._log_node("send_file", state)
        task = state.get("task") or {}
        payload = task.get("payload") or {}
        target = Path(state["target_path"])

        try:
            send_email_sync(
                target,
                payload["receiver"],
                f"修改后的文件：{Path(payload['file_path']).name}",
                (
                    f"已将“{payload['old_text']}”修改为"
                    f"“{payload['new_text']}”，请查收附件。"
                ),
                get_email_config(self.conn),
            )
            self.repository.complete_task(
                task["id"],
                {
                    "source_name": Path(payload["file_path"]).name,
                    "output_name": target.name,
                    "receiver": payload["receiver"],
                },
            )
            return {
                "current_step": "send_file",
                "result": f"文件已修改并发送：{target.name}",
                "error": "",
            }
        except Exception as error:
            self.repository.fail_task(task["id"], str(error))
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
            return {
                "current_step": "send_file",
                "result": f"文件发送失败：{error}",
                "error": str(error),
            }

    @staticmethod
    def finish(
        state: EditSendWorkflowState,
    ) -> dict[str, Any]:
        return {
            "current_step": state.get("current_step", "finished"),
            "result": state.get("result") or state.get("error", ""),
        }

    def _build_graph(self):
        builder = StateGraph(EditSendWorkflowState)

        builder.add_node("search_file", self.search_file)
        builder.add_node("create_task", self.create_task)
        builder.add_node("load_task", self.load_task)
        builder.add_node("select_file", self.select_file)
        builder.add_node("decide_confirmation", self.decide_confirmation)
        builder.add_node("cancel_task", self.cancel_task)
        builder.add_node("edit_document", self.edit_document)
        builder.add_node("send_file", self.send_file)
        builder.add_node("finish", self.finish)

        builder.add_conditional_edges(
            START,
            self.route,
            {
                "start": "search_file",
                "continue": "load_task",
            },
        )
        builder.add_edge("search_file", "create_task")
        builder.add_edge("create_task", "finish")

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
                "execute": "edit_document",
                "finish": "finish",
            },
        )
        builder.add_edge("cancel_task", "finish")

        builder.add_conditional_edges(
            "edit_document",
            self.route_after_edit,
            {
                "send": "send_file",
                "failed": "finish",
            },
        )
        builder.add_edge("send_file", "finish")
        builder.add_edge("finish", END)

        return builder.compile()

    def invoke(
        self,
        state: EditSendWorkflowState,
    ) -> EditSendWorkflowState:
        return self.graph.invoke(state)

    async def ainvoke(
        self,
        state: EditSendWorkflowState,
    ) -> EditSendWorkflowState:
        return await self.graph.ainvoke(state)
