from typing import Any


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 200


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    text = str(text or "").strip()

    if not text:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError(
            "chunk_overlap must be smaller than chunk_size"
        )

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)

        if end < text_length:
            boundary_candidates = [
                text.rfind("\n\n", start, end),
                text.rfind("\n", start, end),
                text.rfind("。", start, end),
                text.rfind(".", start, end),
                text.rfind(";", start, end),
                text.rfind("；", start, end),
            ]
            boundary = max(boundary_candidates)

            minimum_boundary = start + chunk_size // 2
            if boundary >= minimum_boundary:
                end = boundary + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        start = max(end - chunk_overlap, start + 1)

    return chunks


def build_page_chunks(
    page: dict[str, Any],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    chunks = chunk_text(
        page.get("text", ""),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    result = []
    for index, text in enumerate(chunks):
        result.append(
            {
                "chunk_id": (
                    f"{page.get('paper_id', 'unknown')}_"
                    f"p{page.get('page', 0)}_"
                    f"c{index}"
                ),
                "paper_id": page.get("paper_id", ""),
                "file_name": page.get("file_name", ""),
                "library_path": page.get("library_path", ""),
                "page": page.get("page", 0),
                "chunk_index": index,
                "text": text,
            }
        )

    return result