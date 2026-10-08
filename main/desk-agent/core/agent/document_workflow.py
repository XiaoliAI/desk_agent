from typing import Any

from langgraph.graph import END, START, StateGraph

from core.agent.state import DocumentWorkflowState
from plugins_func.file_utils import resolve_requested_file
from plugins_func.functions.generate_report import (
    count_chinese_chars,
    generate_report_content,
    get_report_path,
    open_document,
    write_docx,
)
from plugins_func.functions.read_file import clean_content, read_file_content


class DocumentWorkflow:
    """读取资料、生成报告、保存并打开文档的确定性工作流。"""

    def __init__(self, conn):
        self.conn = conn
        self.graph = self._build_graph()

    @staticmethod
    def route_after_step(state: DocumentWorkflowState) -> str:
        return "failed" if state.get("error") else "continue"

    def resolve_source(self, state: DocumentWorkflowState) -> dict[str, Any]:
        path, error = resolve_requested_file(
            self.conn,
            state.get("source_file", ""),
        )
        if error:
            return {
                "current_step": "resolve_source",
                "error": error,
            }

        return {
            "current_step": "resolve_source",
            "source_path": path,
            "error": "",
        }

    def read_source(self, state: DocumentWorkflowState) -> dict[str, Any]:
        try:
            source_path = state["source_path"]
            content = read_file_content(source_path)
            content, truncated = clean_content(content, 12000)
            if not content:
                raise ValueError("源文件为空")
            if truncated:
                content += "\n[原始资料已按安全长度截断]"

            return {
                "current_step": "read_source",
                "source_content": content,
                "error": "",
            }
        except Exception as error:
            return {
                "current_step": "read_source",
                "error": f"读取源文件失败：{error}",
            }

    async def write_report(self, state: DocumentWorkflowState) -> dict[str, Any]:
        try:
            content = await generate_report_content(
                self.conn,
                state.get("topic", "未命名主题"),
                state.get("word_count", 300),
                source_material=state.get("source_content", ""),
            )
            return {
                "current_step": "write_report",
                "report_content": content,
                "error": "",
            }
        except Exception as error:
            return {
                "current_step": "write_report",
                "error": f"生成报告正文失败：{error}",
            }

    def save_report(self, state: DocumentWorkflowState) -> dict[str, Any]:
        try:
            topic = state.get("topic", "未命名主题")
            report_path = get_report_path(self.conn, topic, None)
            write_docx(
                report_path,
                f"关于{topic}的汇报",
                state["report_content"],
            )
            return {
                "current_step": "save_report",
                "report_path": report_path,
                "error": "",
            }
        except Exception as error:
            return {
                "current_step": "save_report",
                "error": f"保存Word报告失败：{error}",
            }

    def open_report(self, state: DocumentWorkflowState) -> dict[str, Any]:
        try:
            editor_name = open_document(
                self.conn,
                state["report_path"],
                state.get("editor", "default"),
            )
            report_path = state["report_path"]
            count = count_chinese_chars(state["report_content"])
            return {
                "current_step": "open_report",
                "result": (
                    f"已读取{state['source_path'].name}，生成约{count}字的报告，"
                    f"保存为{report_path.name}，并使用{editor_name}打开"
                ),
                "error": "",
            }
        except Exception as error:
            return {
                "current_step": "open_report",
                "error": f"报告已生成，但打开失败：{error}",
            }

    @staticmethod
    def fail_task(state: DocumentWorkflowState) -> dict[str, Any]:
        return {
            "current_step": state.get("current_step", "failed"),
            "result": state.get("error", "任务执行失败"),
        }

    def _build_graph(self):
        builder = StateGraph(DocumentWorkflowState)
        builder.add_node("resolve_source", self.resolve_source)
        builder.add_node("read_source", self.read_source)
        builder.add_node("write_report", self.write_report)
        builder.add_node("save_report", self.save_report)
        builder.add_node("open_report", self.open_report)
        builder.add_node("failed", self.fail_task)

        builder.add_edge(START, "resolve_source")
        for current, following in (
            ("resolve_source", "read_source"),
            ("read_source", "write_report"),
            ("write_report", "save_report"),
            ("save_report", "open_report"),
        ):
            builder.add_conditional_edges(
                current,
                self.route_after_step,
                {"continue": following, "failed": "failed"},
            )

        builder.add_edge("open_report", END)
        builder.add_edge("failed", END)
        return builder.compile()

    async def run(self, initial_state: DocumentWorkflowState):
        return await self.graph.ainvoke(initial_state)
