#创建本地 Chroma
#→ 写入向量
#→ 删除旧论文向量
#→ 按 paper_id 过滤
#→ 语义检索
#→ 返回文本、页码、论文编号和相似度

from pathlib import Path
from typing import Any

from core.rag.embeddings import EmbeddingService


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHROMA_PATH = (
    PROJECT_ROOT / "data" / "literature" / "chroma"
)
DEFAULT_COLLECTION_NAME = "literature"


class ChromaVectorStore:
    """Persistent Chroma vector store for literature retrieval."""

    def __init__(
        self,
        persist_directory: str | Path = DEFAULT_CHROMA_PATH,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        embedding_service: EmbeddingService | None = None,
    ):
        import chromadb
        from chromadb.config import Settings

        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.embedding_service = (
            embedding_service or EmbeddingService()
        )

        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=Settings(anonymized_telemetry=False),
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine",
            },
        )

    @staticmethod
    def _metadata_from_record(
        record: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = {}

        for key, value in record.items():
            if key in {"id", "chunk_id", "text"}:
                continue

            if value is None:
                continue

            if isinstance(value, (str, int, float, bool)):
                metadata[key] = value
                continue

            if isinstance(value, (list, tuple)):
                metadata[key] = ", ".join(
                    str(item) for item in value
                )
                continue

            metadata[key] = str(value)

        if not metadata:
            metadata["source"] = "literature"

        return metadata

    @staticmethod
    def _record_id(record: dict[str, Any]) -> str:
        value = (
            record.get("id")
            or record.get("chunk_id")
        )

        if not value:
            raise ValueError(
                "Each vector record requires id or chunk_id"
            )

        return str(value)

    @staticmethod
    def _record_text(record: dict[str, Any]) -> str:
        text = str(record.get("text") or "").strip()

        if not text:
            raise ValueError(
                "Each vector record requires non-empty text"
            )

        return text

    def upsert_records(
        self,
        records: list[dict[str, Any]],
    ) -> int:
        if not records:
            return 0

        ids = [
            self._record_id(record)
            for record in records
        ]

        documents = [
            self._record_text(record)
            for record in records
        ]

        metadatas = [
            self._metadata_from_record(record)
            for record in records
        ]

        embeddings = (
            self.embedding_service.embed_documents(
                documents
            )
        )
        for metadata in metadatas:
            metadata["embedding_model"] = self.embedding_service.model_name
            metadata["embedding_dimension"] = len(embeddings[0])

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        return len(records)

    def replace_paper_records(
        self,
        paper_id: str,
        records: list[dict[str, Any]],
    ) -> int:
        """Replace one paper's vectors while removing records no longer present."""
        paper_id = str(paper_id or "").strip()
        if not paper_id:
            raise ValueError("paper_id is required")

        for record in records:
            if str(record.get("paper_id") or "") != paper_id:
                raise ValueError("All vector records must belong to the same paper")

        existing = self.collection.get(where={"paper_id": paper_id})
        old_ids = set(existing.get("ids") or [])
        new_ids = {self._record_id(record) for record in records}

        written = self.upsert_records(records)
        stale_ids = sorted(old_ids - new_ids)
        self.delete_by_ids(stale_ids)
        return written

    def delete_by_paper_id(
        self,
        paper_id: str,
    ) -> None:
        self.collection.delete(
            where={
                "paper_id": str(paper_id),
            }
        )

    def delete_by_ids(
        self,
        ids: list[str],
    ) -> None:
        if ids:
            self.collection.delete(
                ids=[str(item) for item in ids]
            )

    def count(self) -> int:
        return self.collection.count()

    def get_records(
        self,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch stored records by metadata for deterministic evidence recovery."""
        query_kwargs: dict[str, Any] = {
            "include": ["documents", "metadatas"],
        }
        if where:
            query_kwargs["where"] = where
        raw = self.collection.get(**query_kwargs)
        ids = raw.get("ids") or []
        documents = raw.get("documents") or []
        metadatas = raw.get("metadatas") or []
        return [
            {
                "id": record_id,
                "text": documents[index] if index < len(documents) else "",
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "distance": None,
                "score": None,
            }
            for index, record_id in enumerate(ids)
        ]

    def close(self) -> None:
        """Release Chroma resources, mainly for commands and tests."""
        from chromadb.api.shared_system_client import SharedSystemClient

        self.client._system.stop()
        SharedSystemClient.clear_system_cache()

    def search(
        self,
        query: str,
        top_k: int = 6,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        query_vector = (
            self.embedding_service.embed_query(query)
        )

        if not query_vector:
            return []

        return self.search_by_vector(query_vector, top_k, where)

    def search_by_vector(
        self,
        query_vector: list[float],
        top_k: int = 6,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search with a precomputed query vector so multiple routes share one API call."""
        if self.collection.count() == 0 or not query_vector:
            return []

        query_kwargs = {
            "query_embeddings": [query_vector],
            "n_results": max(1, int(top_k)),
            "include": [
                "documents",
                "metadatas",
                "distances",
            ],
        }

        if where:
            query_kwargs["where"] = where

        raw = self.collection.query(**query_kwargs)

        ids = raw.get("ids", [[]])[0]
        documents = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]

        results = []

        for index, record_id in enumerate(ids):
            distance = (
                distances[index]
                if index < len(distances)
                else None
            )

            similarity = (
                1.0 - float(distance)
                if distance is not None
                else None
            )

            results.append(
                {
                    "id": record_id,
                    "text": documents[index]
                    if index < len(documents)
                    else "",
                    "metadata": metadatas[index]
                    if index < len(metadatas)
                    else {},
                    "distance": distance,
                    "score": similarity,
                }
            )

        return results
