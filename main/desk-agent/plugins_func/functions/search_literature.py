import asyncio
from typing import TYPE_CHECKING

from config.logger import setup_logging
from core.agent.task_context import TaskContextManager
from core.rag.retriever import (
    format_retrieval_results,
    search_literature as retrieve_literature,
)
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

SEARCH_LITERATURE_DESC = {
    "type": "function",
    "function": {
        "name": "search_literature",
        "description": (
            "Search the local literature knowledge base. "
            "Prefer the selected paper's core work and page evidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research topic, method, contribution, or core work",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results, default 6",
                },
            },
            "required": ["query"],
        },
    },
}


def _current_paper_id(conn, query: str) -> str | None:
    context = TaskContextManager(conn).get_latest("literature_import")
    if context is None or not context.result:
        return None

    query_lower = query.casefold()
    file_name = str(context.result.get("file_name") or "").casefold()
    references_current = any(
        marker in query_lower
        for marker in ("这篇", "该篇", "这个文件", "当前论文", "这份论文")
    )
    if references_current or (file_name and file_name in query_lower):
        return context.result.get("paper_id")
    return None


@register_function(
    "search_literature",
    SEARCH_LITERATURE_DESC,
    ToolType.SYSTEM_CTL,
)
async def search_literature(
    conn: "ConnectionHandler",
    query: str,
    top_k: int = 6,
):
    query = str(query or "").strip()
    if not query:
        message = "Please provide a literature topic or keyword."
        return ActionResponse(Action.RESPONSE, message, message)

    try:
        paper_id = _current_paper_id(conn, query)
        results = await asyncio.to_thread(
            retrieve_literature,
            query,
            top_k,
            paper_id,
        )
        context = format_retrieval_results(query, results)
        logger.bind(tag=TAG).info(
            "Literature search complete: query={}, paper_id={}, results={}",
            query,
            paper_id or "all",
            len(results),
        )
        return ActionResponse(
            Action.REQLLM,
            result=context,
            response=None,
        )
    except Exception as error:
        message = f"Literature search failed: {error}"
        logger.bind(tag=TAG).error(message)
        return ActionResponse(Action.ERROR, message, message)
