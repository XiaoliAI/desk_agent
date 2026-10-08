import asyncio
import html
import os
import platform
import re
import subprocess
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from config.logger import setup_logging
from plugins_func.register import (
    register_function,
    ToolType,
    ActionResponse,
    Action,
)

if TYPE_CHECKING:
    from core.connection import ConnectionHandler


TAG = __name__
logger = setup_logging()


GENERATE_REPORT_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "generate_report",
        "description": (
            "根据用户给出的主题自动生成中文汇报或报告，保存为Word文档并打开。"
            "适用于生成AI汇报、学习报告、项目总结、会议纪要等。"
            "用户提出写报告、写汇报、生成Word文档时调用。"
            "如果用户指定字数，使用word_count参数；如果没有指定，默认生成约100字。"
            "如果用户说打开Word，editor使用word；如果说打开WPS，editor使用wps；"
            "没有指定编辑器时使用系统默认程序打开docx文件。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "报告主题，例如人工智能、Python学习、项目进展",
                },
                "word_count": {
                    "type": "integer",
                    "description": "正文目标汉字数，例如100。未指定时使用100。",
                },
                "file_name": {
                    "type": "string",
                    "description": "可选的Word文件名，例如AI汇报.docx。不提供时自动生成。",
                },
                "editor": {
                    "type": "string",
                    "description": "可选值：default、word、wps。默认使用系统默认程序。",
                },
                "open_after_create": {
                    "type": "boolean",
                    "description": "是否在生成后打开Word文档，默认true。",
                },
            },
            "required": ["topic"],
        },
    },
}


EDITOR_ALIASES = {
    "默认": "default",
    "默认程序": "default",
    "默认编辑器": "default",
    "default": "default",
    "word": "word",
    "microsoftword": "word",
    "微软word": "word",
    "微软office": "word",
    "office": "word",
    "wps": "wps",
    "wpsoffice": "wps",
}


INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "lpt1",
    "lpt2",
    "lpt3",
}


def get_report_config(conn):
    return conn.config.get("plugins", {}).get("generate_report", {})


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_editor(editor: str | None) -> str:
    value = str(editor or "default").strip().lower().replace(" ", "")
    return EDITOR_ALIASES.get(value, value)


def count_chinese_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def clean_report_text(text: str) -> str:
    """清理模型可能返回的Markdown围栏和多余前缀。"""
    value = str(text or "").strip()
    value = re.sub(r"^```(?:text|markdown)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    value = re.sub(r"^(正文|报告正文|内容)\s*[:：]\s*", "", value)
    return value.strip()


def build_report_filename(topic: str, file_name: str | None) -> str:
    if file_name and str(file_name).strip():
        name = Path(str(file_name).strip()).name
    else:
        short_topic = re.sub(r"\s+", "", str(topic or "人工智能"))
        short_topic = short_topic[:24] or "报告"
        name = f"{short_topic}_汇报.docx"

    name = name.strip()
    if not name.lower().endswith(".docx"):
        name += ".docx"

    stem = Path(name).stem
    suffix = Path(name).suffix
    if (
        not stem
        or stem.lower() in WINDOWS_RESERVED_NAMES
        or any(char in name for char in INVALID_FILENAME_CHARS)
    ):
        name = f"报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    else:
        name = f"{stem}{suffix}"

    return name


def get_report_path(conn, topic: str, file_name: str | None) -> Path:
    config = get_report_config(conn)
    output_dir = str(config.get("output_dir", "data/reports"))
    root = get_project_root()
    report_root = (root / output_dir).resolve()
    report_root.mkdir(parents=True, exist_ok=True)

    report_name = build_report_filename(topic, file_name)
    target = (report_root / report_name).resolve()

    try:
        target.relative_to(report_root)
    except ValueError:
        raise ValueError("报告保存路径不安全")

    # 默认不覆盖旧报告，避免误删用户已经生成的内容。
    if target.exists():
        target = target.with_name(
            f"{target.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            f"{target.suffix}"
        )

    return target


def xml_text(value: str) -> str:
    """清除Word XML不允许的控制字符并进行XML转义。"""
    cleaned = "".join(
        char
        for char in str(value or "")
        if char in "\t\n\r" or ord(char) >= 0x20
    )
    return html.escape(cleaned, quote=False)


def make_word_paragraph(text: str, style: str | None = None) -> str:
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    if not text:
        return f"<w:p><w:pPr>{style_xml}</w:pPr></w:p>"

    return (
        f"<w:p><w:pPr>{style_xml}</w:pPr>"
        f'<w:r><w:t xml:space="preserve">{xml_text(text)}</w:t></w:r>'
        f"</w:p>"
    )


def write_docx(path: Path, title: str, content: str):
    """使用标准库生成最小可打开的Word .docx文档。"""
    document_parts = [make_word_paragraph(title, "Title")]
    for line in content.splitlines():
        document_parts.append(make_word_paragraph(line))

    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {"".join(document_parts)}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"
               w:header="708" w:footer="708" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
            ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

    package_relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>
"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.docx")

    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_relationships)
        archive.writestr("word/document.xml", document_xml)

    temp_path.replace(path)


