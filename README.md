<img width="1902" height="905" alt="image" src="https://github.com/user-attachments/assets/e5254e8d-19b0-4d14-b1de-33b8a18b6828" />
一个能听懂你说话、能远程听你指挥、能直接接管你电脑的桌面智能体。项目面向个人电脑操作与远程办公场景，以 Python、LangChain、LangGraph、FastAPI、WebSocket、SQLite、MCP 与 PyMuPDF 为技术底座，统一接入数字人语音/文本、飞书远程指令与本地桌面工具，构建"感知—理解—决策—执行—回传"的完整智能闭环，实现自然语言驱动的跨端桌面任务自动化。

<img width="1180" height="2102" alt="b4903140025e97f5c36a4024d1f6ef76" src="https://github.com/user-attachments/assets/4897aedb-3609-46d6-a1a6-e010c0aa9c94" />
（手机端飞书交互页）

## 核心能力

Workflow + Agent 混合编排架构：邮件发送、文档编辑、报告生成与论文导入等确定性任务由 LangGraph 工作流统一编排，保证执行路径稳定可复现；开放式请求交由 Agent 完成语义理解、参数提取与工具自主选择，实现确定性流程与自主决策的有机协同。

分层意图识别与动态工具路由：覆盖桌面操作、文件处理、邮件、文档与文献检索等业务意图，构建分层识别与路由机制，按意图动态挂载工具子集，避免全量工具注入带来的误选与上下文污染。

三层记忆体系：会话记忆承载上下文理解，SQLite 任务记忆持久化任务状态与关键参数，RAG 知识记忆维护论文索引；支持跨轮参数补充、文件选择、操作确认、任务断点续接与多任务上下文隔离，保障长链路任务的连贯性与可靠性。

多模态桌面执行链路：统一接入数字人语音/文本与飞书远程控制两类入口，通过工具链调用应用、网页、文件、文档与邮件等桌面能力，实现本地交互与远程执行的一体化贯通。

学术文献 RAG 检索增强：构建 PDF 解析、语义分块、论文核心画像、远程 Embedding、Chroma 向量检索、BM25 关键词召回、RRF 名次融合与证据页回补的全流程检索链路，兼顾语义召回与关键词精确匹配，提升检索召回率与答案可追溯性。

## 使用示例

```text
打开浏览器并访问百度
搜索桌面的简历文件
把简历发到我的邮箱
将刚才找到的文档中“。。。。”改成“。。。”，然后发给我
导入桌面上的论文 PDF
搜索这篇论文的研究问题、技术方法和核心工作
总结这篇论文并生成一份报告
```

涉及文件选择或高风险操作时，系统会暂停并保存任务状态：

```text
搜索到多个文件 -> waiting_selection -> 用户回复编号 -> 继续当前任务
准备发送邮件   -> waiting_confirmation -> 用户确认 -> 执行并记录结果
```

用户输入 `1` 时，数字本身不决定业务类型。系统会根据当前用户、等待状态和任务类型恢复最近的待处理任务，避免论文导入与邮件任务串台。

## 系统架构

```text
数字人语音 / 文本 / 飞书
              |
              v
        WebSocket / 远程 API
              |
              v
      意图识别与实体抽取
              |
       +------+------+
       |             |
       v             v
  任务状态路由    Agent 工具选择
       |             |
       +------+------+
              v
   LangGraph 工作流 / 桌面工具 / RAG
              |
              v
 会话记忆 + SQLite 任务记忆 + RAG 知识记忆
```

语音链路：

```text
麦克风 -> 唤醒词 -> Silero VAD -> FunASR -> Agent -> 工具/工作流 -> Edge TTS -> 数字人
```

文献 RAG 链路：

```text
PDF -> PyMuPDF 解析 -> 页面分块与论文画像 -> 远程 Embedding -> Chroma 索引
问题 -> 查询扩展/中英转换 -> 向量检索 + BM25 -> RRF 融合
     -> 相似度过滤/证据页回补 -> 带 [E1] 引用的回答
```

## 技术栈

Python 3.10、LangChain、LangGraph、FastAPI、WebSocket、FunASR、Silero VAD、Edge TTS、SQLite、Chroma、PyMuPDF、MCP、飞书开放平台。

## 目录结构

```text
main/desk-agent/       后端、Agent、工作流、桌面工具和文献 RAG
main/desk-agent-ui/    数字人页面、麦克风与唤醒词运行时
scripts/               Windows 环境初始化和模型下载脚本
start.ps1              一键启动后端和数字人 UI
.github/workflows/     CI 编译和测试配置
```

## 环境要求

- Windows 10/11
- Python 3.10 x64
- PowerShell 5.1 或更高版本
- 可用麦克风（仅使用文本或飞书时不是必需）
- 建议至少 8 GB 内存
- 文献 RAG 需要可用的 Embedding API

## 安装

