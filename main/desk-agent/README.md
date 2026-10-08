# Desk Agent Backend

后端模块包含 WebSocket 服务、意图路由、LangGraph 工作流、SQLite 任务记忆、桌面工具与文献 RAG。完整安装、配置和启动说明请查看仓库根目录的 [README](../../README.md)。

核心入口：

- `app.py`：Agent WebSocket 服务
- `start_all.py`：后端、远程 API 与飞书机器人统一启动器
- `config.example.yaml`：公开配置模板
- `core/agent/`：意图、状态、记忆与工作流
- `core/rag/`：PDF 解析、分块、画像与检索
- `plugins_func/functions/`：桌面工具实现

