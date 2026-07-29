# DeepSeek-v4flash GAIA 运行手册

## 1. 环境

在 PowerShell 中进入本目录并安装锁定的依赖：

```powershell
Set-Location 'D:\个人仓库\agent test\gaia'
..\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

编辑本目录或上一级目录的 `.env`（`load_dotenv()` 会向上查找），至少填写 `MODEL_ID`、`OPENAI_BASE_URL`、
`OPENAI_API_KEY`、`HF_TOKEN` 和 `SILICON_TOKEN`。主模型是纯文本模型时，
图像问答通过硅基流动的 OpenAI-compatible 多模态接口调用
`Qwen/Qwen3-VL-32B-Instruct`。可选配置如下：

```dotenv
SILICON_TOKEN=your-siliconflow-api-key
# 以下均为可选值
SILICON_BASE_URL=https://api.siliconflow.cn/v1
SILICON_VISION_MODEL=Qwen/Qwen3-VL-32B-Instruct
SILICON_VISION_DETAIL=high
SILICON_VISION_MAX_TOKENS=1024
SILICON_VISION_TIMEOUT_SECONDS=120
SILICON_VISION_MAX_IMAGE_BYTES=20971520
```

本地图片会在进程内转换为 Base64 data URL，公网 HTTP/HTTPS 图片则直接把 URL
交给硅基流动；图片内容不再经过公开 Hugging Face Space。调用会消耗硅基流动账户
额度。视觉结果仍需交叉验证，尤其是密集 OCR、细小物体和精确计数。

## 2. 启动 Phoenix

另开一个 PowerShell：

```powershell
Set-Location 'D:\个人仓库\agent test\gaia'
..\.venv\Scripts\Activate.ps1
phoenix serve --host 127.0.0.1 --port 6006
```

打开 <http://localhost:6006>。runner 默认把 traces 发送到本机 Phoenix，并使用
project `gaia-smolagents-deepseek-v4flash`。

## 3. 运行目标任务

完整配置（图像工具 + 两个 skill）：

```powershell
python .\run_gaia_sample.py `
  --task-id 72c06643-a2fa-4186-aa5c-9ec33ae9b445 `
  --skill-profile both `
  --image-tool `
  --variant both-upper-bound
```

无新增工具、无 skill 的 baseline：

```powershell
python .\run_gaia_sample.py `
  --task-id 72c06643-a2fa-4186-aa5c-9ec33ae9b445 `
  --skill-profile none `
  --no-image-tool `
  --variant baseline
```

推荐的无 UUID 定向 skill 组合：

```powershell
python .\run_gaia_sample.py `
  --task-id 72c06643-a2fa-4186-aa5c-9ec33ae9b445 `
  --skill-profile general `
  --image-tool `
  --max-steps 40 `
  --variant full-general
```

结果分别写入 `gaia_outputs\<variant>\`，不会覆盖旧 trace。默认不写入
validation 标准答案；确需离线评分数据时显式加 `--include-reference-answer`，
并确保 agent 无法读取该输出目录。

## 4. 导入外部工具

### 4.1 Docker MCP Toolkit Profile（推荐）

要求 Docker Desktop 4.62 或更高版本。在 Docker Desktop 的
`Settings > Beta features` 中启用 MCP Toolkit。项目采用一个不挂载本机目录的
核心 Profile：`fetch + playwright + time`。首次创建：

```powershell
docker mcp catalog pull mcp/docker-mcp-catalog
docker mcp profile create --name gaia `
  --server catalog://mcp/docker-mcp-catalog/fetch+playwright+time
docker mcp profile tools gaia `
  --disable playwright.browser_run_code_unsafe
docker mcp profile show gaia
```

先运行 `docker mcp profile show gaia` 检查 Profile 是否已经存在；仅在不存在时执行
`profile create`。如果需要重建，先在 Docker Desktop 中确认 Profile 内容，再显式删除旧 Profile。

不要把整个项目目录挂载给同时拥有网络访问的 MCP Server；项目根目录通常包含
`.env`，恶意网页提示可能诱导 Agent 外传密钥。本项目已有
`ExtractPdfTextTool` 和 `AnalyzeImageTool`，GAIA 附件不依赖 filesystem MCP。
确实需要 filesystem/markitdown 时，只挂载一个不含密钥的临时附件目录。

项目通过一个 Gateway 连接加载整个 Profile：

```powershell
Copy-Item .\external_tools.docker.example.json .\external_tools.json
python .\run_gaia_sample.py `
  --skill-profile general `
  --image-tool `
  --external-tools-config .\external_tools.json `
  --variant general-with-docker-mcp