在仓库根目录打开 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\scripts\setup.ps1
```

安装脚本会创建 `main/desk-agent/.venv`，安装后端和数字人依赖，并从模板创建私有配置 `main/desk-agent/data/.config.yaml`。

如果电脑没有 `py -3.10`，请先安装 Python 3.10 x64，并安装 Python Launcher。

## 下载语音模型

语音识别使用本地 SenseVoiceSmall 模型，权重文件不提交到 GitHub：

```powershell
.\scripts\download_models.ps1
```

模型路径应为：

```text
main/desk-agent/models/SenseVoiceSmall/model.pt
```

仅使用文本或飞书时可以暂不下载；使用数字人语音时必须准备该模型。

## 配置

编辑私有配置：

```text
main/desk-agent/data/.config.yaml
```

该文件已被 `.gitignore` 忽略，不能提交到仓库。

### 基础配置

至少填写 LLM Key，并把允许搜索的目录改成本机路径：

```yaml
LLM:
  ModelScopeLLM:
    api_key: "YOUR_MODELSCOPE_API_KEY"

plugins:
  local_file_search:
    allowed_directories:
      - "C:/Users/YOUR_NAME/Desktop"
```

### RAG 配置

LLM 与 Embedding 可以使用不同服务。公开模板默认使用 ModelScope 作为 LLM、阿里云百炼兼容接口作为 Embedding：

```yaml
plugins:
  literature_embedding:
    model_name: qwen3.7-text-embedding-flash
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: "YOUR_DASHSCOPE_API_KEY"
```

Embedding Key 也可通过环境变量提供：

```powershell
$env:DESK_AGENT_EMBEDDING_API_KEY = "YOUR_DASHSCOPE_API_KEY"
```

Chroma 向量数据默认保存在 `main/desk-agent/data/literature/chroma/`，属于本地运行时数据，不提交到 GitHub。

### 邮件配置

填写 `plugins.file_email` 中的 SMTP 地址、端口、邮箱、授权码和默认收件人。SMTP 密码应使用邮箱服务商提供的授权码，不要使用邮箱登录密码。

### 飞书配置

填写 `plugins.feishu` 中的应用 ID 和应用 Secret，并选择回复通道：

- `reply_mode: oauth`：使用飞书应用 OAuth 回复，需要发送消息权限。
- `reply_mode: webhook`：使用群自定义机器人 Webhook 回复。
- `reply_mode: auto`：配置 Webhook 时优先使用 Webhook，否则回退 OAuth。

建议配置 `allowed_open_ids`，只允许指定飞书用户控制本机 Agent。消息接收使用飞书 WebSocket 长连接时，本地电脑不需要暴露公网 Webhook。

### 远程 API 配置

远程 API 默认监听 `http://127.0.0.1:8010`。请把 `plugins.remote_api.token` 改为随机字符串，不要将远程 API 暴露到公网。

## 启动

### 一键启动

在仓库根目录执行：

```powershell
.\start.ps1
```

默认地址：

- 数字人 UI：`http://127.0.0.1:8006/index.html`
- Agent WebSocket：`ws://127.0.0.1:8000/xiaozhi/v1/`
- 远程 API：`http://127.0.0.1:8010`

### 分别启动

只启动 Agent WebSocket：

```powershell
cd main\desk-agent
.\.venv\Scripts\python.exe app.py
```

启动 Agent、远程 API 和可选飞书机器人：

```powershell
cd main\desk-agent
.\.venv\Scripts\python.exe start_all.py
```

只启动数字人 UI：

```powershell
cd main\desk-agent-ui
..\desk-agent\.venv\Scripts\python.exe start.py
```

不要同时运行两套 `start_all.py`。端口被占用时先关闭旧进程，或在私有配置中修改端口。

## 文献 RAG 使用

1. 将 PDF 放入 `allowed_directories` 允许搜索的目录。
2. 发送“导入桌面上的 xxx.pdf”。
3. 如果匹配多个文件，回复候选编号，例如 `1`。
4. 等待系统完成 PDF 解析、分块、论文画像抽取和向量入库。
5. 发送“总结这篇论文的研究问题、技术方法和核心工作”。

检索使用论文画像向量、原文分块向量和 BM25 关键词三类信号，并通过 RRF 合并不同召回列表。画像命中但原文相似度偏低时，系统会根据画像关联页回补原文证据。回答使用 `[E1]`、`[E2]` 标注证据；证据不足时应拒绝猜测。

更换 Embedding 模型或向量维度后，应重新构建向量索引。已有 JSONL 兼容索引时，可执行：

```powershell
cd main\desk-agent
.\.venv\Scripts\python.exe -m core.rag.rebuild_vector_index
```

## 测试

```powershell
cd main\desk-agent
.\.venv\Scripts\python.exe -m pip install -r requirements-ci.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q core\agent core\rag plugins_func\functions api
```

测试覆盖意图路由、飞书回复、文件编号选择、远程 Embedding、文献入库与混合检索、TTS 文本兜底和消息协议。

## 常见问题

### 飞书收到消息但无法回复

查看启动日志中的“飞书回复通道”。OAuth 模式需要检查应用发布状态、消息权限和应用凭据；Webhook 模式需要检查 Webhook 地址、签名密钥以及机器人是否已加入目标群。

### 端口被占用

```powershell
Get-NetTCPConnection -LocalPort 8000,8010,8006 -ErrorAction SilentlyContinue
```

关闭旧服务后再启动，或修改私有配置中的端口。
