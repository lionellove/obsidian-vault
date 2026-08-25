# Skill evolution 实验中的 thinking / reasoning 配置调查

调查日期：2026-08-25

## 结论先行

现有一手资料**不支持**“skill evolution 实验通常都关闭 thinking”这一概括。更准确的结论是：

1. **任务执行阶段关闭 thinking 有直接先例。** Trace2Skill 的官方复现配置明确让 Qwen3.5 执行 rollout、验证和 error analysis 使用 `enable_thinking: false`；HSI 更进一步，明确解释其设计目的：任务阶段关闭 thinking 以限制单步能力上限，进化阶段再开启 thinking。
2. **进化阶段的做法不统一。** Trace2Skill 的 skill evolution 使用 `enable_thinking: true`；HSI 使用同一个 DeepSeek-V4-Flash、进化阶段 `thinking_enabled: true` 且 `reasoning_effort: max`；SKILL-KD 则报告 student、teacher 均使用 `medium reasoning effort`。
3. **SkillOpt 的公开材料需要按模型族区分。** 论文默认配置为 `reasoning_effort: medium`；但当前官方配置明确写着：将 Qwen thinking mode 固定为 `disabled` 可复现论文中已发表的 non-thinking 数字。不能把这一点外推为所有 GPT 实验也关闭 reasoning。
4. **EvoSkill 没有充分报告 thinking 配置。** 论文说明使用 Claude Code + Opus 4.5，但论文和公开默认配置没有给出 extended-thinking 开关或预算；因此只能归为“未报告”，不能推断为关闭。
5. 对本项目最贴近的先例是 **HSI**：它也使用官方 DeepSeek-V4-Flash，并明确采用“Executor off / Evolver on”。因此，如果 Stage 0 决定所有角色都先关闭 thinking，这是一个合理的低成本 viability 设计，但属于我们的实验选择，并非既有工作的统一标准。

## 判定口径

本文严格区分以下状态：

- **显式 thinking=off**：论文或官方代码实际发送关闭开关，例如 `enable_thinking: false` 或 `thinking_enabled: false`。
- **显式 reasoning>off / thinking=on**：论文报告非零 reasoning effort，或官方配置实际发送开启开关。
- **接口无独立 thinking 开关**：实验所用接口/模型在所报告配置中没有独立开关；这不等于模型内部“不推理”。
- **未报告**：论文和作者公开配置都没有足够信息确定模式。模型名、`temperature=0` 或没有输出 chain-of-thought 均不能单独证明 thinking 已关闭。

## 一手证据总表

| 工作 | 任务执行模型与配置 | Analyzer / Evolver / Optimizer 配置 | 判定 | 与本项目的关系 |
|---|---|---|---|---|
| **SkillOpt** | 论文覆盖 GPT-5.5、GPT-5.4 系列、GPT-5.2、Qwen3.5-4B、Qwen3.6-35B-A3B；ALFWorld 为 direct-chat、最多 50 steps。论文明确说 teacher/student 默认 `medium reasoning effort`。但论文同期 v0.1.0 Qwen backend 默认且实际发送 `enable_thinking=false`。 | 默认 optimizer 为 GPT-5.5、medium reasoning；Qwen backend 会忽略共享 `reasoning_effort`，并使用独立 thinking 开关。 | **Qwen target：显式 non-thinking；GPT teacher/student：medium reasoning，不是 off。** | 证明 non-thinking target 仍可通过外部 skill 获益，但不能证明同模型 analyzer/evolver 也应关闭。 |
| **SKILL-KD** | student：Qwen3.5-4B 或 Qwen3.6-35B-A3B；teacher：Qwen3.7-plus 或 ChatGPT-5.5。 | consolidation agent 使用对应 teacher；论文 Appendix A 明确说 teacher 和 student calls 默认均为 `medium reasoning effort`。 | **显式非零 reasoning；不是 thinking=off。** 温度、top-p 未报告。 | ALFWorld 最接近的方法之一，但不支持“关闭 thinking 是必要步骤”。 |
| **Trace2Skill** | 官方 SpreadsheetBench 复现用 Qwen3.5-122B-A10B。rollout、训练集验证、held-out 评测和 error-analysis 使用 `qwen3.5_..._instruct_reasoning.json`，其中 `enable_thinking: false`、`temperature: 1.0`、`top_p: 1.0`。 | success analysis 与 skill evolution 使用 `...thinking_reasoning.json`，其中 `enable_thinking: true`、`temperature: 1.0`、`top_p: 0.95`。 | **显式分角色：Executor off；部分分析与 Evolver on。** | 非常直接地支持“执行关、进化开”的角色分离；也说明 `temperature` 不能替代 thinking 开关。 |
| **HSI** | DeepSeek-V4-Flash；BabyAI 官方 config 为 harness `thinking_enabled: false`、`temperature: 0.0`。README 明确说 task-time thinking off 是为了限制 per-step ceiling。 | 同一 DeepSeek-V4-Flash；顶层 LLM `thinking_enabled: true`、`reasoning_effort: max`，用于 evolver/meta-evolver。 | **显式分角色：同模型 Executor off / Evolver on。** | 与计划中的模型和角色结构最接近，是采用分角色 thinking 的最强直接先例。 |
| **EvoSkill** | 论文全部实验使用 Claude Code + Opus 4.5。 | 官方 config 公开 `harness.name` 与 `model`，但论文/公开默认配置没有报告 extended-thinking 开关、thinking token budget 或 temperature。 | **未报告。** 不能把 Claude Code 的默认行为当作实验配置。 | 可借鉴 failure-driven evolution 和 held-out selection，不能用来支持 thinking on/off 决策。 |

