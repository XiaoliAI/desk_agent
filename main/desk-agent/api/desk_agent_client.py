import hashlib
import json
import re
import threading
import time

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from api.config import get_feishu_config


_sessions = {}
_sessions_lock = threading.Lock()


_SEARCH_RESULT_LINE = re.compile(
    r"^\s*(\d+)[.．、:：]\s*(.+?)\s*\|.*$"
)
_SELECTION_NUMBER = re.compile(
    r"(?:选择|选|发送|发|打开)?\s*(?:第\s*)?"
    r"(\d+|零|一|二|两|三|四|五|六|七|八|九|十)"
    r"\s*(?:个|份|项|号|文件)?\s*$"
)
_CHINESE_NUMBERS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def make_device_id(open_id: str) -> str:
    digest = hashlib.sha256(open_id.encode("utf-8")).hexdigest()[:24]
    return f"feishu-{digest}"


class AgentSession:
    def __init__(self, open_id: str):
        self.open_id = open_id
        self.device_id = make_device_id(open_id)
        self.websocket = None
        self.session_id = ""
        self.last_used = 0.0
        self.lock = threading.Lock()
        self.selection_candidates = []
        self.selection_updated_at = 0.0

    def close(self):
        websocket = self.websocket
        self.websocket = None
        self.session_id = ""
        if websocket is not None:
            try:
                websocket.close()
            except Exception:
                pass

    def connect(self):
        self.close()
        config = get_feishu_config()
        websocket_url = str(
            config.get(
                "agent_websocket_url",
                "ws://127.0.0.1:8000/xiaozhi/v1/",
            )
        )

        self.websocket = connect(
            websocket_url,
            additional_headers={
                "device-id": self.device_id,
                "client-id": "feishu-bot",
            },
            open_timeout=10,
            close_timeout=5,
            max_size=4 * 1024 * 1024,
        )
        self.websocket.send(
            json.dumps(
                {
                    "type": "hello",
                    "device_id": self.device_id,
                    "device_name": "Feishu remote client",
                    "device_mac": self.device_id,
                    "features": {
                        "mcp": False,
                        "emoji": False,
                        "text_only": True,
                    },
                },
                ensure_ascii=False,
            )
        )
        self.session_id = self._wait_for_hello()
        self.last_used = time.monotonic()

    def _wait_for_hello(self) -> str:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            message = self.websocket.recv(timeout=5)
            if isinstance(message, bytes):
                continue
            data = json.loads(message)
            if data.get("type") == "hello" and data.get("session_id"):
                return str(data["session_id"])
        raise TimeoutError("Desk Agent handshake timed out")

    def _collect_response(self, timeout: int) -> str:
        deadline = time.monotonic() + timeout
        sentences = []
        seen_sentences = set()

        while time.monotonic() < deadline:
            remaining = max(1, deadline - time.monotonic())
            message = self.websocket.recv(timeout=remaining)
            if isinstance(message, bytes):
                continue

            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue

            if data.get("type") != "tts":
                continue

            state = data.get("state")
            text = str(data.get("text", "")).strip()
            if state == "sentence_start" and text:
                if text not in seen_sentences:
                    sentences.append(text)
                    seen_sentences.add(text)
            if state == "stop":
                break

        if not sentences:
            raise TimeoutError("Desk Agent returned no text")
        return "\n".join(sentences)

    def _remember_search_results(self, response: str) -> None:
        """Remember numbered file results for the next Feishu selection message."""
        candidates = []
        for line in str(response or "").splitlines():
            match = _SEARCH_RESULT_LINE.match(line)
            if not match:
                continue

            name = match.group(2).strip()
            if name:
                candidates.append(name)

        if candidates:
            self.selection_candidates = candidates
            self.selection_updated_at = time.monotonic()

    @staticmethod
    def _selection_index(command: str):
        text = re.sub(r"\s+", "", str(command or "")).strip()
        if not text:
            return None

        if text.isdigit():
            return int(text)

        match = _SELECTION_NUMBER.match(text)
        if not match:
            return None

        value = match.group(1)
        return int(value) if value.isdigit() else _CHINESE_NUMBERS[value]

    def _normalize_selection(self, command: str) -> str:
        """Turn a numbered file choice into an explicit agent command."""
        if not self.selection_candidates:
            return command

        # Do not apply an old search result after a long idle period.
        if time.monotonic() - self.selection_updated_at > 150:
            self.selection_candidates = []
            return command

        index = self._selection_index(command)
        if index is None or not 1 <= index <= len(self.selection_candidates):
            return command

        file_name = self.selection_candidates[index - 1]
        self.selection_candidates = []

        compact_command = str(command or "").replace(" ", "")
        if "打开" in compact_command:
            return f"打开文件 {file_name}"
        return f"把文件 {file_name} 发送到我的邮箱"

    def send(self, command: str) -> str:
        config = get_feishu_config()
        timeout = int(config.get("agent_timeout_seconds", 120))
        idle_seconds = int(config.get("session_idle_seconds", 150))

        with self.lock:
            if (
                self.websocket is None
                or time.monotonic() - self.last_used > idle_seconds
            ):
                self.connect()

            command = self._normalize_selection(command)

            def build_payload():
                return json.dumps(
                    {
                        "session_id": self.session_id,
                        "type": "listen",
                        "state": "detect",
                        "text": command,
                    },
                    ensure_ascii=False,
                )

            try:
                self.websocket.send(build_payload())
            except (ConnectionClosed, OSError):
                self.connect()
                self.websocket.send(build_payload())

            try:
                result = self._collect_response(timeout)
            except (ConnectionClosed, OSError, TimeoutError):
                self.close()
                raise

            self.last_used = time.monotonic()
            self._remember_search_results(result)
            return result

        raise RuntimeError("Desk Agent command failed")


def get_agent_session(open_id: str) -> AgentSession:
    with _sessions_lock:
        session = _sessions.get(open_id)
        if session is None:
            session = AgentSession(open_id)
            _sessions[open_id] = session
        return session


def send_agent_command(command: str, open_id: str) -> str:
    command = str(command or "").strip()
    open_id = str(open_id or "").strip()
    if not command:
        raise ValueError("Command cannot be empty")
    if not open_id:
        raise ValueError("Feishu open_id cannot be empty")
    return get_agent_session(open_id).send(command)
