"""Rebuild the Chroma literature index from the JSONL compatibility index."""

import json
from collections import defaultdict
from typing import Any

from core.rag.pdf_loader import CHUNKS_INDEX
from core.rag.vector_store import ChromaVectorStore


def load_legacy_records() -> list[dict[str, Any]]:
    if not CHUNKS_INDEX.is_file():
        return []

    records = []
    with CHUNKS_INDEX.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if not record.get("chunk_id") or not str(record.get("text") or "").strip():
                continue
            normalized = dict(record)
            normalized.setdefault("chunk_type", "page_chunk")
            normalized.setdefault(
                "retrieval_priority",
                2 if normalized["chunk_type"] == "paper_profile" else 1,
            )
            records.append(normalized)
    return records


def rebuild_vector_index(
    vector_store: ChromaVectorStore | None = None,
) -> dict[str, int]:
    store = vector_store or ChromaVectorStore()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load_legacy_records():
        paper_id = str(record.get("paper_id") or "").strip()
        if paper_id:
            grouped[paper_id].append(record)

    vector_count = 0
    for paper_id, records in grouped.items():
        vector_count += store.replace_paper_records(paper_id, records)

    return {
        "paper_count": len(grouped),
        "vector_count": vector_count,
        "collection_count": store.count(),
    }


if __name__ == "__main__":
    result = rebuild_vector_index()
    print(
        "Vector index rebuilt: "
        f"papers={result['paper_count']}, "
        f"vectors={result['vector_count']}, "
        f"collection={result['collection_count']}"
    )
