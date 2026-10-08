import json
import re
from pathlib import Path
from typing import Any

from core.rag.pdf_loader import CHUNKS_INDEX


def load_chunks() -> list[dict[str, Any]]:
    if not CHUNKS_INDEX.is_file():
        return []

    records = []

    with CHUNKS_INDEX.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(record, dict):
                records.append(record)

    return records


def tokenize(text: str) -> list[str]:
    text = str(text or "").lower()

    english_words = re.findall(
        r"[a-z0-9][a-z0-9_-]*",
        text,
    )

    chinese_chars = re.findall(
        r"[\u4e00-\u9fff]",
        text,
    )

    return english_words + chinese_chars


def score_record(
    query: str,
    record: dict[str, Any],
) -> float:
    query_text = str(query or "").strip().lower()
    content = str(record.get("text") or "").lower()

    if not query_text or not content:
        return 0.0

    score = 0.0

    if query_text in content:
        score += 8.0

    query_tokens = set(tokenize(query_text))
    content_tokens = set(tokenize(content))

    if query_tokens and content_tokens:
        overlap = query_tokens & content_tokens
        score += len(overlap) / len(query_tokens) * 5.0

    if record.get("chunk_type") == "paper_profile":
        score += 3.0

    if record.get("core_work"):
        score += 2.0

    return score


def search_literature(
    query: str,
    top_k: int = 6,
    paper_id: str | None = None,
) -> list[dict[str, Any]]:
    records = load_chunks()

    if paper_id:
        records = [
            record
            for record in records
            if record.get("paper_id") == paper_id
        ]

    scored = []

    for record in records:
        score = score_record(query, record)

        if score <= 0:
            continue

        item = dict(record)
        item["score"] = round(score, 4)
        scored.append(item)

    scored.sort(
        key=lambda item: (
            item["score"],
            item.get("chunk_type") == "paper_profile",
        ),
        reverse=True,
    )

    return scored[:max(1, int(top_k))]


def format_retrieval_results(
    query: str,
    results: list[dict[str, Any]],
) -> str:
    if not results:
        return (
            f"没有在本地文献库中找到与“{query}”相关的内容。"
        )

    lines = [
        f"关于“{query}”的文献检索结果：",
        "",
    ]

    for index, item in enumerate(results, start=1):
        file_name = item.get("file_name", "未知文件")
        page = item.get("page", "未知页码")
        chunk_type = item.get("chunk_type", "page_chunk")
        text = str(item.get("text") or "").strip()

        if chunk_type == "paper_profile":
            source_label = "论文核心工作摘要"
        else:
            source_label = f"原文片段，第{page}页"

        lines.append(
            f"{index}. [{file_name} | {source_label}]"
        )
        lines.append(text[:1800])
        lines.append("")

    return "\n".join(lines)
