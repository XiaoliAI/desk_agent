#定义任务在各节点间传递的数据。
from pathlib import Path
from typing import Any, TypedDict

class DocumentWorkflowState(TypedDict, total=False):
    source_file: str
    source_path: Path
    source_content: str

    topic: str
    word_count: int
    editor: str

    report_path: Path
    report_content: str

    current_step: str
    error: str
    result: str


class EditSendWorkflowState(TypedDict, total=False):
    mode: str
    query: str
    entities: dict[str, Any]
    candidates: list[dict[str, str]]
    task: dict[str, Any]
    payload: dict[str, Any]
    task_status: str
    action: str
    source_path: str
    target_path: str
    result: str
    error: str
    current_step: str


class FileEmailState(TypedDict, total=False):
    query: str
    task: dict[str, Any]
    task_status: str
    action: str
    result: str
    error: str
    current_step: str
