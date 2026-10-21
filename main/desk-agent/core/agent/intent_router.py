#这是一个“规则优先”的意图识别模块：先用关键词快速判断用户想干什么并抽取参数，规则搞不定时再交给大模型。 它属于智能助手/Agent 系统中的“意图路由”层
import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class IntentResult:
    name: str
    confidence: float
    entities: dict[str, Any]
    missing_fields: list[str]
    raw_text: str = ""

    @property
    def requires_tool(self) -> bool:
        return self.name not in {"chat", "unknown"}


class IntentRouter:
    """
    对用户请求进行轻量意图识别。

    第一版使用规则快速识别高确定性命令，
    无法确定时再交给LLM。
    """

    INTENTS = {
        "chat",
        "open_application",
        "open_website",
        "open_file",
        "search_local_file",
        "send_file_email",
        "edit_document",
        "edit_document_and_send",
        "generate_report",
        "import_literature",
        "search_literature",
        "weather",
        "web_search",
        "confirm_task",
        "cancel_task",
        "select_file",
        "unknown",
    }

    def classify_fast(self, text: str) -> IntentResult | None:
        value = self._normalize(text)

        if not value:
            return None

        if self._is_literature_import(value):
            return IntentResult(
                name="import_literature",
                confidence=0.97,
                entities={"file_query": self._extract_file_query(text) or text},
                missing_fields=[],
                raw_text=text,
            )

        if self._is_literature_search(value):
            return IntentResult(
                name="search_literature",
                confidence=0.96,
                entities={"query": self._extract_literature_query(text)},
                missing_fields=[],
                raw_text=text,
            )

        if self._is_cancel(value):
            return IntentResult(
                name="cancel_task",
                confidence=0.99,
                entities={},
                missing_fields=[],
                raw_text=text,
            )

        if self._is_confirm(value):
            return IntentResult(
                name="confirm_task",
                confidence=0.99,
                entities={},
                missing_fields=[],
                raw_text=text,
            )

        if self._is_file_selection(value):
            return IntentResult(
                name="select_file",
                confidence=0.99,
                entities={"selection": value},
                missing_fields=[],
                raw_text=text,
            )

        if self._contains_any(value, ["天气", "气温", "下雨", "温度"]):
            return IntentResult(
                name="weather",
                confidence=0.95,
                entities={"location": self._extract_location(text)},
                missing_fields=[],
                raw_text=text,
            )

        if self._contains_any(value, ["搜索", "查一下新闻", "联网搜", "网上查"]):
            return IntentResult(
                name="web_search",
                confidence=0.92,
                entities={"query": text},
                missing_fields=[],
                raw_text=text,
            )

        if self._contains_any(value, ["打开网页", "打开网站", "访问网站"]):
            return IntentResult(
                name="open_website",
                confidence=0.95,
                entities={"url": self._extract_url(text)},
                missing_fields=[],
                raw_text=text,
            )

        if self._contains_any(value, ["打开qq", "打开微信", "打开浏览器", "打开wps"]):
            return IntentResult(
                name="open_application",
                confidence=0.96,
                entities={"application": self._extract_application(text)},
                missing_fields=[],
                raw_text=text,
            )

        has_file = self._contains_any(
            value,
            ["文件", "成绩单", "简历", "报告", "文档", "资料", "桌面的", "桌面上的", ".doc", ".rtf"],
        ) or bool(re.search(r"(?:里面|里的|中的|里|中).*(?:改成|改为|换成|变成|替换|修改|删除|移除)", value))
        has_send = self._contains_any(
            value,
            [
                "发给我",
                "发送给我",
                "发到邮箱",
                "发送到邮箱",
                "发到我的邮箱",
                "发送到我的邮箱",
                "到我的邮箱",
                "到我邮箱",
                "邮件发送",
            ],
        )
        has_edit = self._contains_any(
            value,
            [
                "修改",
                "改成",
                "改为",
                "换成",
                "变成",
                "替换",
                "从",
                "把名字改",
                "修改内容",
                "删除",
                "移除",
            ],
        )

        if has_file and has_edit and has_send:
            old_text, new_text = self._extract_edit_pair(text)
            return IntentResult(
                name="edit_document_and_send",
                confidence=0.97,
                entities={
                    "file_query": self._extract_file_query(text),
                    "old_text": old_text,
                    "new_text": new_text,
                    "receiver": "default",
                },
                missing_fields=self._edit_missing_fields(old_text, new_text),
                raw_text=text,
            )

        if has_file and has_edit:
            old_text, new_text = self._extract_edit_pair(text)
            return IntentResult(
                name="edit_document",
                confidence=0.95,
                entities={
                    "file_query": self._extract_file_query(text),
                    "old_text": old_text,
                    "new_text": new_text,
                },
                missing_fields=self._edit_missing_fields(old_text, new_text),
                raw_text=text,
            )

        if has_file and has_send:
            return IntentResult(
                name="send_file_email",
                confidence=0.97,
                entities={
                    "file_query": self._extract_file_query(text),
                    "receiver": "default",
                },
                missing_fields=[],
                raw_text=text,
            )

        if has_file and self._contains_any(value, ["查找", "寻找", "找一下"]):
            return IntentResult(
                name="search_local_file",
                confidence=0.94,
                entities={"query": self._extract_file_query(text)},
                missing_fields=[],
                raw_text=text,
            )

        if self._contains_any(
            value,
            ["写一份报告", "生成报告", "写一份汇报", "生成汇报"],
        ):
            return IntentResult(
                name="generate_report",
                confidence=0.94,
                entities={"topic": text},
                missing_fields=[],
                raw_text=text,
            )

        if self._contains_any(value, ["打开文件", "打开文档", "查看文件"]):
            return IntentResult(
                name="open_file",
                confidence=0.90,
                entities={"file_query": self._extract_file_query(text)},
                missing_fields=[],
                raw_text=text,
            )

        if has_file and "打开" in value:
            return IntentResult(
                name="open_file",
                confidence=0.90,
                entities={"file_query": self._extract_file_query(text)},
                missing_fields=[],
                raw_text=text,
            )

        return None

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", "", str(text or "").casefold())

    @staticmethod
    def _contains_any(text: str, values: list[str]) -> bool:
        return any(value.casefold() in text for value in values)

    @staticmethod
    def _is_literature_import(value: str) -> bool:
        return (
            "\u5bfc\u5165" in value
            and (
                ".pdf" in value
                or "\u8bba\u6587" in value
                or "\u6587\u732e" in value
            )
        )

    @staticmethod
    def _is_literature_search(value: str) -> bool:
        has_literature = any(
            token in value
            for token in (
                "\u8bba\u6587",
                "\u6587\u732e",
                "\u7814\u7a76\u5de5\u4f5c",
                "\u6838\u5fc3\u5de5\u4f5c",
                "\u6838\u5fc3\u5185\u5bb9",
                "\u6587\u732e\u7efc\u8ff0",
            )
        )
        has_core_request = any(
            token in value
            for token in (
                "\u6838\u5fc3\u5de5\u4f5c",
                "\u6838\u5fc3\u5185\u5bb9",
                "\u7814\u7a76\u8d21\u732e",
            )
        )
        has_search_action = any(
            token in value
            for token in (
                "\u641c\u7d22",
                "\u67e5\u627e",
                "\u68c0\u7d22",
                "\u603b\u7ed3",
                "\u6838\u5fc3\u5de5\u4f5c",
                "\u6838\u5fc3\u5185\u5bb9",
            )
        )
        return (has_literature or has_core_request) and has_search_action

    @staticmethod
    def _extract_literature_query(text: str) -> str:
        value = str(text or "").strip()
        value = re.sub(
            "^(?:\u8bf7|\u5e2e\u6211)?[ \t]*(?:\u641c\u7d22|\u68c0\u7d22|\u67e5\u627e|\u603b\u7ed3)",
            "",
            value,
        )
        value = re.sub(
            "(?:\u8fd9\u7bc7|\u8fd9\u4e2a)?(?:\u8bba\u6587|\u6587\u732e)?[ \t]*(?:\u7684)?[ \t]*(?:\u6838\u5fc3\u5de5\u4f5c|\u6838\u5fc3\u5185\u5bb9|\u7814\u7a76\u5de5\u4f5c)$",
            "",
            value,
        )
        return value.strip(" \t,，。！？") or "\u6838\u5fc3\u5de5\u4f5c"

    @staticmethod
    def _is_confirm(text: str) -> bool:
        return any(
            value in text
            for value in [
                "确认发送",
                "确认",
                "可以发送",
                "发送吧",
                "好的发送",
            ]
        )

    @staticmethod
    def _is_cancel(text: str) -> bool:
        return any(
            value in text
            for value in [
                "取消",
                "取消发送",
                "不要发送",
                "别发送",
            ]
        )

    @staticmethod
    def _is_file_selection(text: str) -> bool:
        return bool(
            re.fullmatch(
                r"(?:我)?(?:选择|选|发送)?(?:了)?(?:第\s*)?"
                r"(?:[1-9]|[一二三四五六七八九])"
                r"(?:个|项|号|个文件)?",
                text,
            )
        )

    @staticmethod
    def _extract_url(text: str) -> str:
        match = re.search(
            r"https?://[^\s，。！？]+",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(0) if match else ""

    @staticmethod
    def _extract_application(text: str) -> str:
        for application in ["qq", "微信", "浏览器", "wps", "word"]:
            if application in text.casefold():
                return application
        return ""

    @staticmethod
    def _extract_location(text: str) -> str:
        match = re.search(
            r"(.+?)(?:天气|气温|温度)",
            text,
        )
        return match.group(1).strip("，。 ") if match else ""

    @staticmethod
    def _extract_file_query(text: str) -> str:
        value = str(text or "").strip()
        location_prefix = r"(?:桌面的|桌面上的|电脑上的|电脑里的|本地的|本地里的|我的电脑上的)?"

        # "桌面文件中..." means search desktop documents by content; it does
        # not provide a concrete file name.
        generic_desktop_match = re.search(
            r"(?:找|查找|搜索)?\s*(?:桌面|电脑桌面)(?:上的|的)?"
            r"(?:文件|文档)(?:中|里|里面|里的|中的)?",
            value,
        )
        if generic_desktop_match:
            # There is no concrete file name before "中". The workflow will
            # search document contents using old_text.
            return ""

        # Extract the file phrase before the requested action, for example:
        # "把桌面agent简历修改一下" -> "agent简历".
        explicit_location_match = re.search(
            r"(?:桌面|电脑桌面)(?:上的|的)?\s*"
            r"(?P<file>.+?)(?="
            r"(?:里面|里的|中的|里|中|修改|更改|改一下|改成|改为|"
            r"换成|变成|替换|删除|移除|打开|读取|查看|发送到|发到|发送|发给|$)"
            r")",
            value,
        )
        if explicit_location_match:
            return IntentRouter._clean_file_query(
                explicit_location_match.group("file")
            )

        recent_match = re.search(
            r"(?:刚刚|刚才|之前|上次)找到的(?:文件|文档)?\s*(?P<file>.+?)(?=，|,|、|将|把|中的|里的|$)",
            value,
        )
        if recent_match:
            return IntentRouter._clean_file_query(recent_match.group("file"))

        # 先从“文件里的/文件中的”结构中提取文件名。这个结构同时覆盖
        # “修改报告里的标题”和“删除成绩单里的学号123”。
        document_match = re.search(
            rf"(?:把|将|修改|更改|删除|移除)?\s*{location_prefix}"
            r"(?P<file>.+?)(?:里面|里的|中的|里|中)",
            value,
        )
        if document_match:
            return IntentRouter._clean_file_query(document_match.group("file"))

        # 发送文件时，文件名位于“发给我/发到邮箱”等发送动作之前。
        send_match = re.search(
            rf"(?:把|将|发送|发)?\s*{location_prefix}"
            r"(?P<file>.+?)(?=(?:发给我|发送给我|发到|发送到|到我的邮箱|到我邮箱))",
            value,
        )
        if send_match:
            return IntentRouter._clean_file_query(send_match.group("file"))

        # 打开/查找类请求没有“里/中”标记，使用命令词后的剩余文本。
        fallback = re.sub(
            rf"^(?:帮我|请|把|将|查找|搜索|找一下|打开|读取|查看)\s*{location_prefix}",
            "",
            value,
        )
        fallback = re.split(
            r"(?:发给我|发送给我|发到我的邮箱|发送到我的邮箱|然后|并且|再)",
            fallback,
            maxsplit=1,
        )[0]
        return IntentRouter._clean_file_query(fallback)

    @staticmethod
    def _clean_file_query(value: str) -> str:
        value = str(value or "").strip(" \t，。；：")
        for prefix in (
            "桌面的",
            "桌面上的",
            "桌面",
            "电脑上的",
            "电脑里的",
            "本地的",
            "本地里的",
            "文件",
            "文档",
        ):
            if value.startswith(prefix):
                value = value[len(prefix):].strip()
        if value.endswith("文件"):
            value = value[:-2].strip()
        return value.strip(" \t，。；：")

    @staticmethod
    def _extract_replacement(text: str) -> str:
        patterns = [
            r"(?:替换成|替换为|修改为|改成|改为|换成|变成|为)[“\"]?(.*?)[”\"]?(?:，|。|；|然后|并且|发给我|发送给我|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()

        return ""

    @classmethod
    def _extract_edit_pair(cls, text: str) -> tuple[str, str]:
        tail = r"(?=，|。|；|然后|并且|发给我|发送给我|$)"
        patterns = [
            rf"(?:把|将).*?(?:修改一下|修改|更改|替换).*?[，,]\s*[“\"]?(.*?)[”\"]?(?:改成|改为|替换为|替换成|修改为|换成|变成)[“\"]?(.*?)[”\"]?{tail}",
            rf"(?:把|将).*?(?:里面|里的|中的|里|中).*?从[“\"]?(.*?)[”\"]?(?:改成|改为|替换为|替换成|修改为|换成|变成)[“\"]?(.*?)[”\"]?{tail}",
            rf"(?:删除|移除).*?(?:里面|里的|中的|里|中)(?:的)?[“\"]?(.*?)[”\"]?{tail}",
            rf"(?:把|将|修改|更改).*?(?:里面|里的|中的|里|中)(?:的)?[“\"]?(.*?)[”\"]?(?:替换成|替换为|修改为|改成|改为|换成|变成|为)[“\"]?(.*?)[”\"]?{tail}",
            rf"(?:把|将)[“\"]?(.*?)[”\"]?(?:替换成|替换为|修改为|改成|改为|换成|变成|为)[“\"]?(.*?)[”\"]?{tail}",
        ]
        for pattern in patterns:
            match = re.search(pattern, str(text or ""))
            if match:
                groups = [group.strip(" \t，。；：\"'“”") for group in match.groups()]
                if len(groups) == 1:
                    return groups[0], ""
                return groups[0], groups[1]
        return "", cls._extract_replacement(text)

    @staticmethod
    def _is_placeholder_old_text(value: str) -> bool:
        return str(value or "").strip() in {
            "名字",
            "姓名",
            "学号",
            "标题",
            "日期",
            "金额",
            "内容",
            "文字",
        }

    @staticmethod
    def _edit_missing_fields(old_text: str, new_text: str) -> list[str]:
        missing = []
        if not old_text or IntentRouter._is_placeholder_old_text(old_text):
            missing.append("old_text")
        if new_text is None:
            missing.append("new_text")
        return missing

    def to_json(self, result: IntentResult) -> str:
        return json.dumps(
            {
                "intent": result.name,
                "confidence": result.confidence,
                "entities": result.entities,
                "missing_fields": result.missing_fields,
            },
            ensure_ascii=False,
        )
