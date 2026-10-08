import json

from core.agent.task_repository import TaskRepository


def get_task_owner_id(conn) -> str:
    """Use the same stable owner key as the task workflows."""
    for attribute in ("device_id", "client_id", "session_id"):
        value = getattr(conn, attribute, None)
        if value:
            return str(value)
    return "local-user"


def _safe_payload(payload: dict) -> dict:
    """Keep task memory useful without exposing credentials or raw task data."""
    allowed = (
        "file_query",
        "file_name",
        "file_path",
        "source_name",
        "source_file",
        "output_name",
        "output_file_name",
        "old_text",
        "new_text",
        "receiver",
        "topic",
        "word_count",
        "selected_index",
        "paper_id",
    )
    result = {key: payload[key] for key in allowed if key in payload}
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        result["candidate_files"] = [
            item.get("file_name", "")
            for item in candidates[:5]
            if isinstance(item, dict)
        ]
    return result


def build_task_memory(conn, limit: int = 5) -> str:
    """Build compact structured context from active SQLite tasks."""
    try:
        tasks = TaskRepository().get_active_tasks(get_task_owner_id(conn), limit)
    except Exception:
        return ""

    if not tasks:
        return ""

    context = []
    for task in tasks:
        context.append(
            {
                "task_id": task["id"][:8],
                "task_type": task["task_type"],
                "status": task["status"],
                "data": _safe_payload(task.get("payload") or {}),
            }
        )

    # Completed literature imports remain the current domain context even
    # after the selection task is finished.
    try:
        latest_literature = TaskRepository().get_latest_task(
            get_task_owner_id(conn),
            task_type="literature_import",
        )
        if latest_literature and latest_literature.get("result"):
            context.append(
                {
                    "task_id": latest_literature["id"][:8],
                    "task_type": "literature_context",
                    "status": latest_literature["status"],
                    "data": _safe_payload(latest_literature["result"]),
                }
            )
    except Exception:
        pass

    return (
        "当前活动任务（以此为准，不要猜测文件路径或任务状态）：\n"
        + json.dumps(context, ensure_ascii=False)
        + "\n只有用户明确确认后，才执行等待确认的高风险任务。"
    )