def configured_editor_path(conn, editor: str) -> str | None:
    config = get_report_config(conn)
    open_application_config = conn.config.get("plugins", {}).get(
        "open_application", {}
    )
    paths = open_application_config.get("paths", {})

    configured = config.get(f"{editor}_path") or paths.get(editor)
    if configured:
        return os.path.expandvars(os.path.expanduser(str(configured)))

    if editor == "word":
        candidates = [
            Path(os.environ.get("ProgramFiles", ""))
            / "Microsoft Office/root/Office16/WINWORD.EXE",
            Path(os.environ.get("ProgramFiles(x86)", ""))
            / "Microsoft Office/root/Office16/WINWORD.EXE",
            Path(os.environ.get("ProgramW6432", ""))
            / "Microsoft Office/root/Office16/WINWORD.EXE",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)

    if editor == "wps":
        install_roots = [
            Path(os.environ.get("ProgramFiles", "")),
            Path(os.environ.get("ProgramFiles(x86)", "")),
            Path(os.environ.get("LOCALAPPDATA", "")),
        ]
        patterns = [
            "WPS Office/*/office6/wps.exe",
            "Kingsoft/WPS Office/*/office6/wps.exe",
            "Kingsoft/WPS Office/office6/wps.exe",
        ]
        candidates = []
        for install_root in install_roots:
            if not str(install_root):
                continue
            for pattern in patterns:
                candidates.extend(install_root.glob(pattern))

        existing = [path for path in candidates if path.is_file()]
        if existing:
            newest = max(existing, key=lambda path: path.stat().st_mtime)
            return str(newest)

    return None


def open_document(conn, document_path: Path, editor: str):
    editor = normalize_editor(editor)

    if platform.system() != "Windows":
        raise RuntimeError("当前文档打开功能只支持Windows系统")

    if editor == "default":
        os.startfile(str(document_path))
        return "系统默认程序"

    if editor not in {"word", "wps"}:
        raise ValueError("编辑器只支持default、word或wps")

    editor_path = configured_editor_path(conn, editor)
    if not editor_path:
        raise FileNotFoundError(
            f"没有找到{editor}程序，请在data/.config.yaml中配置"
            f"plugins.open_application.paths.{editor}"
        )

    if not os.path.isfile(editor_path):
        raise FileNotFoundError(f"找不到{editor}程序：{editor_path}")

    subprocess.Popen([editor_path, str(document_path)], shell=False)
    return editor


