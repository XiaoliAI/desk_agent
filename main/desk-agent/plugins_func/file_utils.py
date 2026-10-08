import re
from difflib import SequenceMatcher
from pathlib import Path


DEFAULT_ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".docx",
    ".doc",
}

DEFAULT_ALLOWED_DIRECTORIES = [
    "data/desktop_files",
    "data/reports",
]

LATEST_REPORT_ALIASES = {
    "刚才生成的报告",
    "刚生成的报告",
    "刚才的报告",
    "最新生成的报告",
    "最新的报告",
    "最新报告",
}

TEMPORAL_HINTS = ("刚才", "刚刚", "最新", "最近")
QUERY_NOISE_WORDS = (
    "帮我",
    "请",
    "打开",
    "查看",
    "读取",
    "用wps",
    "用word",
    "使用wps",
    "使用word",
    "刚才生成的",
    "刚刚生成的",
    "最新生成的",
    "刚才的",
    "刚刚的",
    "最新的",
)
GENERIC_FILE_SUFFIXES = ("的文件", "文件", "文档", "报告", "汇报")


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_file_access_config(conn):
    return conn.config.get("plugins", {}).get("read_file", {})


def get_allowed_extensions(conn):
    config = get_file_access_config(conn)
    extensions = config.get(
        "allowed_extensions",
        list(DEFAULT_ALLOWED_EXTENSIONS),
    )

    normalized = set()
    for extension in extensions:
        value = str(extension).strip().lower()
        if value and not value.startswith("."):
            value = "." + value
        if value:
            normalized.add(value)

    return normalized or DEFAULT_ALLOWED_EXTENSIONS


def get_allowed_roots(conn):
    config = get_file_access_config(conn)
    directories = config.get(
        "allowed_directories",
        DEFAULT_ALLOWED_DIRECTORIES,
    )
    if not isinstance(directories, list):
        directories = DEFAULT_ALLOWED_DIRECTORIES

    project_root = get_project_root()
    roots = []
    for directory in directories:
        directory_path = Path(str(directory))
        if directory_path.is_absolute():
            continue

        root = (project_root / directory_path).resolve()
        root.mkdir(parents=True, exist_ok=True)
        roots.append(root)

    return roots


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def normalize_file_stem(value: str) -> str:
    """Normalize a file stem for case-insensitive, whitespace-free matching."""
    return re.sub(r"[\s_\-—–·.。]+", "", str(value or "")).casefold()


def normalize_query_stem(value: str) -> str:
    normalized = normalize_file_stem(value)
    for word in QUERY_NOISE_WORDS:
        normalized = normalized.replace(normalize_file_stem(word), "")
    return normalized


def semantic_file_stem(value: str, is_query: bool = False) -> str:
    normalized = (
        normalize_query_stem(value)
        if is_query
        else normalize_file_stem(value)
    )

    changed = True
    while normalized and changed:
        changed = False
        for suffix in GENERIC_FILE_SUFFIXES:
            normalized_suffix = normalize_file_stem(suffix)
            if normalized.endswith(normalized_suffix):
                normalized = normalized[: -len(normalized_suffix)]
                changed = True
                break

    return normalized


def file_match_score(requested_stem: str, candidate_stem: str) -> float:
    query = normalize_query_stem(requested_stem)
    candidate = normalize_file_stem(candidate_stem)
    if not query or not candidate:
        return 0.0

    if query == candidate:
        return 1.0

    length_ratio = min(len(query), len(candidate)) / max(len(query), len(candidate))
    if candidate.startswith(query) or query.startswith(candidate):
        return 0.92 + (0.07 * length_ratio)
    if query in candidate or candidate in query:
        return 0.82 + (0.08 * length_ratio)

    query_core = semantic_file_stem(query, is_query=True)
    candidate_core = semantic_file_stem(candidate)
    if query_core and query_core == candidate_core:
        return 0.91
    if query_core and candidate_core:
        core_length_ratio = min(len(query_core), len(candidate_core)) / max(
            len(query_core), len(candidate_core)
        )
        if query_core in candidate_core or candidate_core in query_core:
            return 0.80 + (0.09 * core_length_ratio)

    full_ratio = SequenceMatcher(None, query, candidate).ratio()
    core_ratio = SequenceMatcher(None, query_core, candidate_core).ratio()
    return max(full_ratio, core_ratio) * 0.82


