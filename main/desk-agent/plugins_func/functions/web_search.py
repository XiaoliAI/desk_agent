import httpx
from config.logger import setup_logging
from plugins_func.register import (
    register_function,
    ToolType,
    ActionResponse,
    Action,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

_DEFAULT_DESCRIPTION = (
    "联网搜索工具。当用户明确需要联网搜索问题时使用此工具。"
)

WEB_SEARCH_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": _DEFAULT_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题",
                }
            },
            "required": ["query"],
        },
    },
}


async def _search_metaso(api_key: str, query: str, max_results: int) -> str:
    """调用秘塔搜索API"""
    url = "https://metaso.cn/api/v1/search"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "size": max_results,
        "stream": False,
        "scope": "webpage",
        "includeSummary": True,
        "includeRawContent": False,
        "conciseSnippet": False,
    }
    logger.bind(tag=TAG).debug(f"秘塔搜索请求 | URL: {url} | payload: {payload}")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=3.0)) as client:
        response = await client.post(url, json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    logger.bind(tag=TAG).debug(
        f"秘塔搜索响应 | status: {response.status_code} | keys: {list(data.keys()) if isinstance(data, dict) else type(data)}"
    )

    error_text = _extract_api_error(data)
    if error_text:
        return f"联网搜索接口返回错误：{error_text}"

    webpages = _extract_metaso_webpages(data)
    if not webpages:
        return "未找到相关搜索结果。"

    lines = ["【联网搜索结果】"]
    for i, item in enumerate(webpages, 1):
        title = item.get("title", "无标题")
        snippet = item.get("summary", "")
        date = item.get("date", "")
        lines.append(f"{i}. 标题：{title}")
        if date:
            lines.append(f"   日期：{date}")
        if snippet:
            lines.append(f"   摘要：{snippet}")

    return "\n".join(lines)


async def _search_tavily(api_key: str, query: str, max_results: int) -> str:
    """调用Tavily搜索API"""
    url = "https://api.tavily.com/search"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_answer": "advanced",
    }
    logger.bind(tag=TAG).debug(f"Tavily搜索请求 | URL: {url} | payload: {payload}")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=3.0)) as client:
        response = await client.post(url, json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    logger.bind(tag=TAG).debug(
        f"Tavily搜索响应 | status: {response.status_code} | keys: {list(data.keys()) if isinstance(data, dict) else type(data)}"
    )

    error_text = _extract_api_error(data)
    if error_text:
        return f"联网搜索接口返回错误：{error_text}"

    results = data.get("results", [])
    if not results:
        return "未找到相关搜索结果。"

    answer = data.get("answer", "")
    lines = [f"【联网搜索结果】\n总结：{answer}"]
    # for i, item in enumerate(results, 1):
    #     title = item.get("title", "无标题")
    #     summary = item.get("content", "")
    #     lines.append(f"{i}. 标题：{title}")
    #     if summary:
    #         lines.append(f"   摘要：{summary}")

    return "\n".join(lines)


def _is_placeholder_api_key(api_key: str) -> bool:
    if not api_key:
        return True
    value = str(api_key).strip().lower()
    return value in {"mk-xxx", "tvly-xxx", "xxx"} or "你的" in value


def _extract_api_error(data) -> str:
    if not isinstance(data, dict):
        return ""

    for key in ("error", "message", "msg", "detail"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for sub_key in ("message", "msg", "detail", "error"):
                sub_value = value.get(sub_key)
                if isinstance(sub_value, str) and sub_value.strip():
                    return sub_value.strip()

    code = data.get("code")
    if code not in (None, 0, "0", 200, "200"):
        return f"错误码 {code}"

    return ""


def _extract_metaso_webpages(data):
    if not isinstance(data, dict):
        return []

    webpages = data.get("webpages")
    if isinstance(webpages, list):
        return webpages

    nested_data = data.get("data")
    if isinstance(nested_data, dict):
        for key in ("webpages", "results", "items"):
            value = nested_data.get(key)
            if isinstance(value, list):
                return value

    for key in ("results", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value

    return []


@register_function("web_search", WEB_SEARCH_FUNCTION_DESC, ToolType.SYSTEM_CTL)
async def web_search(conn: "ConnectionHandler", query: str = None):
    logger.bind(tag=TAG).info(f"web_search 被调用 | query={query}")
    if not query:
        return ActionResponse(Action.REQLLM, "请提供搜索关键词。", None)

    web_search_config = conn.config.get("plugins", {}).get("web_search", {})
    provider = web_search_config.get("provider", "").lower()
    max_results = int(web_search_config.get("max_results", 3))
    logger.bind(tag=TAG).info(f"web_search 配置 | provider={provider} | max_results={max_results} | config_keys={list(web_search_config.keys())}")

    api_key = web_search_config.get("api_key", "")
    if _is_placeholder_api_key(api_key):
        return ActionResponse(
            Action.REQLLM,
            "联网搜索功能还没有配置真实API Key，请在 data/.config.yaml 中配置 plugins.web_search.api_key。",
            None,
        )

    try:
        if provider == "metaso":
            result_text = await _search_metaso(api_key, query, max_results)
        elif provider == "tavily":
            result_text = await _search_tavily(api_key, query, max_results)
        else:
            return ActionResponse(
                Action.REQLLM,
                f"联网搜索功能未配置或配置的搜索源无效（当前：{provider}），请检查配置。",
                None,
            )
        logger.bind(tag=TAG).info(f"搜索结果组装完成:\n{result_text}")
    except httpx.TimeoutException:
        logger.bind(tag=TAG).error("联网搜索请求超时")
        result_text = "联网搜索请求超时，请稍后重试。"
    except httpx.HTTPStatusError as e:
        logger.bind(tag=TAG).error(f"联网搜索请求失败: {e}")
        result_text = "联网搜索请求失败，请稍后重试。"
    except Exception as e:
        logger.bind(tag=TAG).error(f"联网搜索异常: {e}")
        result_text = "联网搜索出现异常，请稍后重试。"

    return ActionResponse(Action.REQLLM, result_text, None)