```

在当前 Windows 环境中，Docker MCP CLI v0.42.2 的宿主 Gateway 会因为 PATH 中没有
`socat` 而无法启动业务 server。项目的默认 `external_tools.json` 因此采用更窄的
安全路径：直接以 stdio 启动 profile 中相同固定 digest 的 fetch、Playwright、time
容器，不挂载 Docker socket 或宿主目录。可用
`external_tools.docker-direct.example.json` 重建该配置；Gateway 问题修复后也可以
继续使用 `external_tools.docker.example.json`。

同一份 direct 配置可以交给 Pi 或 smolagents。配置里的 `pi_builtin_tools` 只影响 Pi，
smolagents 会忽略该字段：

```powershell
python .\gaia.py `
  --task-id <GAIA-task-id> `
  --no-image-tool `
  --external-tools-config .\external_tools.json `
  --variant pi-docker-mcp-code
```

当前 allowlist 包含 `fetch`、精选 Playwright 导航/交互工具和时区工具，共 12 个；
没有开放文件上传和浏览器任意代码执行。默认 `pi_builtin_tools=[]`，编码由受限
`python` 工具提供；它不能读文件、环境变量或网络。这样网页 prompt injection
不能直接转成宿主 shell 命令。

若 Pi runner 已经放进一次性容器或虚拟机，并且只挂载临时任务目录，可以复制
`external_tools.pi-host-code.example.json`。该显式 opt-in 配置开放
`read + bash + grep + find + ls`，仍不开放 `edit/write`。不要在包含 `.env`、
历史 trace 或个人源码的宿主目录中使用它。

`DeepSeek-V4-Flash` 负责文本推理和工具选择；它不直接接收图片。保留
`--image-tool` 后，`AnalyzeImageTool` 会惰性连接 `.env` 中配置的硅基流动
多模态模型，并把图片内容转成文本。底层使用 OpenAI-compatible
`/chat/completions` 接口。

配置中的 `max_tools` 是启动保护：Profile 暴露的工具超过该数量时，runner 会拒绝
运行。需要缩小 Profile 或用 `tool_allowlist` 精确选择工具，而不是盲目提高上限。
Gateway 固定使用 `--static`，因此 Agent 不能在评测过程中动态安装或替换 Server。
`connect_timeout_seconds=180` 用于容纳首次镜像拉取；镜像缓存后通常会更快。
Pi 会逐个 server 拉取全部工具分页；返回模型前，MCP 输出会过滤二进制内容并截断到
64 KiB，避免大响应挤占上下文或 trace。

MCP 子进程默认只收到运行所需的系统环境变量，不会自动继承
`OPENAI_API_KEY`、`HF_TOKEN`、`SILICON_TOKEN` 等密钥。某个 Server 确实需要环境变量时，
在 `docker_mcp.env_passthrough` 或对应 `mcp_servers` 条目中显式列出。
旧的 stdio MCP 配置如果曾依赖隐式继承环境变量，也必须迁移为显式
`env_passthrough`，否则 runner 会在变量缺失时拒绝启动。

如果 Gateway 日志出现连接 `host.docker.internal:<port>` 失败，说明 Docker Desktop
配置了当前不可用的代理。到 Docker Desktop 的代理设置中启动、修正或关闭该代理，
确认镜像可以正常拉取后再运行；不要把模型 API Key 写进 Docker 代理配置。

### 4.2 单独的 MCP 或 Hub 工具

复制并缩减示例配置，只保留审计过的 server/tool：

```powershell
Copy-Item .\external_tools.example.json .\external_tools.json
python .\run_gaia_sample.py `
  --skill-profile general `
  --external-tools-config .\external_tools.json `
  --variant general-with-mcp
```

stdio server 会在 runner 生命周期内启动并关闭；远程 MCP 直接连接 URL。不要把
示例占位 server 原样运行。

### 4.3 建议继续开放的工具

按收益和风险，建议分 Profile 增加，而不是把所有工具放进 `gaia`：

1. `gaia-research`：GitHub issue/commit/timeline 只读查询、Wikidata/MediaWiki、
   PubChem/NCBI 等结构化公共 API。优先采用专用只读工具，不开放通用带凭证 HTTP。
2. `gaia-code`：有 CPU、内存、时间和网络限制的状态化 Python 容器。每题复用同一
   工作目录，题目之间销毁；不挂载 Docker socket、`.env`、`.git` 或历史 trace。
3. `gaia-docs`：DOCX/XLSX/PPTX/HTML/ZIP 的只读提取器，只挂载临时附件目录；
   对压缩包设置展开大小和文件数上限。

暂不建议开放：宿主机任意 filesystem、`docker.sock`、secret manager、邮件/网盘、
浏览器文件上传、任意网页 JavaScript、无域名限制的带凭证请求，以及直接写项目文件
的 `edit/write`。工具描述和网页内容都按不可信输入处理；每个实验条件最好保持
8–15 个工具，并为 Pi 与 smolagents 使用同一 MCP allowlist。

## 5. 只做本地验证

这些命令不会调用 agent 或模型：

```powershell
python -m unittest discover -s tests -v
python 'C:\Users\83577\.codex\skills\.system\skill-creator\scripts\quick_validate.py' `
  .\Skill\solve-gaia-r12-trench-volume
python 'C:\Users\83577\.codex\skills\.system\skill-creator\scripts\quick_validate.py' `
  .\Skill\solve-high-pressure-fluid-volume
python .\run_gaia_sample.py --help
```
