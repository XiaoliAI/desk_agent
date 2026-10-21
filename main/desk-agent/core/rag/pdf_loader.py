 #RAG 的“文献入库”模块：把一个 PDF 文件解析、复制、切块，并写入三个 JSONL 索引文件，供后续检索使用。



import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.rag.chunker import build_page_chunks
from core.rag.paper_profile import profile_text
from core.rag.vector_store import ChromaVectorStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LITERATURE_ROOT = PROJECT_ROOT / "data" / "literature"
PAPERS_ROOT = LITERATURE_ROOT / "papers"
INDEX_ROOT = LITERATURE_ROOT / "index"
PAGES_INDEX = INDEX_ROOT / "pages.jsonl"
CHUNKS_INDEX = INDEX_ROOT / "chunks.jsonl"
PAPERS_INDEX = INDEX_ROOT / "papers.jsonl"


def _require_pymupdf():
    try:
        import fitz
    except ImportError as error:
        raise RuntimeError(
            "PDF解析依赖未安装，请在desk-agent目录执行："
            ".\\.venv\\Scripts\\python.exe -m pip install PyMuPDF"
        ) from error
    return fitz


def ensure_literature_directories() -> None:
    PAPERS_ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_ROOT.mkdir(parents=True, exist_ok=True)


def _file_id(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()[:24]


def _copy_to_library(source: Path, file_id: str) -> Path:
    ensure_literature_directories()
    target = PAPERS_ROOT / f"{file_id}_{source.name}"
    if not target.exists():
        shutil.copy2(source, target)
    return target


def extract_pdf_pages(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fitz = _require_pymupdf()
    file_id = _file_id(path)

    try:
        document = fitz.open(str(path))
    except Exception as error:
        raise ValueError(f"无法打开PDF文件：{path.name}，{error}") from error

    metadata = document.metadata or {}
    paper = {
        "paper_id": file_id,
        "file_name": path.name,
        "source_path": str(path),
        "title": str(metadata.get("title") or path.stem).strip(),
        "author": str(metadata.get("author") or "").strip(),
        "subject": str(metadata.get("subject") or "").strip(),
        "page_count": len(document),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }

    pages = []
    for page_number, page in enumerate(document, start=1):
        text = page.get_text("text") or ""
        text = "\n".join(
            line.strip()
            for line in text.replace("\x00", "").splitlines()
            if line.strip()
        )
        if not text:
            continue
        pages.append(
            {
                "paper_id": file_id,
                "file_name": path.name,
                "page": page_number,
                "text": text,
            }
        )

    document.close()
    return paper, pages


def _read_index() -> list[dict[str, Any]]:
    if not PAGES_INDEX.is_file():
        return []
    records = []
    with PAGES_INDEX.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def import_pdf(
    path: Path,
    core_profile: dict[str, Any] | None = None,
    extracted: tuple[dict[str, Any], list[dict[str, Any]]] | None = None,
    vector_store: ChromaVectorStore | None = None,
) -> dict[str, Any]:
    source = path.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"找不到PDF文件：{source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError("文献知识库目前只支持PDF文件")

    paper, pages = extracted or extract_pdf_pages(source)
    library_path = _copy_to_library(source, paper["paper_id"])
    paper["library_path"] = str(library_path)
    paper["core_profile"] = core_profile or {}

    ensure_literature_directories()
    existing = [
        record
        for record in _read_index()
        if record.get("paper_id") != paper["paper_id"]
    ]
    existing.extend(
        {
            **page,
            "library_path": str(library_path),
        }
        for page in pages
    )
    with PAGES_INDEX.open("w", encoding="utf-8") as stream:
        for record in existing:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    old_chunks = []
    if CHUNKS_INDEX.is_file():
        with CHUNKS_INDEX.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(record, dict)
                    and record.get("paper_id") != paper["paper_id"]
                ):
                    old_chunks.append(record)

    page_records = [
        {
            **page,
            "library_path": str(library_path),
        }
        for page in pages
    ]
    chunk_records = []
    for page in page_records:
        page_chunks = build_page_chunks(page)
        for chunk in page_chunks:
            chunk["chunk_type"] = "page_chunk"
            chunk["retrieval_priority"] = 1
        chunk_records.extend(page_chunks)

    profile_record = None
    if core_profile:
        profile_record = {
            "chunk_id": f"{paper['paper_id']}_profile",
            "chunk_type": "paper_profile",
            "retrieval_priority": 2,
            "paper_id": paper["paper_id"],
            "file_name": paper["file_name"],
            "library_path": str(library_path),
            "page": core_profile.get("evidence_pages", []),
            "text": profile_text(core_profile),
            "core_work": core_profile.get("core_work", ""),
        }
        old_chunks.append(profile_record)
    old_chunks.extend(chunk_records)

    vector_records = list(chunk_records)
    if profile_record:
        vector_records.append(profile_record)
    store = vector_store or ChromaVectorStore()
    vector_count = store.replace_paper_records(
        paper["paper_id"],
        vector_records,
    )

    with CHUNKS_INDEX.open("w", encoding="utf-8") as stream:
        for record in old_chunks:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    old_papers = []
    if PAPERS_INDEX.is_file():
        with PAPERS_INDEX.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(record, dict)
                    and record.get("paper_id") != paper["paper_id"]
                ):
                    old_papers.append(record)
    old_papers.append(paper)
    with PAPERS_INDEX.open("w", encoding="utf-8") as stream:
        for record in old_papers:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "paper": paper,
        "page_count": len(pages),
        "chunk_count": len(chunk_records) + (1 if core_profile else 0),
        "vector_count": vector_count,
        "text_chars": sum(len(page["text"]) for page in pages),
    }
