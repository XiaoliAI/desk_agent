import asyncio
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from config.logger import setup_logging
from plugins_func.file_utils import is_inside
from plugins_func.functions.search_local_files import (
    get_allowed_extensions,
    get_allowed_roots,
    search_files,
)
from plugins_func.register import Action, ActionResponse, ToolType, register_function

if TYPE_CHECKING:
    from core.connection import ConnectionHandler


TAG = __name__
SUPPORTED_EXTENSIONS = {".doc", ".docx"}
logger = setup_logging()
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_TEXT = f"{{{WORD_NS}}}t"

REPLACE_DOCUMENT_DESC = {
    "type": "function",
    "function": {
        "name": "replace_document_text",
        "description": (
            "Find and replace explicit text in a Word document. "
            "Supports .doc and .docx. The source file is never overwritten."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "Word file name or fuzzy file name.",
                },
                "old_text": {
                    "type": "string",
                    "description": "Exact text to replace.",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text. Empty means delete.",
                },
                "output_file_name": {
                    "type": "string",
                    "description": "Optional output file name.",
                },
            },
            "required": ["file_name", "old_text", "new_text"],
        },
    },
}


def _resolve_document(conn, file_name: str) -> Path:
    query = str(file_name or "").strip().strip("\"'")
    if not query:
        raise ValueError("file_name is required")

    requested_suffix = Path(query).suffix.lower()
    if requested_suffix and requested_suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Only .doc and .docx files can be modified")

    allowed_extensions = get_allowed_extensions(conn) & SUPPORTED_EXTENSIONS
    if not allowed_extensions:
        raise ValueError("No editable Word extension is enabled")

    matches = search_files(conn, query)
    paths = [
        item["path"]
        for item in matches
        if item["path"].suffix.lower() in allowed_extensions
    ]
    if not paths:
        raise FileNotFoundError(f"Word document not found: {query}")

    query_name = Path(query).name.casefold()
    exact = [path for path in paths if path.name.casefold() == query_name]
    if len(exact) == 1:
        return exact[0]
    if len(paths) > 1:
        names = ", ".join(path.name for path in paths[:5])
        raise ValueError(f"Multiple matching Word documents: {names}")
    return paths[0]


def _output_path(conn, source: Path, output_file_name: str) -> Path:
    raw_name = str(output_file_name or "").strip()
    if raw_name:
        name = Path(raw_name).name
        if name in {"", ".", ".."} or name != raw_name:
            raise ValueError("output_file_name must be a file name only")
        if Path(name).suffix.lower() != source.suffix.lower():
            raise ValueError("Output extension must match the source extension")
    else:
        name = f"{source.stem}_edit{source.suffix}"

    target = source.with_name(name).resolve()
    roots = get_allowed_roots(conn)
    if not any(is_inside(target, root) for root in roots):
        raise PermissionError("Output is outside the allowed safe directories")
    if target == source:
        raise ValueError("The source file cannot be overwritten")
    if target.exists():
        target = target.with_name(
            f"{target.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{target.suffix}"
        )
    return target


def _iter_story_ranges(document):
    """Yield Word body, table, header, footer, comment and text-box ranges."""
    stories = document.StoryRanges
    for index in range(1, stories.Count + 1):
        try:
            current = stories.Item(index)
        except Exception:
            continue
        while current is not None:
            yield current
            try:
                current = current.NextStoryRange
            except Exception:
                current = None


def _replace_in_range(text_range, old_text: str, new_text: str) -> bool:
    find = text_range.Find
    find.ClearFormatting()
    find.Replacement.ClearFormatting()
    find.Text = old_text
    find.Replacement.Text = new_text
    find.Forward = True
    find.Wrap = 1
    find.Format = False
    find.MatchCase = False
    find.MatchWholeWord = False
    return bool(find.Execute(Replace=2))


def _close_word(word, document):
    if document is not None:
        try:
            document.Close(SaveChanges=False)
        except Exception:
            pass
    if word is not None:
        try:
            word.Quit()
        except Exception:
            pass


