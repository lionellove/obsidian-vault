# Skill Package 自进化：ALFWorld Stage 0 可执行实验计划

状态：经 `grill-me` 访谈确认  
确认日期：2026-08-25  
实验性质：低成本 viability study；不承担统计显著性结论

本文件把[原始研究构想](./实验计划.md)收敛为第一轮可以直接实现和运行的实验。thinking/reasoning 配置的文献依据见[调查笔记](./thinking-mode-research.md)。

---

## 1. Stage 0 要回答的唯一问题

在冻结同一个 `DeepSeek-V4-Flash` Executor、使用相同执行反馈和相同验证预算时：

> 对 Skill Package 进行局部、可追踪的 Structured Semantic Patch，是否比不进化更有效，并且至少不明显差于完整重写 Skill Package IR？

主比较为：

1. **No Evolution**：始终使用共同的初始 Skill Package \(S_0\)；
2. **Structured Patch**：对 \(S_0\) 应用绑定到一个 Root Cause 的结构化增量 \(\Delta\)；
3. **Full IR Rewrite**：在相同证据下完整生成 \(S'\)，但仍服从同一个 Skill Package schema。

Stage 0 的证据目标不是证明最终 SOTA，而是确认下面这条链中已经出现可重复研究的正向信号：

\[
Trajectory
\rightarrow FailureIR / PreservationIR
\rightarrow RootCause
\rightarrow RepresentationChoice
\rightarrow SkillUpdate
\rightarrow PairedValidation
\]

### 1.1 Stage 0 不回答的问题

- 不比较 Graph runtime 与 flat runtime；
- 不实现基于当前状态的 subgraph routing；
- 不比较不同 Artifact 组合的完整消融；
- 不比较 Atomic edit 与 Multi-edit Semantic Patch；
- 不使用 expert trajectory 做主实验的知识蒸馏；
- 不在 `valid_seen` 或 `valid_unseen` 上调参；
- 不做显著性或 SOTA 声称。

这些问题只有在 Stage 0 通过 stop/go gate 后才进入后续实验。

---

## 2. 固定模型与角色配置

所有 LLM 角色使用 DeepSeek 官方 API 和同一个模型 ID：

```text
base_url: https://api.deepseek.com
model: deepseek-v4-flash
```

|角色|Thinking|Reasoning effort|作用|
|---|---|---|---|
|\(S_0\) Generator|enabled|max|生成预算内尽可能好的共同初始 Skill|
|Agent Executor|disabled|不适用|逐步选择一个 admissible action|
|Failure Analyzer|enabled|max|把失败轨迹转为 representation-neutral Failure IR|
|Success Analyzer|enabled|max|从成功轨迹抽取 Preservation IR|
|Root Cause Merger|enabled|max|跨实例聚类、抽象、估计 scope 和排序|
|Structured Patch Generator|enabled|max|选择 Artifact 类型并输出增量 Patch IR|
|Full Rewrite Generator|enabled|max|输出完整替换后的 Skill Package IR|
|Semantic Verifier|enabled|max|blind semantic audit，无否决权|
|Structural Verifier|无 LLM|不适用|确定性 schema 和图结构检查|

### 2.1 必须显式固定的请求参数

- Executor 必须在实际请求中显式发送 `thinking.type=disabled`；仅设置 `temperature=0` 不等于关闭 thinking。
- Executor 使用 `temperature=0`，并设置足够小的输出上限，只允许返回一个动作。
- thinking 模式下采样参数可能不生效；meta roles 仍需记录最终请求体。
- Structured Patch 与 Full Rewrite 的对应角色使用相同 reasoning effort、上下文和输出 token 上限。
- 保存服务端返回的 `model`、`system_fingerprint`、request ID 和时间戳；模型 alias 变化时不得把前后运行合并为同一实验。

### 2.2 Executor 输出协议

Executor 每步只能返回：

```text
FINAL_ACTION: <从当前 admissible actions 中逐字复制一个动作>
```

解析器只能容忍展示层噪声，最终执行值必须映射回唯一的原始 admissible action。不得允许索引、同义词、局部匹配或模型发明动作。

---

## 3. 数据防火墙与任务抽样

### 3.1 数据来源

Stage 0 只使用 ALFWorld `train`。`valid_seen` 和 `valid_unseen` 在最终 Skill 冻结前完全不可运行。

已有实验接触过的 10 个 `valid_unseen` 任务永久列入 contaminated diagnostic set，不得进入未来正式 unseen 主指标。

### 3.2 54 个唯一任务

六个 task family 各抽取 9 个全新任务：

1. Pick & Place；
2. Examine in Light；
3. Clean & Place；
4. Heat & Place；
5. Cool & Place；
6. Pick Two & Place。

每个 family 内再分配：

|集合|每类任务数|合计|用途|
|---|---:|---:|---|
|Calibration|3|18|检查 \(S_0\) 地板/天花板|
|Evolution|3|18|收集成功与失败轨迹|
|Patch-validation|3|18|比较 \(S_0\)、Patch、Rewrite|

### 3.3 去重与分组规则

- 汇总仓库现有 config 和 result 中出现过的 task ID，形成 denylist；
- exact task ID 不得复用；
- 根据 `task_type`、scene、goal template、目标物体、目标 receptacle、movable receptacle 和 sliced 状态建立 near-duplicate group key；
- 同一 group 不得跨 calibration、evolution、patch-validation；
- 固定抽样 seed 为 `20260825`；
- 输出三个 task manifest、denylist 和 SHA-256；
- manifest 冻结后，任何任务替换都必须创建新的实验版本。

### 3.4 环境固定项

```yaml
env_type: AlfredTWEnv
domain_randomization: false
max_steps: 50
environment_seed: fixed
```

validation 的三个条件使用六种运行顺序的 balanced permutation；18 个任务中每种排列恰好出现 3 次，以降低 API 时间漂移、缓存和固定顺序偏差。

---

## 4. 共同初始 Skill Package \(S_0\)

### 4.1 生成输入

\(S_0\) Generator 只能看到：

- 六类 ALFWorld task family 的公开定义；
- 环境 action/observation 的通用语义；
- 本实验的 Skill Package schema；
- deterministic renderer 的格式说明。

不得看到任何 calibration、evolution、validation 实例、轨迹、expert plan 或已有实验的 revised skill。

### 4.2 质量与复杂度预算

模型被要求在预算内生成它认为最好的通用 Skill，不得人为挖缺陷：

- workflow nodes：6–12；
- 每类非 workflow Artifact：最多 8 项；
- 渲染后最多 1,200 个英文词；
- 禁止具体 object ID、scene、任务实例和未经观察的位置先验。

### 4.3 Human gate

人只检查：

- schema 是否合法；
- 是否存在实例泄漏；
- 六类任务是否均可适用；
- 是否自相矛盾；
- 是否违反长度与组件预算。

人不得直接添加或改写语义。不通过时，只把违反的 gate 条目返回给模型重新生成，最多 3 次。通过后冻结：生成 prompt、原始响应、IR、渲染文本和全部哈希。

### 4.4 Calibration gate

在18个 calibration 任务上只运行冻结的 \(S_0\)：

- 4–14 个成功：进入 evolution；
- 0–3 个成功：地板效应，停止；
- 15–18 个成功：天花板效应，停止。

不得查看具体失败后再修改 \(S_0\)。若配置不具备可识别区间，应另建实验版本，而不是在当前 Stage 0 内调优。

---

## 5. 最小 Skill Package IR

```yaml
skill_package:
  schema_version: "0.1"
  package_id: "alfworld-stage0-s0"
  entry_node: "parse_goal"

  nodes:
    - id: "parse_goal"
      type: "decision"
      instruction: "..."
      scope: {level: "global"}

  edges:
    - id: "e_parse_search"
      source: "parse_goal"
      target: "search_target"
      condition: "the required target location is not established"

  constraints:
    - id: "c_admissible_only"
      scope: {level: "global"}
      rule: "..."

  verifications:
    - id: "q_target_state"
      target: "transform_object"
      criterion: "..."
      on_failure: "f_retry_transform"

  fallbacks:
    - id: "f_retry_transform"
      trigger: "the requested state is not established"
      target: "transform_object"
      max_retries: 1
```

### 5.1 受控枚举

Node type：

```text
action | decision | verification | terminal
```

Scope level：

```text
global | task_family | workflow | local
```

`instance` scope 不允许 commit。`task_family` 必须引用六类枚举之一；`local` 必须引用现有 node。

### 5.2 Stage 0 runtime

Stage 0 不实现外部 graph controller。每一步均由同一个 deterministic renderer 将完整 Package 渲染成文本：

1. workflow nodes 与条件边；
2. constraints；
3. verifications；
4. fallbacks；
5. scope 信息。

Structured Patch、Full Rewrite 和 \(S_0\) 必须使用完全相同的 renderer。每一步记录实际注入的文本和 input token。

---

## 6. Representation-neutral Failure IR

Failure IR 只描述缺失的执行语义，不提前指定应该写成 workflow、constraint、verification 或 fallback。

```yaml
failure:
  failure_id: "f_003"
  defect_type: "missing_state_confirmation"
  location:
    trajectory_steps: [12, 13]
    related_skill_ids: ["transform_object"]
  evidence:
    observation: "..."
    expected_semantics: "establish the required state before final placement"
  cause: "the policy proceeds without establishing the postcondition"
  scope:
    level: "task_family"
    target: "heat_and_place"
  patchability: "skill_patchable"
  confidence: 0.86
```

建议的 representation-neutral defect types：

```text
missing_prerequisite
wrong_ordering
missing_state_confirmation
recovery_failure
repeated_exploration
constraint_violation
non_skill_execution_error
insufficient_evidence
unknown
```

Analyzer 可读取完整失败轨迹、当前 \(S_t\)、task goal、admissible actions、reward 和 termination；不得读取 expert trajectory、PDDL plan、隐藏状态或目标位置。

---

## 7. Preservation IR

成功轨迹形成只用于防回归的 Preservation IR：

```yaml
preservation:
  preservation_id: "keep_004"
  behavior: "acquire the located target before navigating to its destination"
  scope:
    level: "task_family"
    target: "pick_and_place"
  supported_by: ["trace_02", "trace_08"]
  related_skill_ids: ["acquire_target"]
  confidence: 0.91
```

Preservation IR 不自动加入 Skill。它只告诉两个 Generator 哪些现有行为不应被无意破坏。

---

## 8. Root Cause Merge 与选择

Merger 对所有 Failure IR 执行：

```text
clustering + abstraction + scope estimation + support counting + ranking
```

Root Cause schema：

```yaml
root_cause:
  root_cause_id: "rc_002"
  semantic_defect: "..."
  scope: {level: "task_family", target: "heat_and_place"}
  supported_by:
    - {failure_id: "f_003", trace_id: "trace_03"}
    - {failure_id: "f_011", trace_id: "trace_11"}
  contradictory_evidence: []
  patchability: "skill_patchable"
  priority: 1
```

Stage 0 只选择排名最高且满足以下条件的一个 Root Cause：

- 至少两个不同实例支持；
- scope 不为 `instance`；
- `skill_patchable`；
- supporting evidence 不互相矛盾。

其余 Root Causes 只记录，不进入本轮 Generator。

---

## 9. 两种 evolution 接口

两个 Generator 只能看到：

- 当前 \(S_t\)；
- 被选中的 Root Cause IR；
- Preservation IR；
- 去实例化后的最小 evidence snippets；
- support 数量与 trace/step 引用。

它们不读取完整原始轨迹，也不重新执行 Failure Analysis。

### 9.1 Structured Semantic Patch

```yaml
semantic_patch:
  patch_id: "p_rc_002"
  diagnosis_binding:
    root_cause_id: "rc_002"
    interpreted_defect: "..."
    evidence_refs: ["trace_03:12", "trace_11:9"]
  representation_decision:
    selected_components: ["verification", "fallback"]
    rationale: "..."
  preservation_impact:
    - preservation_id: "keep_004"
      impact: "preserved"
      rationale: "..."
  edits:
    - op: "ADD"
      kind: "VERIFICATION"
      value: {...}
      addresses: ["rc_002"]
    - op: "ADD"
      kind: "FALLBACK"
      value: {...}
      addresses: ["rc_002"]
```

允许的 primitive operations：

```text
ADD | UPDATE | DELETE
```

允许的 kinds：

```text
NODE | EDGE | CONSTRAINT | VERIFICATION | FALLBACK
```

一个 Semantic Patch 可以包含多个协同 edits，但所有语义变化必须只服务同一个 Root Cause。

### 9.2 Full Skill Package IR Rewrite

```yaml
full_rewrite:
  diagnosis_binding: {...}
  preservation_impact: [...]
  rewritten_skill_package: {...完整 S'...}
  change_manifest:
    - change: "ADD|UPDATE|DELETE"
      kind: "..."
      target_id: "..."
      addresses: ["rc_002"]
      rationale: "..."
```

Full Rewrite 可重写完整状态，但：

- 输出仍必须满足同一个 Skill Package schema；
- 每个语义差异都必须出现在 `change_manifest`；
- 每个变化必须绑定同一个 Root Cause；
- 不得顺手修复其他问题；
- 使用与 Structured Patch 相同的 evidence 和推理预算。

任意 Markdown `SKILL.md` 重写不属于主实验，可作为未来补充实验。

### 9.3 NO_PATCH

如果证据不足，两个 Generator 都可以输出 `NO_PATCH`，但必须引用 Root Cause 并说明为什么无法形成有证据支持的修改。`NO_PATCH` 是实验结果，不触发重新采样。

---

## 10. 候选预算与格式修复

每种方法只有一次 semantic generation。

格式处理顺序：

1. 使用 JSON structured output 和 schema；
2. 做确定性规范化，例如 code fence、Unicode、尾逗号、可唯一确定的包装；
3. 如仍不可解析，最多 3 次 format-only LLM repair。

Format repair 只能改变括号、引号、字段位置、类型包装或 schema 外壳，不得改变：

- edit 数量与顺序；
- op、kind、target、scope、ID；
- instruction、rule、criterion、condition、rationale；
- Root Cause 或 Preservation 绑定。

修复前后对可提取语义字段计算 canonical fingerprint。无法证明语义不变，则候选判为非法，而不是算作格式修复成功。

---

## 11. 三层验证

### 11.1 Deterministic Structural Verifier：硬门槛

至少检查：

- schema 与 enum；
- ID 唯一；
- entry node 存在；
- edge source/target 存在；
- node 从 entry 可达；
- 无 dangling reference；
- verification target 与 on_failure 存在；
- fallback target 存在且 retry 有界；
- 删除操作不会破坏引用完整性；
- scope 引用合法且不为 instance；
- 每项变化绑定唯一选中的 Root Cause；
- Full Rewrite 的 change manifest 与实际 IR diff 一致；
- 长度与组件预算。

### 11.2 LLM Semantic Verifier：只审计

Semantic Verifier 接收候选时隐藏：

- 候选来自 Patch 还是 Rewrite；
- validation 成绩；
- Generator 的方法标签。

输出：

```text
relevance
generality
contradiction
redundancy
over_specificity
root_cause_coverage
preservation_risk
```

它没有否决权。只要结构合法，候选必须进入动态验证。

### 11.3 Dynamic Validation：最终有效性证据

在同一18个 patch-validation 任务上分别运行：

```text
S0
Apply(S0, StructuredPatch)
FullRewrite(S0)
```

环境 success/failure 是最终行为证据。

---

## 12. 90-episode 运行矩阵

|阶段|条件|任务数|Episodes|
|---|---|---:|---:|
|Calibration|\(S_0\)|18|18|
|Evolution rollout|\(S_0\)，两种方法共享|18|18|
|Patch-validation|\(S_0\)|18|18|
|Patch-validation|Structured Patch|18|18|
|Patch-validation|Full Rewrite|18|18|
|**总计上限**|||**90**|

如果某候选为 `NO_PATCH` 或结构非法，则不运行其18个 validation episodes，实际用量低于90；该方法记为未产生可验证候选。

---

## 13. 指标与 stop/go gate

### 13.1 配对行为指标

对每个候选与 \(S_0\) 的相同任务结果定义：

- `Repair`：\(S_0\) 失败、候选成功；
- `Regression`：\(S_0\) 成功、候选失败；
- `Stable success`：二者均成功；
- `Stable failure`：二者均失败；
- `NetGain = Repairs - Regressions`。

### 13.2 Structured Patch 的 Stage 0 go 条件

必须同时满足：

1. Calibration 位于 4–14/18；
2. 至少存在一个符合条件的 Root Cause；
3. Structured candidate 通过 Structural Verifier；
4. `NetGain >= 2`；
5. `Regressions <= 1`；
6. 渲染后 Skill word count 相对 \(S_0\) 增长不超过 50%；
7. Structured Patch 的成功数不比 Full Rewrite 少超过 1 题；若 Rewrite 无合法候选，则单独记录，不能自动算 Structured 胜出。

任一项不满足，Stage 0 不扩样，先做失败归因。

### 13.3 分开报告、不合成加权分数

主指标是配对 `NetGain`。另外分别报告：

- 总成功率和六类 task-family 成功向量；
- repairs、regressions、stable success、stable failure；
- 成功与失败 episode 的 steps 分布；
- invalid output、format repair、max-step termination 和循环行为；
- prompt input、cache-hit、cache-miss、reasoning、output tokens；
- API 成本、模型延迟、episode wall time；
- 渲染后 words/characters；
- nodes、edges、constraints、verifications、fallbacks 数量；
- \(S_0\rightarrow S'\) 的 canonical IR edit distance；
- format repair 次数与 candidate validity；
- Semantic Verifier 和 human audit 结果。

Stage 0 不选择 \(\lambda\) 或 \(\mu\)，不计算任意的 performance-complexity 加权总分。可展示 Pareto 关系，但不据此声称统计胜出。

### 13.4 统计边界

18个 validation 任务只用于探索性信号：

- 报告原始配对表和描述性区间；
- 不报告显著性胜出；
- 不因 p-value 选择候选；
- Stage 1 才预注册 exact McNemar 和 paired bootstrap。

---

## 14. Blind human audit

Human audit 不进入 evolution loop，也不影响候选接受。

审计者可以看：失败轨迹、Failure IR、Root Cause、候选修改以及隐藏的 ALFWorld expert plan；但必须隐藏：

- 候选来自 Structured Patch 还是 Full Rewrite；
- 动态 validation 成绩。

固定 rubric：

1. Failure IR 是否有直接轨迹证据；
2. Root Cause 是否解释实际失败；
3. scope 是否可跨实例复用；
4. 是否把非 Skill 错误误判为 Skill 缺陷；
5. Representation Choice 是否适合该语义缺陷；
6. 多个 edits 是否共同解决同一个 Root Cause；
7. 是否出现没有证据的新规则；
8. 是否破坏 Preservation IR。

理想情况下两名审计者独立评分并报告一致率；只有一名审计者时明确标为 exploratory single audit。

---

## 15. 失败归因与下一步

|观察|解释优先级|下一步|
|---|---|---|
|Calibration <20%|Executor/S0 地板|停止；检查执行协议与新实验设置|
|Calibration >80%|天花板|停止；另建更有辨识度的设置|
|无重复 Root Cause|失败过于分散或 Analyzer 不稳定|审计 Failure IR，不生成 Patch|
|候选结构非法|schema/生成接口问题|修实现；不扩 rollout|
|Root Cause 正确但候选语义错|Representation Choice/Generator 问题|改进接口后另建版本|
|候选语义合理但动态无增益|Executor 未遵循或规则不可操作|比较受影响步骤和动作|
|Patch 有增益且 Rewrite 更强|Structured locality 主张暂不支持|检查 edit budget 与表示限制|
|Patch 有增益、回归更少、复杂度受控|viability signal|设计 Stage 1 确证实验|

Expert-contrast 只能作为后续补充实验：保持其他条件相同，向 Analyzer 增加 expert trajectory，以区分 self-feedback 与 teacher distillation。

---

## 16. 必须保存的实验产物

建议目录：

```text
results/skillgraph_stage0/<run_id>/
├── preregistration.yaml
├── code_state.json
├── manifests/
│   ├── denylist.json
│   ├── calibration.json
│   ├── evolution.json
│   └── patch_validation.json
├── s0/
│   ├── generation_prompt.txt
│   ├── raw_response.json
│   ├── skill_package.json
│   └── rendered_skill.md
├── trajectories/
│   ├── calibration/
│   ├── evolution/
│   └── validation/
├── ir/
│   ├── failures.jsonl
│   ├── preservations.jsonl
│   └── root_causes.json
├── candidates/
│   ├── structured_patch/
│   └── full_rewrite/
├── verifier/
│   ├── structural.json
│   └── semantic_blind.json
├── audit/
│   ├── blinded_packet.json
│   └── human_scores.json
└── report/
    ├── paired_outcomes.csv
    ├── metrics.json
    └── stage0_report.md
```

`code_state.json` 至少记录：

- Git commit 和 dirty-worktree diff hash；
- Python 与依赖版本；
- ALFWorld 数据版本；
- evaluator、prompt、schema、renderer 和 Skill 哈希；
- DeepSeek model ID、system fingerprint 和所有请求参数；
- task manifest hash；
-开始/结束时间、错误与重试。

---

## 17. 实现顺序

严格按下面顺序开发，避免同时调试整个闭环：

1. 定义并测试 Skill Package schema；
2. 实现 deterministic renderer；
3. 定义 Patch DSL 与 Full Rewrite envelope；
4. 实现 `Apply(Patch)` 和 canonical IR diff；
5. 实现 Structural Verifier 与单元测试；
6. 人工制作一个 Patch，验证 Package 修改、渲染和 Executor 注入闭环；
7. 修改 DeepSeek adapter，显式支持 thinking 配置并完整记录 usage；
8. 实现 denylist、group-aware sampler 和 manifest hash；
9. 生成并冻结 \(S_0\)；
10. 运行18题 calibration；只有通过 gate 才继续；
11. 运行18题共享 evolution rollout；
12. 实现 Failure IR 与 Preservation IR 生成；
13. 实现 Root Cause Merge、support 与 ranking；
14. 生成唯一 Structured Patch 和唯一 Full Rewrite；
15. 完成格式处理、Structural Verifier 和 blind Semantic audit；
16. 随机化运行54个 validation condition-episodes；
17. 计算配对结果与 stop/go gate；
18. 制作 blind human audit packet；
19. 完成 Stage 0 报告，再决定是否设计 Stage 1。

---

## 18. 开跑前检查清单

- [ ] 所有54个任务均未在仓库历史实验中使用；
- [ ] calibration/evolution/validation exact ID 与 group 均不重叠；
- [ ] task manifests 和 denylist 已冻结并哈希；
- [ ] \(S_0\) 未接触任何实验轨迹；
- [ ] Executor 的实际请求明确关闭 thinking；
- [ ] meta roles 的实际请求明确开启 max thinking；
- [ ] Structured 与 Rewrite 输入证据、上下文和预算一致；
- [ ] Failure IR 中没有 Artifact 类型标签；
- [ ] Generator 看不到完整轨迹和 expert plan；
- [ ] 两种方法只处理同一个 Root Cause；
- [ ] Semantic Verifier 不具有硬否决权；
- [ ] Full Rewrite 的 manifest 与真实 diff 可自动核对；
- [ ] validation 条件顺序已做 balanced permutation；
- [ ] 所有 token、成本、fingerprint 和哈希字段可落盘；
- [ ] human audit packet 隐藏方法标签和 validation 成绩；
- [ ] 任何 stop 条件触发后不会自动扩样。

---

## 19. 预算估计

Stage 0 最多90个 episode。按当前仓库轨迹长度与 DeepSeek-V4-Flash 官方价格估计：

- 常见成本约 `US$1–4`；
- 极保守预留 `US$10`；
- meta roles 开启 thinking 的成本远小于逐步 Executor rollout；
- 跑完首批 calibration 后，必须使用真实 cache-hit/cache-miss/reasoning/output token 重新校准估算。

成本只作为资源约束，不作为候选接受分数。

---

## 20. Stage 0 完成定义

只有以下产物全部存在，Stage 0 才算完成：

1. 冻结且可复现的 \(S_0\)；
2. 三个互斥 task manifests；
3. 完整 evolution trajectories；
4. Failure IR、Preservation IR 和 Root Cause；
5. Structured Patch 与 Full Rewrite 原始输出和最终 IR；
6. Structural、Semantic 和 Dynamic 三类验证记录；
7. 18题逐任务配对结果；
8. blind human audit；
9. token、成本、复杂度和回归指标；
10. 明确的 go/no-go 结论及其触发条款。

Stage 0 通过只表示“值得开展更大规模确证实验”，不表示已经证明 Structured Patch 普遍优于 Free Rewrite。
