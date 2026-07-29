# 基于 Pi SDK 的 GAIA runner

新的入口是 `gaia.py`。Python 只负责加载 GAIA 数据、附件和本地 skill，
Pi SDK 负责模型对话与原生 tool-call 循环。模型密钥只从进程环境读取，不会写入
Python→Node 的 JSON 协议或最终 trace。

## 安装

```powershell
Set-Location 'D:\个人仓库\agent test\gaia'
..\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

Set-Location .\pi-harness
npm.cmd install
Set-Location ..
```

父目录 `D:\个人仓库\agent test\.env` 至少需要：

```dotenv
MODEL_ID=deepseek-v4-flash
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=...
SILICON_TOKEN=...
```

`SILICON_TOKEN` 只供 `analyze_image` 使用。Pi 文本模型的
`OPENAI_API_KEY` 不会转发给 Python 工具进程。

## 运行

运行默认目标任务：

```powershell
python .\gaia.py
```

运行指定任务并允许最多 40 个 Pi turn：

```powershell
python .\gaia.py `
  --task-id 72c06643-a2fa-4186-aa5c-9ec33ae9b445 `
  --skill-profile general `
  --image-tool `
  --max-turns 40 `
  --variant pi-general-image
```

无图像工具 baseline：

```powershell
python .\gaia.py `
  --task-id 72c06643-a2fa-4186-aa5c-9ec33ae9b445 `
  --skill-profile none `
  --no-image-tool `
  --variant pi-baseline
```

每个任务写入
`gaia_outputs\<variant>\level<level>_<task-id>.json`。关键字段包括
`prediction`、`error`、`error_type`、`tool_error_count`、`turns`、
`terminated_by`、`logs` 和 `memory_messages`。`error_type` 会区分
`model_error`、`answer_format_error`、`max_turns` 与 `runner_error`；
`logs` 会记录模型消息及工具开始/结束事件，因此可以区分：

- 模型没有发出 tool call；
- 工具执行失败；
- 工具成功但模型忽略了结果；
- 达到 `max_turns`；
- 模型没有按 `<final_answer>...</final_answer>` 返回答案。

Phoenix 目前记录 Python 侧的任务总 span；Pi 内部的完整步骤以 JSON trace 为准。

## 工具边界

Pi 当前可以调用：

- `web_search`：公共网页搜索；
- `extract_pdf_text`：下载 PDF 并按页提取文字；
- `python`：在临时目录中运行受限计算代码；不能导入模块、读文件、访问网络或环境变量，
  预置 `math` 与 `statistics`；
- `analyze_image`：通过硅基流动视觉模型分析本地或远程图像。

Python 工具采用长驻 JSONL bridge，避免每次调用重新导入模型客户端。bridge 只接收
显式白名单中的工具名，单次工具调用有超时；超时后会终止 bridge，防止迟到响应污染
下一次调用。

传入 `--external-tools-config .\external_tools.json` 后，Pi 会通过官方 MCP
TypeScript client 启动配置中的 stdio server 组，动态发现 allowlist 中的工具，
并把 JSON Schema 转换成 Pi custom tools。Pi 不依赖 smolagents 的 Tool 对象。
当前配置直接启动 `gaia` profile 固定 digest 的 fetch、Playwright、time 三个 Docker
MCP 镜像；Pi 与 smolagents 共用同一配置和 allowlist。
同一配置中的 `pi_builtin_tools` 是 Pi 内置工具的显式白名单。默认配置将它设为空：
编码能力由上面的受限 `python` 提供，不把宿主文件系统或 shell 暴露给网页内容。

```powershell
python .\gaia.py `
  --task-id <GAIA-task-id> `
  --no-image-tool `
  --external-tools-config .\external_tools.json `
  --variant pi-docker-mcp-code
```

MCP 子进程只继承运行所需的系统变量以及 `env_passthrough` 明确列出的变量，
不会自动收到文本模型 API key。`tool_allowlist` 必须非空，工具数超过 `max_tools`
时 Pi 会拒绝启动。每个 server 的工具列表会完整翻页；工具结果只接收文本、文本资源
和结构化 JSON，并限制为 64 KiB。固定 digest 防止评测期间镜像实现漂移。

只有在 **Pi runner 本身已经位于一次性容器/虚拟机内** 时，才使用
`external_tools.pi-host-code.example.json`。它显式开放
`read + bash + grep + find + ls`；这些工具使用 runner 的权限，不是 Docker MCP
容器的权限。不要在存有 `.env`、历史 trace 或个人文件的宿主工作区直接启用它。

附件目前稳定支持图片和 PDF；DOCX、XLSX、PPTX、音频等任务会在 prompt 中明确标为
无专用解析器，而不会假装已经读到附件内容。

## 本地验证

以下命令不会访问真实模型 API：

```powershell
..\.venv\Scripts\python.exe -m unittest discover -s tests -v

Set-Location .\pi-harness
npm.cmd test
npm.cmd run typecheck
```

Python 测试中包含一个本地假 OpenAI-compatible SSE 服务。它会要求 Pi 原生调用
`python` 工具，再验证工具结果确实进入第二轮模型请求。