def _replace_in_xml(xml_data: bytes, old_text: str, new_text: str):
    """Replace text across split Word runs without starting Word/WPS."""
    try:
        root = ElementTree.fromstring(xml_data)
    except ElementTree.ParseError:
        return xml_data, 0

    text_nodes = [node for node in root.iter() if node.tag == W_TEXT]
    entries = []
    full_text_parts = []
    offset = 0
    for node in text_nodes:
        text = node.text or ""
        if not text:
            continue
        entries.append((node, offset, offset + len(text), text))
        full_text_parts.append(text)
        offset += len(text)

    full_text = "".join(full_text_parts)
    if not full_text or old_text not in full_text:
        return xml_data, 0

    matches = []
    start = 0
    while True:
        position = full_text.find(old_text, start)
        if position < 0:
            break
        matches.append((position, position + len(old_text)))
        start = position + len(old_text)

    # Apply from right to left so offsets before each match remain stable.
    for match_start, match_end in reversed(matches):
        first_index = next(
            index
            for index, (_, begin, end, _) in enumerate(entries)
            if begin <= match_start < end
        )
        last_index = next(
            index
            for index, (_, begin, end, _) in enumerate(entries)
            if begin < match_end <= end
        )

        first_node, first_begin, _, first_original = entries[first_index]
        last_node, last_begin, _, last_original = entries[last_index]
        first_offset = match_start - first_begin
        last_offset = match_end - last_begin

        if first_index == last_index:
            first_node.text = (
                first_original[:first_offset]
                + new_text
                + first_original[last_offset:]
            )
        else:
            first_node.text = (
                first_original[:first_offset]
                + new_text
                + last_original[last_offset:]
            )
            for index in range(first_index + 1, last_index + 1):
                entries[index][0].text = ""

    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True), len(matches)


def _replace_in_docx(source: Path, target: Path, old_text: str, new_text: str):
    replaced_count = 0
    with zipfile.ZipFile(source, "r") as source_zip:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
            for info in source_zip.infolist():
                content = source_zip.read(info.filename)
                if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                    content, count = _replace_in_xml(content, old_text, new_text)
                    replaced_count += count
                target_zip.writestr(info, content)

    if replaced_count == 0:
        raise ValueError(f"Text not found in DOCX document: {old_text}")
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError("The DOCX output file was not created")


def _replace_with_word(source: Path, target: Path, old_text: str, new_text: str):
    try:
        import pythoncom
        import win32com.client
    except ImportError as error:
        raise RuntimeError(
            "pywin32 is required: python -m pip install pywin32"
        ) from error

    pythoncom.CoInitialize()
    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(str(source), ReadOnly=False)

        replaced = False
        for text_range in _iter_story_ranges(document):
            try:
                replaced = _replace_in_range(text_range, old_text, new_text) or replaced
            except Exception as error:
                logger.bind(tag=TAG).debug(f"Skipping non-editable Word story: {error}")
        if not replaced:
            raise ValueError(f"Text not found in document: {old_text}")

        file_format = 0 if source.suffix.lower() == ".doc" else 16
        document.SaveAs2(FileName=str(target), FileFormat=file_format)
        _close_word(word, document)
        word = None
        document = None

        if not target.is_file() or target.stat().st_size == 0:
            raise ValueError("Word did not create a valid output file")
        return target
    finally:
        _close_word(word, document)
        pythoncom.CoUninitialize()


def _replace_document(source: Path, target: Path, old_text: str, new_text: str):
    if source.suffix.lower() == ".docx":
        return _replace_in_docx(source, target, old_text, new_text)
    return _replace_with_word(source, target, old_text, new_text)


@register_function(
    "replace_document_text",
    REPLACE_DOCUMENT_DESC,
    ToolType.SYSTEM_CTL,
)
async def replace_document_text(
    conn: "ConnectionHandler",
    file_name: str,
    old_text: str,
    new_text: str,
    output_file_name: str = "",
):
    target = None
    try:
        old_text = str(old_text or "")
        if not old_text.strip():
            raise ValueError("old_text is required")
        source = await asyncio.to_thread(_resolve_document, conn, file_name)
        target = _output_path(conn, source, output_file_name)
        await asyncio.to_thread(
            _replace_document, source, target, old_text, str(new_text or "")
        )
        message = f"Replaced text in {source.name}; output: {target.name}"
        logger.bind(tag=TAG).info(
            f"document replacement saved: source={source}, target={target}, old_text={old_text}"
        )
        return ActionResponse(action=Action.RESPONSE, result=message, response=message)
    except Exception as error:
        if target is not None and target.exists():
            try:
                target.unlink()
            except OSError:
                logger.bind(tag=TAG).warning(f"Could not remove failed output: {target}")
        message = f"Document replacement failed: {error}"
        logger.bind(tag=TAG).error(message)
        return ActionResponse(action=Action.ERROR, result=message, response=message)
