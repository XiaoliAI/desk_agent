"""Remote embeddings for literature indexing and retrieval."""

import math
import os
import re
from pathlib import Path
from typing import Iterable

from config.config_loader import get_project_dir, merge_configs, read_config


DEFAULT_MODEL_NAME = "qwen3.7-text-embedding-flash"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _safe_error_details(error: Exception) -> str:
    details = str(error).replace("\r", " ").replace("\n", " ")[:500]
    details = re.sub(
        r"(?i)(authorization|api[-_ ]?key)(\s*[:=]\s*)([^,;\s]+)",
        r"\1\2[REDACTED]",
        details,
    )
    details = re.sub(
        r"\b(?:sk-[A-Za-z0-9_-]{12,}|ms-[A-Za-z0-9-]{12,})\b",
        "[REDACTED]",
        details,
    )
    return details


def _embedding_config() -> tuple[dict, dict]:
    root = Path(get_project_dir())
    config = merge_configs(
        read_config(root / "config.yaml"),
        read_config(root / "data" / ".config.yaml"),
    )
    settings = config.get("plugins", {}).get("literature_embedding", {})
    selected_llm = config.get("selected_module", {}).get("LLM", "")
    llm_settings = config.get("LLM", {}).get(selected_llm, {})
    return settings, llm_settings


class EmbeddingService:
    """Generate literature vectors through an OpenAI-compatible endpoint."""

    def __init__(
        self,
        model_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        batch_size: int = 16,
        client=None,
    ):
        from openai import OpenAI

        settings, llm_settings = _embedding_config()
        url = base_url or settings.get("base_url") or DEFAULT_BASE_URL
        self.model_name = (
            model_name
            or os.getenv("DESK_AGENT_EMBEDDING_MODEL")
            or settings.get("model_name")
            or DEFAULT_MODEL_NAME
        )
        key = (
            api_key
            or os.getenv("DESK_AGENT_EMBEDDING_API_KEY")
            or settings.get("api_key")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("MODELSCOPE_API_KEY")
        )
        llm_url = str(llm_settings.get("base_url") or "").rstrip("/")
        if not key and llm_url == str(url).rstrip("/"):
            key = llm_settings.get("api_key")
        if not key or str(key).startswith("YOUR_"):
            raise ValueError("Embedding API key is not configured")
        self.batch_size = int(batch_size)
        if self.batch_size < 1:
            raise ValueError("Embedding batch_size must be positive")
        self.client = client or OpenAI(
            api_key=key,
            base_url=url,
            timeout=30.0,
            max_retries=1,
        )
        self.dimension: int | None = None

    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        values = [str(text or "").strip() for text in texts]
        if not values:
            return []
        if any(not value for value in values):
            raise ValueError("Cannot embed empty text")

        vectors = []
        for start in range(0, len(values), self.batch_size):
            batch = values[start : start + self.batch_size]
            try:
                response = self.client.embeddings.create(
                    model=self.model_name,
                    input=batch,
                )
            except Exception as error:
                status = getattr(error, "status_code", None)
                code = getattr(error, "code", None)
                details = _safe_error_details(error)
                raise RuntimeError(
                    "Embedding request failed: "
                    f"type={type(error).__name__}, status={status}, "
                    f"code={code}, details={details}"
                ) from None

            data = response.data
            if len(data) != len(batch):
                raise ValueError("Embedding response count does not match input count")
            indices = [item.index for item in data]
            if sorted(indices) == list(range(len(batch))):
                ordered_data = sorted(data, key=lambda item: item.index)
            elif indices and all(index == 0 for index in indices):
                # DashScope text embeddings currently return index=0 for every
                # item while preserving input order.
                ordered_data = data
            else:
                raise ValueError("Embedding response indices are invalid")
            for item in ordered_data:
                vector = [float(number) for number in item.embedding]
                if not vector or not all(math.isfinite(number) for number in vector):
                    raise ValueError("Embedding response contains an invalid vector")
                norm = math.sqrt(sum(number * number for number in vector))
                if norm == 0:
                    raise ValueError("Embedding response contains a zero vector")
                if self.dimension is None:
                    self.dimension = len(vector)
                elif self.dimension != len(vector):
                    raise ValueError(
                        "Embedding response dimension changed within the service"
                    )
                vectors.append([number / norm for number in vector])

        if len({len(vector) for vector in vectors}) != 1:
            raise ValueError("Embedding response contains inconsistent dimensions")
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
