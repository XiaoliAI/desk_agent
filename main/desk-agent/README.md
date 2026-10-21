# Desk Agent Backend

后端包含 Agent WebSocket 服务、意图识别、LangGraph 工作流、SQLite 任务记忆、桌面工具、远程 API、飞书适配器和学术文献 RAG。

完整的安装、配置、启动、飞书接入、RAG 使用和发布说明请查看仓库根目录的 [README](../../README.md)。

## 后端入口

- `app.py`：Agent WebSocket 服务，数字人 UI 通过它连接。
- `start_all.py`：统一启动 Desk Agent、远程 API 和可选飞书机器人。
- `config.example.yaml`：公开配置模板，复制为 `data/.config.yaml` 后填写本机配置。
- `core/agent/`：意图路由、任务状态、记忆和 LangGraph 工作流。
- `core/rag/`：PDF 解析、语义分块、论文画像、Embedding、Chroma 和检索融合。
- `plugins_func/functions/`：桌面工具和文献工具。
- `api/`：远程 API、飞书 WebSocket 客户端及 OAuth/Webhook 回复通道。
- `tests/`：意图、任务、RAG、飞书、Embedding 和 TTS 测试。

## 启动

在本目录执行：

```powershell
.\.venv\Scripts\python.exe start_all.py
```

只启动 Agent WebSocket：

```powershell
.\.venv\Scripts\python.exe app.py
```

## RAG 索引

论文导入后，PDF 页面分块和论文核心画像会写入本地兼容索引，并同步写入 Chroma。向量数据位于 `data/literature/chroma/`，属于运行时数据，已被 Git 忽略。

已有兼容索引但需要重建 Chroma 时：

```powershell
.\.venv\Scripts\python.exe -m core.rag.rebuild_vector_index
```

更换 Embedding 模型或向量维度后，应清理旧 Chroma 数据并重新导入论文。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ci.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q core\agent core\rag plugins_func\functions api
```