本次选取的工作中，没有一个能可靠归为“所用模型/接口本身无 thinking 开关”：Qwen 与 DeepSeek 有显式开关，GPT 实验报告 reasoning effort，而 EvoSkill 的 Claude Code 设置只是缺少报告。故没有用“接口无开关”替“未报告”填补证据空白。

## 逐项证据

### 1. SkillOpt

论文的主实验覆盖七个 target models，并在 ALFWorld 使用最多 50 个环境步骤。论文给出的代表性 ALFWorld run 是 GPT-5.4-nano student + GPT-5.5 optimizer；这不是无 reasoning 的模型组合。[SkillOpt 论文，实验与 qualitative ALFWorld](https://arxiv.org/html/2605.23904)

论文实验设置明确写明 teacher 与 student calls 默认使用 `medium reasoning effort`。[SkillOpt 论文，Default optimizer hyperparameters](https://arxiv.org/html/2605.23904)

论文同期的官方 `v0.1.0` 基础配置将 optimizer/target 设为 GPT-5.5，并将共享 `reasoning_effort` 设为 `medium`。[SkillOpt v0.1.0 base config](https://github.com/microsoft/SkillOpt/blob/v0.1.0/configs/_base_/default.yaml)

但同一版本的 Qwen backend 是明确例外：默认 `ENABLE_THINKING=false`、`temperature=0.7`、`max_tokens=8000`，并实际把 `chat_template_kwargs={"enable_thinking": false}` 放入请求；该 backend 同时丢弃共享 `reasoning_effort` 参数。因此 Qwen3.5-4B / Qwen3.6-35B-A3B（包括 ALFWorld 单元）可以严格归为 non-thinking target，而不是把 `medium` 错误套到 Qwen wire request 上。[SkillOpt v0.1.0 Qwen backend](https://github.com/microsoft/SkillOpt/blob/v0.1.0/skillopt/model/qwen_backend.py)

当前官方基础配置进一步写明：

```yaml
model:
  optimizer: gpt-5.5
  target: gpt-5.5
  reasoning_effort: medium
  # ...
  # Pin "disabled" to reproduce the published non-thinking numbers.
  qwen_chat_thinking_mode: ""  # server_default | enabled | disabled
  optimizer_qwen_chat_thinking_mode: ""
  target_qwen_chat_thinking_mode: ""
```

来源：[SkillOpt 当前 `configs/_base_/default.yaml`](https://github.com/microsoft/SkillOpt/blob/main/configs/_base_/default.yaml)

Qwen backend 进一步将 `disabled` 映射为实际 wire payload：

```python
payload["chat_template_kwargs"] = {
    "enable_thinking": config.thinking_mode == THINKING_MODE_ENABLED
}
```

并允许 optimizer 与 target 分角色覆盖。来源：[SkillOpt `qwen_backend.py`](https://github.com/microsoft/SkillOpt/blob/main/skillopt/model/qwen_backend.py)

需要保留的限定：论文正文没有按每个结果单元完整列出 thinking wire payload；Qwen non-thinking 的最强证据来自论文同期 v0.1.0 的实际 backend 和当前官方复现声明。GPT 的官方请求实现发送 `reasoning_effort=medium`、没有发送 temperature，因此不能把 Qwen 的 `temperature=0.7` 或 thinking-off 结论外推到 GPT。[SkillOpt OpenAI/Azure backend](https://github.com/microsoft/SkillOpt/blob/main/skillopt/model/azure_openai.py) 正式复现实验应固定仓库 commit，并把最终发送的 request body 写入 run metadata，避免 server default 随服务版本变化。

### 2. SKILL-KD

SKILL-KD 的两个配置为：

- Group 1：Qwen3.5-4B student，Qwen3.7-plus teacher/consolidator；
- Group 2：Qwen3.6-35B-A3B student，ChatGPT-5.5 teacher/consolidator。

论文 Appendix A 明确写道：`Teacher and student calls use medium reasoning effort by default.` 它还说明 ALFWorld 每个 episode 最多 50 steps。[SKILL-KD Appendix A, Experimental Details](https://arxiv.org/html/2607.28048#A.Experimental-Details)

因此该工作不能归类为 thinking off。它没有报告 temperature、top-p，也没有给出一个等价于 `enable_thinking=false` 的开关；最稳妥判定是“显式 medium reasoning，其他解码参数未报告”。

### 3. Trace2Skill

官方 reproduction note 使用同一个 `Qwen3.5-122B-A10B`，但为执行与进化准备两份明确不同的生成配置：

```bash
GENERATION_CONFIG=gen_config/qwen3.5_35B_122B_instruct_reasoning.json
THINK_GENERATION_CONFIG=gen_config/qwen3.5_35B_122B_thinking_reasoning.json
```

rollout、error analysis、baseline/evolved validation 和 held-out evaluation 使用 `GENERATION_CONFIG`；success analysis 与 skill evolution 使用 `THINK_GENERATION_CONFIG`。[Trace2Skill 官方 reproduction note](https://github.com/Qwen-Applications/Trace2Skill/blob/main/README.md#4-reproduction-note)

两份配置的关键差异是：

- instruct config：`temperature=1.0`、`top_p=1.0`、`chat_template_kwargs.enable_thinking=false`；
- thinking config：`temperature=1.0`、`top_p=0.95`、`chat_template_kwargs.enable_thinking=true`。

来源：[instruct config](https://github.com/Qwen-Applications/Trace2Skill/blob/main/gen_config/qwen3.5_35B_122B_instruct_reasoning.json)；[thinking config](https://github.com/Qwen-Applications/Trace2Skill/blob/main/gen_config/qwen3.5_35B_122B_thinking_reasoning.json)

这是一条重要方法学证据：`temperature=0` 或 `1` 与 thinking on/off 是两个正交变量，必须分别记录。

### 4. HSI：与 DeepSeek-V4-Flash 计划最接近的直接先例

HSI 不是单一 `SKILL.md` 优化，而是 task harness evolution；但它与本项目非常接近：同一个冻结的 DeepSeek-V4-Flash 同时执行环境任务并改写可部署的外部程序/策略。

作者 README 明确说明设计目的：task-time thinking 被关闭以限制模型单步能力上限，而在改写 harness 时开启 thinking，给 self-modification 最大机会。[HSI 官方 README](https://github.com/TailinZhou/hsi#hierarchical-self-improvement-a-framework-for-task-specific-evolvable-agent-harnesses)

其 BabyAI 公开配置为：

```yaml
llm:
  model: "deepseek-v4-flash"
  temperature: 0.0
  thinking_enabled: true
  reasoning_effort: "max"

harness:
  temperature: 0.0
  thinking_enabled: false
```

来源：[HSI `benchmark_config_goal/balrog_babyai/config.yaml`](https://github.com/TailinZhou/hsi/blob/main/benchmark_config_goal/balrog_babyai/config.yaml#L1-L30)

这与“同一模型，Executor off，evolution components on”的提案几乎同构。它并不证明该选择在 ALFWorld 上一定最优，但证明该控制不是无先例的临时做法。

### 5. EvoSkill

论文明确写明 OfficeQA 等实验使用 Claude Code with Opus 4.5。[EvoSkill 论文 §3.1.2](https://arxiv.org/html/2603.02766#S3.SS1.SSS2)

作者仓库的配置公开了 harness 与 model，例如：

```toml
[harness]
name = "claude"
model = "claude-sonnet-4-6"
```

但论文和公开默认配置没有给出 `thinking` / `extended_thinking`、thinking token budget 或 temperature。[EvoSkill 官方仓库](https://github.com/sentient-agi/EvoSkill)

所以这里只能标为**未报告**。即使底层 Opus 4.5 具备某种 reasoning 能力，也不能据此认定实验开启或关闭了 thinking。

## 对本项目 Stage 0 的建议

### 推荐的预注册配置

如果目标是先用最低成本验证 patch pipeline 是否出现成功信号，可以采用：

```yaml
model: deepseek-v4-flash

executor:
  thinking: disabled
  temperature: 0.0

failure_analyzer:
  thinking: disabled
  temperature: 0.0

root_cause_merger:
  thinking: disabled
  temperature: 0.0

patch_or_rewrite_generator:
  thinking: disabled
  temperature: 0.0

semantic_verifier:
  thinking: disabled
  temperature: 0.0
```

这应被写成 **Stage 0 viability configuration**，而不是宣称为文献标准。理由是：SkillOpt 的 Qwen non-thinking 结果表明 non-thinking target 可以从 skill optimization 获益；但 Trace2Skill、SKILL-KD 与 HSI 都给 evolution-side reasoning 分配了额外能力。

### 必须显式发送开关

DeepSeek 官方 API 当前默认 thinking 为 enabled；OpenAI Chat Completions 格式需要显式发送：

```python
extra_body={"thinking": {"type": "disabled"}}
```

仅设置 `temperature=0` **不会**关闭 thinking。DeepSeek 官方文档还说明 thinking mode 下 temperature/top-p 等采样参数不生效。[DeepSeek Thinking Mode 官方文档](https://api-docs.deepseek.com/guides/thinking_mode/)

因此每次调用至少记录：

- model id 与服务端返回的 model version（若提供）；
- role；
- 最终发送的 `thinking.type`；
- temperature、top_p、max_tokens；
- prompt/input tokens、cache-hit/cache-miss tokens；
- reasoning tokens / `reasoning_content` 是否出现；
- completion/output tokens；
- request id、时间戳和重试次数。

### Stage 0 失败时的诊断顺序

如果 90-episode Stage 0 没有出现 improvement signal，不应立即判定 Structured Patch 无效。先区分：

1. Executor 在 S0 下是否存在足够但非饱和的能力；
2. Failure IR 是否稳定定位到跨实例 root cause；
3. non-thinking Analyzer/Generator 是否生成了语义完整、可执行的候选；
4. candidate 是否通过结构/语义 verifier，却在动态 validation 中无效；
5. 失败是否只发生在 meta roles 的抽象/合并阶段。

若证据指向第 3 或第 5 项，再做一个很小的 **meta-thinking sensitivity**：保持 rollout trajectories、S0、validation tasks 和 patch budget 不变，只把 Analyzer / Merger / Generator / Semantic Verifier 切换为 thinking enabled；Executor 仍保持 off。这样才能区分“patch 表示无效”与“non-thinking meta-agent 没有足够抽象能力”。该敏感性实验应作为诊断，不与主 Stage 0 的结果混在一起。

## 最终判断

- “Executor 关闭 thinking”有强直接先例，尤其是 Trace2Skill 和同样使用 DeepSeek-V4-Flash 的 HSI。
- “所有 evolution 组件也关闭 thinking”有一定可行性依据，但不是这些代表性工作的主流共同设置。
- 先跑全 non-thinking 的 90-episode viability gate 是合理且节省成本的；必须把它预注册成 Stage 0 配置，并保留一个严格控制的小型 meta-thinking sensitivity 作为失败诊断。
