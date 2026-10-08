#这段代码实现了一个文档任务服务（DocumentTaskService），负责创建、确认执行、取消和查询“从文件生成报告”任务，并调用 DocumentWorkflow 执行流程、校验输出路径、更新任务状态。

from pathlib import Path

from core.agent.document_workflow import DocumentWorkflow
from core.agent.task_repository import TaskRepository
from plugins_func.file_utils import (
    get_project_root,
    resolve_requested_file,
)
from plugins_func.functions.generate_report import normalize_editor


ALLOWED_EDITORS = {"default", "word", "wps"}


def get_owner_id(conn) -> str:
    for attribute in ("device_id", "client_id", "session_id"):
        value = getattr(conn, attribute, None)
        if value:
            return str(value)
    return "local-user"


def validate_word_count(value) -> int:
    try:
        count = int(value or 300)
    except (TypeError, ValueError):
        count = 300
    return max(20, min(count, 2000))


def verify_report_path(conn, report_path: Path) -> Path:
    path = Path(report_path).resolve()
    project_root = get_project_root()

    output_dir = (
        conn.config
        .get("plugins", {})
        .get("generate_report", {})
        .get("output_dir", "data/reports")
    )
    report_root = (project_root / str(output_dir)).resolve()

    try:
        path.relative_to(report_root)
    except ValueError as error:
        raise ValueError("生成结果不在安全报告目录中") from error

    if path.suffix.lower() != ".docx":
        raise ValueError("生成结果不是DOCX文件")

    if not path.is_file():
        raise FileNotFoundError("报告生成后没有找到输出文件")

    return path


class DocumentTaskService:
    TASK_TYPE = "create_report_from_file"

    def __init__(self, conn):
        self.conn = conn
        self.owner_id = get_owner_id(conn)
        self.repository = TaskRepository()

    def create_plan(
        self,
        source_file: str,
        topic: str,
        word_count: int = 300,
        editor: str = "default",
    ) -> dict:
        source_path, error = resolve_requested_file(
            self.conn,
            source_file,
        )
        if error:
            raise ValueError(error)

        topic = str(topic or "").strip()
        if not topic:
            raise ValueError("报告主题不能为空")

        editor = normalize_editor(editor)
        if editor not in ALLOWED_EDITORS:
            raise ValueError("编辑器只支持default、word或wps")

        project_root = get_project_root()
        relative_source = source_path.relative_to(project_root)

        payload = {
            "source_file": relative_source.as_posix(),
            "source_name": source_path.name,
            "topic": topic,
            "word_count": validate_word_count(word_count),
            "editor": editor,
        }

        return self.repository.create_task(
            self.owner_id,
            self.TASK_TYPE,
            payload,
        )

    async def confirm(self, task_id: str | None = None):
        task = (
            self.repository.get_task(task_id, self.owner_id)
            if task_id
            else self.repository.get_latest_task(
                self.owner_id,
                status="pending",
            )
        )

        if not task:
            raise ValueError("没有等待确认的任务")

        if task["task_type"] != self.TASK_TYPE:
            raise ValueError("当前任务类型不支持此执行器")

        if not self.repository.claim_pending_task(
            task["id"],
            self.owner_id,
        ):
            raise ValueError("任务已经被执行、取消或正在运行")

        payload = task["payload"]
        try:
            workflow = DocumentWorkflow(self.conn)
            state = await workflow.run(
                {
                    "source_file": payload["source_file"],
                    "topic": payload["topic"],
                    "word_count": payload["word_count"],
                    "editor": payload["editor"],
                    "current_step": "start",
                    "error": "",
                }
            )

            if state.get("error"):
                raise RuntimeError(state["error"])

            report_path = verify_report_path(
                self.conn,
                state["report_path"],
            )

            result = {
                "message": state.get("result", "任务执行完成"),
                "report_path": str(report_path),
                "report_name": report_path.name,
                "final_step": state.get("current_step"),
            }
            self.repository.complete_task(task["id"], result)
            return task["id"], result

        except Exception as error:
            self.repository.fail_task(task["id"], str(error))
            raise

    def cancel(self, task_id: str | None = None) -> str:
        task = (
            self.repository.get_task(task_id, self.owner_id)
            if task_id
            else self.repository.get_latest_task(
                self.owner_id,
                status="pending",
            )
        )
        if not task:
            raise ValueError("没有等待取消的任务")

        if not self.repository.cancel_task(task["id"], self.owner_id):
            raise ValueError("任务已经执行、取消或正在运行")
        return task["id"]

    def get_status(self, task_id: str | None = None):
        task = (
            self.repository.get_task(task_id, self.owner_id)
            if task_id
            else self.repository.get_latest_task(self.owner_id)
        )
        if not task:
            raise ValueError("还没有任务记录")
        return task