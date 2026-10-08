from dataclasses import dataclass
from typing import Any

from core.agent.task_memory import get_task_owner_id
from core.agent.task_repository import TaskRepository


@dataclass
class TaskContext:
    task: dict[str, Any]

    @property
    def task_id(self) -> str:
        return self.task["id"]

    @property
    def task_type(self) -> str:
        return self.task["task_type"]

    @property
    def status(self) -> str:
        return self.task["status"]

    @property
    def payload(self) -> dict[str, Any]:
        return self.task.get("payload") or {}

    @property
    def result(self) -> dict[str, Any]:
        return self.task.get("result") or {}


class TaskContextManager:
    """Task state facade used by every feature to avoid context collisions."""

    ACTIVE_STATUSES = (
        "pending",
        "waiting_selection",
        "waiting_confirmation",
        "running",
    )

    def __init__(self, conn, repository: TaskRepository | None = None):
        self.conn = conn
        self.repository = repository or TaskRepository()
        self.owner_id = get_task_owner_id(conn)

    def list_active(self, limit: int = 20) -> list[TaskContext]:
        tasks = self.repository.get_active_tasks(self.owner_id, limit=limit)
        return [TaskContext(task) for task in tasks]

    def get_active(self, task_type: str) -> TaskContext | None:
        for context in self.list_active():
            if context.task_type == task_type:
                return context
        return None

    def get_latest(self, task_type: str) -> TaskContext | None:
        task = self.repository.get_latest_task(
            self.owner_id,
            task_type=task_type,
        )
        return TaskContext(task) if task else None

    def get_waiting_selection_tasks(self) -> list[TaskContext]:
        return [
            context
            for context in self.list_active()
            if context.status == "waiting_selection"
        ]

    def resolve_selection_task(
        self,
        task_type: str | None = None,
    ) -> TaskContext | None:
        tasks = self.get_waiting_selection_tasks()
        if task_type:
            return next(
                (task for task in tasks if task.task_type == task_type),
                None,
            )
        return tasks[0] if len(tasks) == 1 else None

    def create(
        self,
        task_type: str,
        payload: dict[str, Any],
        status: str = "pending",
    ) -> TaskContext:
        task = self.repository.create_task(
            self.owner_id,
            task_type,
            payload,
            status=status,
        )
        return TaskContext(task)

    def update(
        self,
        context: TaskContext,
        *,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> TaskContext | None:
        task = self.repository.update_task(
            context.task_id,
            self.owner_id,
            status=status,
            payload=payload,
        )
        return TaskContext(task) if task else None

    def complete(self, context: TaskContext, result: dict[str, Any]) -> None:
        self.repository.complete_task(context.task_id, result)

    def fail(self, context: TaskContext, error: str) -> None:
        self.repository.fail_task(context.task_id, error)

    def cancel(self, context: TaskContext) -> bool:
        return self.repository.cancel_task(context.task_id, self.owner_id)
