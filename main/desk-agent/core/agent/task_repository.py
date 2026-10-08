#这段代码实现了一个基于 SQLite 的异步任务存储仓库（TaskRepository），用于创建、查询、认领、完成、失败和取消 agent 任务，并管理任务的状态流转。
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


TASK_STATUSES = {
    "pending",
    "waiting_selection",
    "waiting_confirmation",
    "running",
    "completed",
    "failed",
    "cancelled",
    "expired",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_default_database_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "data" / "agent_tasks.db"


class TaskRepository:
    def __init__(self, database_path: Path | None = None):
        self.database_path = database_path or get_default_database_path()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    completed_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_owner_status
                ON agent_tasks(owner_id, status, created_at DESC)
                """
            )

    @staticmethod
    def _to_dict(row):
        if row is None:
            return None

        task = dict(row)
        task["payload"] = json.loads(task["payload"])
        task["result"] = (
            json.loads(task["result"])
            if task.get("result")
            else None
        )
        return task

    def create_task(
        self,
        owner_id: str,
        task_type: str,
        payload: dict,
        status: str = "pending",
    ) -> dict:
        if status not in TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {status}")
        task_id = uuid.uuid4().hex
        now = utc_now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_tasks (
                    id, owner_id, task_type, status,
                    payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    owner_id,
                    task_type,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )

        return self.get_task(task_id, owner_id)

    def get_task(self, task_id: str, owner_id: str):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM agent_tasks
                WHERE id = ? AND owner_id = ?
                """,
                (task_id, owner_id),
            ).fetchone()
        return self._to_dict(row)

    def get_latest_task(
    self,
    owner_id: str,
    status: str | None = None,
    task_type: str | None = None,
):
        sql = "SELECT * FROM agent_tasks WHERE owner_id = ?"
        parameters = [owner_id]

        if status:
            sql += " AND status = ?"
            parameters.append(status)

        if task_type:
           sql += " AND task_type = ?"
           parameters.append(task_type)
        sql += " ORDER BY created_at DESC LIMIT 1"

        with self._connect() as connection:
            row = connection.execute(sql, parameters).fetchone()
        return self._to_dict(row)

    def get_active_tasks(self, owner_id: str, limit: int = 5):
        """Return resumable tasks for task-aware short-term context."""
        statuses = ("pending", "waiting_selection", "waiting_confirmation", "running")
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM agent_tasks
                WHERE owner_id = ? AND status IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (owner_id, *statuses, max(1, int(limit) * 10)),
            ).fetchall()
        # Keep only the newest active task of each type. Old abandoned tasks
        # must not crowd the short-term context or steal a confirmation.
        result = []
        seen_types = set()
        for row in rows:
            task = self._to_dict(row)
            if task["task_type"] in seen_types:
                continue
            seen_types.add(task["task_type"])
            result.append(task)
            if len(result) >= max(1, int(limit)):
                break
        return result

    def update_task(
        self,
        task_id: str,
        owner_id: str,
        *,
        status: str | None = None,
        payload: dict | None = None,
    ) -> dict | None:
        if status is not None and status not in TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {status}")

        assignments = ["updated_at = ?"]
        parameters = [utc_now()]

        if status is not None:
            assignments.append("status = ?")
            parameters.append(status)
        if payload is not None:
            assignments.append("payload = ?")
            parameters.append(json.dumps(payload, ensure_ascii=False))

        parameters.extend([task_id, owner_id])
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE agent_tasks
                SET {', '.join(assignments)}
                WHERE id = ? AND owner_id = ?
                """,
                parameters,
            )

        return self.get_task(task_id, owner_id)

    def claim_task(
        self,
        task_id: str,
        owner_id: str,
        allowed_statuses: tuple[str, ...] = ("pending", "waiting_confirmation"),
    ) -> bool:
        now = utc_now()
        placeholders = ",".join("?" for _ in allowed_statuses)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"""
                UPDATE agent_tasks
                SET status = 'running',
                    confirmed_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND owner_id = ?
                  AND status IN ({placeholders})
                """,
                (now, now, task_id, owner_id, *allowed_statuses),
            )
            return cursor.rowcount == 1

    def claim_pending_task(self, task_id: str, owner_id: str) -> bool:
        return self.claim_task(task_id, owner_id, ("pending",))

    def complete_task(self, task_id: str, result: dict):
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent_tasks
                SET status = 'completed',
                    result = ?,
                    error = NULL,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(result, ensure_ascii=False),
                    now,
                    now,
                    task_id,
                ),
            )

    def fail_task(self, task_id: str, error: str):
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent_tasks
                SET status = 'failed',
                    error = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (error, now, now, task_id),
            )

    def cancel_task(self, task_id: str, owner_id: str) -> bool:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks
                SET status = 'cancelled',
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                  AND owner_id = ?
                  AND status IN ('pending', 'waiting_selection', 'waiting_confirmation')
                """,
                (now, now, task_id, owner_id),
            )
            return cursor.rowcount == 1