async def generate_report_content(
    conn: "ConnectionHandler",
    topic: str,
    word_count: int,
    source_material: str = "",
) -> str:
    if conn.llm is None:
        raise RuntimeError("LLM尚未初始化，无法生成报告")

    system_prompt = (
        "你是一个严谨、简洁的中文报告写作助手。"
        "你的输出会直接保存到Word文档中。"
        "不要输出思考过程、标题、Markdown符号、引号或说明文字，只输出正文。"
    )
    user_prompt = (
        f"请围绕“{topic}”写一段适合工作汇报的中文正文。"
        f"目标长度约为{word_count}个汉字，允许上下浮动10%。"
        "内容要完整、客观、适合向老师或领导汇报。"
        "正文至少包含背景/现状、核心内容、价值或下一步中的主要信息。"
        "只返回正文，不要返回标题和字数说明。"
    )

    max_tokens = max(300, min(2400, int(word_count * 2.5)))
    result = await asyncio.to_thread(
        conn.llm.response_no_stream,
        system_prompt,
        user_prompt,
        max_tokens=max_tokens,
        temperature=0.4,
    )
    content = clean_report_text(result)

    # 只有长度明显偏离时才二次压缩/扩写，避免无意义增加请求次数。
    actual_count = count_chinese_chars(content)
    tolerance = max(15, int(word_count * 0.2))
    if content and abs(actual_count - word_count) > tolerance:
        refine_prompt = (
            f"请把下面这段中文正文调整到约{word_count}个汉字，"
            "保留核心事实和汇报语气，只输出调整后的正文，不要标题和解释：\n"
            f"{content}"
        )
        refined = await asyncio.to_thread(
            conn.llm.response_no_stream,
            system_prompt,
            refine_prompt,
            max_tokens=max_tokens,
            temperature=0.2,
        )
        refined = clean_report_text(refined)
        if refined:
            content = refined

    if not content:
        raise RuntimeError("LLM没有生成有效的报告正文")

    return content


@register_function(
    "generate_report",
    GENERATE_REPORT_FUNCTION_DESC,
    ToolType.SYSTEM_CTL,
)
async def generate_report(
    conn: "ConnectionHandler",
    topic: str,
    word_count: int = 100,
    file_name: str | None = None,
    editor: str = "default",
    open_after_create: bool = True,
):
    """生成报告正文、创建Word文档并按需打开。"""
    topic = str(topic or "").strip()
    if not topic:
        return ActionResponse(
            action=Action.RESPONSE,
            result="报告主题不能为空",
            response="报告主题不能为空",
        )

    try:
        word_count = int(word_count or 100)
    except (TypeError, ValueError):
        word_count = 100

    config = get_report_config(conn)
    try:
        max_word_count = int(config.get("max_word_count", 2000))
    except (TypeError, ValueError):
        max_word_count = 2000

    word_count = max(20, min(word_count, max_word_count))

    try:
        content = await generate_report_content(conn, topic, word_count)
        report_path = get_report_path(conn, topic, file_name)
        title = f"关于{topic}的汇报"
        write_docx(report_path, title, content)

        actual_count = count_chinese_chars(content)
        opened_message = ""

        should_open = (
            open_after_create
            if open_after_create is not None
            else bool(config.get("open_after_create", True))
        )
        if should_open:
            try:
                editor_name = open_document(conn, report_path, editor)
                opened_message = f"，已使用{editor_name}打开"
            except Exception as open_error:
                logger.bind(tag=TAG).warning(
                    f"报告已生成但打开编辑器失败: {open_error}"
                )
                opened_message = "，但自动打开编辑器失败，请检查Word/WPS路径配置"

        message = (
            f"报告已生成，正文约{actual_count}字，"
            f"文件已保存为{report_path.name}{opened_message}"
        )
        logger.bind(tag=TAG).info(
            f"生成报告成功: topic={topic}, path={report_path}, "
            f"target_count={word_count}, actual_count={actual_count}, editor={editor}"
        )

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    except Exception as error:
        message = f"生成报告失败：{error}"
        logger.bind(tag=TAG).error(message)
        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )
