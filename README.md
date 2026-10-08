# Desk Agent

面向个人电脑操作与远程办公场景的多模态桌面智能体。项目基于 LangChain、LangGraph 与 MCP 构建 Workflow + Agent 混合架构，通过语音、文本和飞书接收指令，并调用受控桌面工具执行多步骤任务。

> 当前主要支持 Windows 与 Python 3.10。项目能够操作本地文件和发送邮件，请仅配置可信目录，并妥善保管 API Key、SMTP 授权码与飞书密钥。

## 核心能力

- **Workflow + Agent：**覆盖 12 类业务意图以及确认、取消、候选选择等流程控制意图。确定性任务由 LangGraph 编排，开放式请求由 Agent 在意图约束下选择工具并提取参数。
- **三层记忆：**组合会话上下文、SQLite 任务状态与 RAG 知识记忆，支持跨轮参数补全、任务确认、断点续执行和任务类型隔离。
- **多模态桌面执行：**统一接入数字人语音、文本和飞书远程指令，通过 Function Calling 与 MCP 封装应用、网页、文件、文档和邮件工具。
- **文献 RAG：**解析 PDF 并建立原文分块与论文核心内容画像，联合检索原文片段、研究问题、方法、贡献和实验结论，辅助文献问答与综述生成。当前召回采用本地关键词匹配与画像加权，不依赖向量数据库。

## 使用示例

```text
打开浏览器并访问百度
查找桌面的成绩单
把简历发到我的邮箱
将刚才找到的文档中“李栩威”改成“李威”，然后发给我
帮我写一份关于人工智能的 500 字汇报，并用 WPS 打开
导入桌面上的 PDF 论文
搜索这篇论文的核心工作
```

## 系统架构

```text
数字人语音 / 文本 / 飞书
          │
          ▼
     意图识别与实体抽取
          │
     ┌────┴────┐
     ▼         ▼
LangGraph     Agent
Workflow      工具选择
     └────┬────┘
          ▼
应用 / 网页 / 文件 / 文档 / 邮件 / 文献 RAG
          │
          ▼
会话记忆 / SQLite 任务记忆 / RAG 知识记忆
```

语音链路：

```text
麦克风 → 唤醒词 → Silero VAD → FunASR → Agent → Edge TTS → 数字人
```

## 技术栈

Python 3.10、LangChain、LangGraph、FastAPI、WebSocket、FunASR、Silero VAD、Edge TTS、SQLite、MCP、PyMuPDF、飞书开放平台。

## 目录结构

```text
main/desk-agent/       后端、Agent、工作流、工具与 RAG
main/desk-agent-ui/    数字人页面、麦克风与唤醒词运行时
scripts/               环境初始化和模型下载脚本
start.ps1              Windows 一键启动入口
```

## 快速开始

### 1. 准备环境

- Windows 10/11
- Python 3.10 x64
- PowerShell 5.1 或更高版本
- 可用麦克风
- 建议至少 8 GB 内存

在项目根目录执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\scripts\setup.ps1
```

该脚本会创建 `main/desk-agent/.venv`、安装后端和唤醒词依赖，并从模板创建私有配置。

### 2. 下载本地 ASR 模型

SenseVoiceSmall 权重约 900 MB，不提交到 GitHub：

```powershell
.\scripts\download_models.ps1
```

也可以手动下载 [SenseVoiceSmall model.pt](https://modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt)，保存到：

```text
main/desk-agent/models/SenseVoiceSmall/model.pt
```

### 3. 配置服务

编辑以下文件：

```text
main/desk-agent/data/.config.yaml
```

至少需要填写：

- `LLM.ModelScopeLLM.api_key`：ModelScope API Key
- `plugins.local_file_search.allowed_directories`：允许搜索的本地目录

按需填写：

- 高德天气和联网搜索 API Key
- 默认收件邮箱、SMTP 用户名及授权码
- 飞书应用 ID、Secret 和允许访问的用户
- QQ、WPS、Word 或浏览器的自定义路径

真实配置已经被 `.gitignore` 排除。不要把 `data/.config.yaml` 提交到仓库。

### 4. 启动

一键启动后端、远程 API、可选飞书机器人和数字人 UI：

```powershell
.\start.ps1
```

浏览器访问：

```text
http://127.0.0.1:8006/index.html
```

默认服务地址：

- Agent WebSocket：`ws://127.0.0.1:8000/xiaozhi/v1/`
- 数字人页面：`http://127.0.0.1:8006/index.html`
- 远程 API：`http://127.0.0.1:8010`

只启动后端时：

```powershell
cd main\desk-agent
.\.venv\Scripts\python.exe app.py
```

只启动数字人 UI 时：

```powershell
cd main\desk-agent-ui
..\desk-agent\.venv\Scripts\python.exe start.py
```

## 配置安全

- 仓库只提交 `config.example.yaml`，真实配置存放于 `data/.config.yaml`。
- 不要提交日志、任务数据库、邮件地址、论文原文或生成文档。
- 发布前请运行 `git status --short` 并检查每一个待提交文件。
- 如果密钥曾出现在公开提交中，删除文件并不足够，必须立即在对应平台撤销并重新生成密钥。

## 常见问题

**启动时报 `model.pt` 无效或找不到中央目录**

模型下载不完整。删除损坏的 `model.pt`，重新运行 `scripts/download_models.ps1`。

**数字人能打字对话，但语音没有识别结果**

确认浏览器已获得麦克风权限，页面已连接 `ws://127.0.0.1:8000/xiaozhi/v1/`，后端日志中能够看到浏览器音频包和 PCM 解码记录。

**Edge TTS 请求失败**

Edge TTS 依赖外部网络。TTS 不可用时，文字与工具执行仍可能正常工作。

**端口 8010 被占用**

关闭旧的远程 API 进程，或修改私有配置中的 `plugins.remote_api.port`。

## 开发验证

```powershell
cd main\desk-agent
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q core\agent core\rag plugins_func\functions api
```

## 许可证与致谢

项目基于 [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) 的服务端和数字人模块改造，保留原项目 MIT License 与版权声明。第三方模型、数字人素材及服务分别受其各自许可证和服务条款约束。

