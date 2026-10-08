import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from config.logger import setup_logging
from core.agent.task_context import TaskContextManager
from core.agent.task_helpers import is_cancel, selection_index
from core.rag.paper_profile import build_paper_profile
from core.rag.pdf_loader import extract_pdf_pages, import_pdf
from plugins_func.functions.search_local_files import search_files
from plugins_func.register import Action, ActionResponse, ToolType, register_function

if TYPE_CHECKING:
    from core.connection import ConnectionHandler


TAG = __name__
LITERATURE_IMPORT_TASK_TYPE = "literature_import"
logger = setup_logging()

IMPORT_LITERATURE_DESC = {
    "type": "function",
    "function": {
        "name": "import_literature",
        "description": (
            "Import one PDF into the local literature knowledge base. "
            "If multiple PDFs match, create a selection task and wait for a number."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_query": {
                    "type": "string",
                    "description": "PDF filename or fuzzy search query",
                },
            },
            "required": ["file_query"],
        },
    },
}


def _task_manager(conn: "ConnectionHandler") -> TaskContextManager:
    return TaskContextManager(conn)


async def _import_one(conn, path: Path) -> dict:
    extracted = await asyncio.to_thread(extract_pdf_pages, path)
    profile = await build_paper_profile(conn, extracted[0], extracted[1])
    return await asyncio.to_thread(import_pdf, path, profile, extracted)


def _completed_result(imported: dict) -> dict:
    paper = imported["paper"]
    return {
        "paper_id": paper["paper_id"],
        "file_name": paper["file_name"],
        "file_path": paper["source_path"],
    }


@register_function(
    "import_literature",
    IMPORT_LITERATURE_DESC,
    ToolType.SYSTEM_CTL,
)
async def import_literature(
    conn: "ConnectionHandler",
    file_query: str,
):
    query = str(file_query or "").strip()
    if not query:
        message = "请提供 PDF 文件名或搜索关键词。"
        return ActionResponse(Action.RESPONSE, message, message)

    try:
        results = await asyncio.to_thread(search_files, conn, query)
        pdfs = [
            item["path"]
            for item in results
            if item["path"].suffix.lower() == ".pdf"
        ]
        if not pdfs:
            message = f"没有找到匹配的 PDF：{query}"
            return ActionResponse(Action.RESPONSE, message, message)

        normalized_query = query.strip().strip('"\'')
        exact_matches = [
            path
            for path in pdfs
            if path.name.casefold() == normalized_query.casefold()
        ]
        if exact_matches:
            pdfs = exact_matches[:1]
        elif len(pdfs) == 1:
            pdfs = pdfs[:1]
        else:
            manager = _task_manager(conn)
            manager.create(
                LITERATURE_IMPORT_TASK_TYPE,
                {
                    "file_query": query,
                    "candidates": [
                        {
                            "file_path": str(path),
                            "file_name": path.name,
                        }
                        for path in pdfs[:10]
                    ],
                },
                status="waiting_selection",
            )
            choices = "\n".join(
                f"{index}. {path.name} | {path}"
                for index, path in enumerate(pdfs[:10], start=1)
            )
            message = (
                f"找到 {len(pdfs)} 个可能的 PDF：\n{choices}\n"
                "请回复文件编号，例如 1。"
            )
            return ActionResponse(Action.RESPONSE, message, message)

        path = pdfs[0]
        manager = _task_manager(conn)
        task = manager.create(
            LITERATURE_IMPORT_TASK_TYPE,
            {
                "file_query": query,
                "file_path": str(path),
                "file_name": path.name,
            },
            status="running",
        )

        try:
            imported = await _import_one(conn, path)
            result = _completed_result(imported)
            manager.complete(task, result)
        except Exception as error:
            manager.fail(task, str(error))
            raise

        message = (
            f"已导入 {result['file_name']}，提取 {imported['page_count']} 页。"
            "现在可以搜索这篇论文的核心工作。"
        )
        logger.bind(tag=TAG).info(
            "Literature import complete: query={}, file={}",
            query,
            result["file_name"],
        )
        return ActionResponse(Action.RESPONSE, message, message)
    except Exception as error:
        message = f"Literature import failed: {error}"
        logger.bind(tag=TAG).error(message)
        return ActionResponse(Action.ERROR, message, message)


async def continue_literature_import(
    conn: "ConnectionHandler",
    query: str,
) -> str | None:
    """Resolve the current literature selection and import only that PDF."""
    manager = _task_manager(conn)
    context = manager.resolve_selection_task(LITERATURE_IMPORT_TASK_TYPE)
    if context is None:
        return None

    if is_cancel(query):
        manager.cancel(context)
        return "论文导入任务已取消。"

    candidates = context.payload.get("candidates") or []
    index = selection_index(query, len(candidates))
    if index is None:
        return "请回复论文编号，例如 1。"

    selected = candidates[index]
    file_path = Path(str(selected.get("file_path", ""))).resolve()
    if not file_path.is_file():
        manager.fail(context, "selected PDF does not exist")
        return f"找不到所选文件：{file_path.name}。"

    payload = dict(context.payload)
    payload.update(
        {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "selected_index": index + 1,
        }
    )
    running = manager.update(context, status="running", payload=payload)
    if running is None:
        return "论文导入任务状态更新失败。"

    try:
        imported = await _import_one(conn, file_path)
        result = _completed_result(imported)
        manager.complete(running, result)
        return (
            f"已导入 {result['file_name']}，提取 {imported['page_count']} 页。"
            "现在可以搜索这篇论文的核心工作。"
        )
    except Exception as error:
        manager.fail(running, str(error))
        logger.bind(tag=TAG).error("Selected literature import failed: {}", error)
        return f"论文导入失败：{error}"