def collect_stem_matches(
    roots,
    requested: Path,
    allowed_extensions,
    prefer_latest: bool = False,
):
    """Rank safe files using fuzzy spoken-name matching."""
    requested_stem = requested.stem if requested.suffix else requested.name
    requested_suffix = requested.suffix.lower()
    candidates = []

    for root in roots:
        search_root = root
        if len(requested.parts) > 1:
            candidate_parent = (get_project_root() / requested.parent).resolve()
            if is_inside(candidate_parent, root):
                search_root = candidate_parent
            else:
                continue

        for candidate in search_root.rglob("*"):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in allowed_extensions:
                continue
            if requested_suffix and candidate.suffix.lower() != requested_suffix:
                continue
            resolved = candidate.resolve()
            if not is_inside(resolved, root):
                continue
            if resolved not in candidates:
                candidates.append(resolved)

    scored = [
        (file_match_score(requested_stem, path.stem), path)
        for path in candidates
    ]
    scored = [item for item in scored if item[0] >= 0.55]
    scored.sort(
        key=lambda item: (item[0], item[1].stat().st_mtime),
        reverse=True,
    )
    if not scored:
        return []

    top_score = scored[0][0]
    close_matches = [item for item in scored if top_score - item[0] < 0.08]
    if prefer_latest:
        latest = max(close_matches, key=lambda item: item[1].stat().st_mtime)
        return [latest[1]]

    if len(close_matches) == 1:
        return [scored[0][1]]

    return [path for _, path in close_matches[:5]]


def find_latest_report(roots):
    reports = []
    for root in roots:
        for candidate in root.rglob("*.docx"):
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if is_inside(resolved, root):
                reports.append(resolved)

    if not reports:
        return None

    return max(reports, key=lambda path: path.stat().st_mtime)


def resolve_requested_file(conn, file_name: str):
    """Resolve a file inside safe directories, with optional suffix omission."""
    value = str(file_name or "").strip().strip("\"'")
    if not value:
        return None, "文件名不能为空"
    if "\x00" in value:
        return None, "文件名包含非法字符"

    requested = Path(value)
    if requested.is_absolute():
        return None, "不允许访问绝对路径"
    if ".." in requested.parts:
        return None, "文件路径不能包含.."

    allowed_extensions = get_allowed_extensions(conn)
    roots = get_allowed_roots(conn)
    prefer_latest = any(hint in value for hint in TEMPORAL_HINTS)

    normalized_value = normalize_file_stem(value)
    normalized_aliases = {
        normalize_file_stem(alias) for alias in LATEST_REPORT_ALIASES
    }
    if normalized_value in normalized_aliases:
        latest = find_latest_report(roots)
        if latest is None:
            return None, "安全目录中还没有可打开的Word报告"
        return latest, None

    suffix = requested.suffix.lower()
    if suffix and suffix not in allowed_extensions:
        allowed = "、".join(sorted(allowed_extensions))
        return None, f"暂不支持访问{suffix}文件，只支持：{allowed}"

    existing = []
    if suffix:
        project_root = get_project_root()
        candidates = [(project_root / requested).resolve()]
        candidates.extend((root / requested).resolve() for root in roots)

        for candidate in candidates:
            if not candidate.is_file():
                continue
            if not any(is_inside(candidate, root) for root in roots):
                continue
            if candidate not in existing:
                existing.append(candidate)

    if not existing:
        existing = collect_stem_matches(
            roots,
            requested,
            allowed_extensions,
            prefer_latest=prefer_latest,
        )

    if not existing:
        return None, f"安全目录中找不到文件：{value}"
    if len(existing) > 1:
        paths = "；".join(str(path) for path in existing[:5])
        return None, f"找到多个相似文件，请说得更具体一些：{paths}"

    return existing[0], None
