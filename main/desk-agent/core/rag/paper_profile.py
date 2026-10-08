import json
import re
from typing import Any


PROFILE_FIELDS = (
    "research_problem",
    "core_work",
    "method",
    "findings",
    "contributions",
    "limitations",
    "evidence_pages",
)


def _paper_text(pages: list[dict[str, Any]], max_chars: int = 24000) -> str:
    parts = []
    total = 0
    for page in pages:
        text = str(page.get("text") or "").strip()
        if not text:
            continue
        part = f"[Page {page.get('page', 0)}]\n{text}"
        remaining = max_chars - total
        if remaining <= 0:
            break
        parts.append(part[:remaining])
        total += len(part)
    return "\n\n".join(parts)


def _fallback_profile(
    paper: dict[str, Any],
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    source = _paper_text(pages, max_chars=3000)
    return {
        "research_problem": "",
        "core_work": source,
        "method": "",
        "findings": "",
        "contributions": "",
        "limitations": "",
        "evidence_pages": [page.get("page", 0) for page in pages[:3]],
        "profile_source": "fallback_excerpt",
    }


def _parse_json_object(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


async def build_paper_profile(
    conn,
    paper: dict[str, Any],
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a compact paper-level record for literature retrieval."""
    fallback = _fallback_profile(paper, pages)
    llm = getattr(conn, "llm", None)
    if llm is None:
        return fallback

    source = _paper_text(pages)
    system_prompt = (
        "You are an academic literature analyst. "
        "Extract only claims supported by the supplied paper text. "
        "Return one valid JSON object and no Markdown."
    )
    user_prompt = (
        "Analyze this paper for literature-review retrieval. "
        "The core_work field must clearly answer: what problem does the paper "
        "solve, what does it propose or build, and what is the main result? "
        "Keep each text field concise but informative. "
        "evidence_pages must be an array of page numbers supporting core_work.\n"
        "Use exactly these JSON keys: "
        "research_problem, core_work, method, findings, contributions, "
        "limitations, evidence_pages.\n\n"
        f"Paper metadata: {json.dumps(paper, ensure_ascii=False)}\n\n"
        f"Paper text:\n{source}"
    )

    try:
        import asyncio

        raw = await asyncio.to_thread(
            llm.response_no_stream,
            system_prompt,
            user_prompt,
            max_tokens=1200,
            temperature=0.1,
        )
        parsed = _parse_json_object(raw)
        if not parsed or not str(parsed.get("core_work") or "").strip():
            return fallback

        profile = {
            key: parsed.get(key, "")
            for key in PROFILE_FIELDS
        }
        if not isinstance(profile["evidence_pages"], list):
            profile["evidence_pages"] = []
        profile["profile_source"] = "llm"
        return profile
    except Exception:
        return fallback


def profile_text(profile: dict[str, Any]) -> str:
    labels = {
        "research_problem": "Research problem",
        "core_work": "Core work",
        "method": "Method",
        "findings": "Findings",
        "contributions": "Contributions",
        "limitations": "Limitations",
    }
    parts = []
    for key, label in labels.items():
        value = str(profile.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts)
