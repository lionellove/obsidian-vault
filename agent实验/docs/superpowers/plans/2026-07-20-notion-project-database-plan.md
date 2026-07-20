# Notion Project Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Notion 中搭建一套 Projects + Tasks 双 Database 系统，用于追踪项目状态流与里程碑阶段，并通过 Obsidian 链接实现内容联动。

**Architecture:** 采用两个相互关联的 Notion Database：Projects 承载项目目标、阶段、状态与 Obsidian 索引；Tasks 承载具体任务状态、优先级、工时与 Obsidian 笔记链接。通过 Relation 与 Rollup 实现项目完成百分比的自动汇总。

**Tech Stack:** Notion（Database、Relation、Rollup、Views、Automations）、Obsidian（Markdown 笔记、Obsidian URL）

## Global Constraints

- 项目类型字段选项：学术研究 / 个人管理 / 内容创作 / 其他
- 项目阶段字段选项：选题立项 / 资料收集 / 方案设计 / 执行实施 / 分析总结 / 输出交付 / 已完成
- 项目状态字段选项：未开始 / 进行中 / 阻塞 / 已完成 / 已搁置
- 任务状态字段选项：未开始 / 进行中 / 阻塞 / 待验收 / 已完成 / 已取消
- 优先级字段选项：P0 / P1 / P2 / P3
- 任务类型字段选项：研究 / 写作 / 实验 / 开发 / 会议 / 杂项
- Obsidian 链接使用 `obsidian://open?vault=...&file=...` 格式
- 命名约定：Notion 项目名 = Obsidian 文件夹名；Notion 任务名 = Obsidian 任务笔记标题

---

## File Structure

| 文件/位置 | 用途 |
|-----------|------|
| `docs/superpowers/specs/2026-07-20-notion-project-database-design.md` | 设计规格文档（已存在） |
| `docs/superpowers/plans/2026-07-20-notion-project-database-plan.md` | 本实施计划文档 |
| Notion 页面：`Projects` database | 项目级管理 |
| Notion 页面：`Tasks` database | 任务级管理 |
| Obsidian vault：`Projects/项目名称/README.md` | 项目内容索引页 |
| Obsidian vault：`Projects/项目名称/任务/任务名.md` | 任务内容笔记 |

---

### Task 1: 创建 Projects Database

**Files:**
- Create: Notion 页面 `Projects`（Full page database）

**Interfaces:**
- Consumes: 无
- Produces: Projects Database，供 Task 2 建立 Relation

- [ ] **Step 1: 新建 Database**
  - 在 Notion 中新建页面，标题为 `Projects`
  - 选择 `Database` → `Full page`
  - 初始模板选择 `Blank`

- [ ] **Step 2: 添加基础字段**
  将默认的 `Name` 字段重命名为 `项目名称`（保持 Title 类型）。
  按顺序添加以下字段：

  | 字段名 | 类型 | 选项 |
  |--------|------|------|
  | 项目类型 | Select | 学术研究, 个人管理, 内容创作, 其他 |
  | 当前阶段 | Select | 选题立项, 资料收集, 方案设计, 执行实施, 分析总结, 输出交付, 已完成 |
  | 项目状态 | Select | 未开始, 进行中, 阻塞, 已完成, 已搁置 |
  | 优先级 | Select | P0, P1, P2, P3 |
  | 开始日期 | Date | - |
  | 截止日期 | Date | - |
  | 项目目标 | Text | - |
  | Obsidian 索引 | URL | - |

- [ ] **Step 3: 添加统计字段（先占位，Relation 在 Task 3 建立后补全）**
  - 添加 `关联任务` 字段，类型选择 `Relation`，目标 Database 选择 Task 2 创建的 `Tasks`（若 Tasks 尚未创建，先跳过，Task 3 再回来设置）
  - 添加 `任务总数` 字段，类型选择 `Rollup`
  - 添加 `已完成任务` 字段，类型选择 `Rollup`
  - 添加 `完成百分比` 字段，类型选择 `Formula`

- [ ] **Step 4: 验证字段**
  - 打开 Projects 的表格视图
  - 确认字段顺序与上表一致
  - 确认所有 Select 字段的选项无拼写错误

- [ ] **Step 5: 提交进度记录**
  - 在 Obsidian 或本地更新一份进度日志，记录 `Projects Database 字段创建完成`

---

### Task 2: 创建 Tasks Database

**Files:**
- Create: Notion 页面 `Tasks`（Full page database）

**Interfaces:**
- Consumes: 无
- Produces: Tasks Database，供 Task 3 建立 Relation

- [ ] **Step 1: 新建 Database**
  - 在 Notion 中新建页面，标题为 `Tasks`
  - 选择 `Database` → `Full page`
  - 初始模板选择 `Blank`

- [ ] **Step 2: 添加基础字段**
  将默认的 `Name` 字段重命名为 `任务名称`（保持 Title 类型）。
  按顺序添加以下字段：

  | 字段名 | 类型 | 选项 |
  |--------|------|------|
  | 所属项目 | Relation | 指向 Projects Database |
  | 项目阶段 | Rollup | 取所属项目的"当前阶段" |
  | 任务状态 | Select | 未开始, 进行中, 阻塞, 待验收, 已完成, 已取消 |
  | 优先级 | Select | P0, P1, P2, P3 |
  | 任务类型 | Select | 研究, 写作, 实验, 开发, 会议, 杂项 |
  | 计划日期 | Date | - |
  | 截止日期 | Date | - |
  | 实际完成日 | Date | - |
  | 预计工时 | Number | 格式：Number |
  | 实际工时 | Number | 格式：Number |
  | Obsidian 笔记 | URL | - |
  | 前置任务 | Relation | 指向 Tasks Database（自引用） |
  | 阻塞原因 | Text | - |
  | 描述 | Text | - |

- [ ] **Step 3: 配置 Rollup 字段"
  - `项目阶段` Rollup 配置：
    - Relation: `所属项目`
    - Property: `当前阶段`
    - Calculate: `Show original`

- [ ] **Step 4: 验证字段**
  - 打开 Tasks 的表格视图
  - 确认字段顺序与上表一致
  - 确认 Relation 字段指向正确的 Database

---

### Task 3: 建立 Projects 与 Tasks 的 Relation 和 Rollup

**Files:**
- Modify: Notion `Projects` Database
- Modify: Notion `Tasks` Database

**Interfaces:**
- Consumes: Projects Database（Task 1）、Tasks Database（Task 2）
- Produces: 完整的 Relation/Rollup 配置

- [ ] **Step 1: 在 Projects 中建立指向 Tasks 的 Relation**
  - 打开 Projects Database
  - 编辑 `关联任务` 字段
  - Relation type 选择 `Two-way relation`
  - 目标 Database 选择 `Tasks`
  - 目标 Database 中的反向字段命名为 `所属项目`（与 Task 2 中已有的字段合并）

- [ ] **Step 2: 配置任务总数 Rollup**
  - 编辑 `任务总数` 字段
  - Relation: `关联任务`
  - Property: `任务名称`
  - Calculate: `Count all`

- [ ] **Step 3: 配置已完成任务 Rollup**
  - 编辑 `已完成任务` 字段
  - Relation: `关联任务`
  - Property: `任务状态`
  - Calculate: `Count values`
  - Filter: `任务状态` is `已完成`

- [ ] **Step 4: 配置完成百分比 Formula**
  - 编辑 `完成百分比` 字段
  - Formula 输入：
  ```
  prop("任务总数") == 0 ? 0 : prop("已完成任务") / prop("任务总数") * 100
  ```
  - 格式选择 `Percent`（如果 Formula 输出数值）或保持 Number 显示为 `%`

- [ ] **Step 5: 验证汇总逻辑**
  - 在 Projects 中创建一个测试项目
  - 在 Tasks 中创建 3 个任务并关联到该项目
  - 将其中 1 个任务状态改为"已完成"
  - 检查 Projects 中是否显示：任务总数=3，已完成任务=1，完成百分比=33.33%

---

### Task 4: 配置 Projects 的 Views

**Files:**
- Modify: Notion `Projects` Database

**Interfaces:**
- Consumes: Projects Database（Task 1）
- Produces: 5 个 Projects 视图

- [ ] **Step 1: 创建"项目总览"表格视图**
  - 视图类型：Table
  - 排序：优先级 Ascending（P0 在前）
  - 显示字段：项目名称, 项目类型, 当前阶段, 项目状态, 优先级, 截止日期, 完成百分比

- [ ] **Step 2: 创建"阶段看板"视图**
  - 视图类型：Board
  - Group by: `当前阶段`
  - 排序：优先级 Ascending
  - 卡片显示：项目状态, 完成百分比

- [ ] **Step 3: 创建"状态看板"视图**
  - 视图类型：Board
  - Group by: `项目状态`
  - 排序：优先级 Ascending
  - 卡片显示：当前阶段, 完成百分比

- [ ] **Step 4: 创建"本月聚焦"视图**
  - 视图类型：Table
  - 过滤：`开始日期` is within `this month` OR `截止日期` is within `this month`
  - 排序：截止日期 Ascending

- [ ] **Step 5: 创建"画廊视图"**
  - 视图类型：Gallery
  - 卡片封面：None
  - 卡片属性显示：当前阶段, 项目状态, 完成百分比, 截止日期

- [ ] **Step 6: 验证视图**
  - 切换到每个视图，确认分组、排序、过滤正常工作
  - 确认看板可以拖拽项目卡片改变阶段或状态

---

### Task 5: 配置 Tasks 的 Views

**Files:**
- Modify: Notion `Tasks` Database

**Interfaces:**
- Consumes: Tasks Database（Task 2）
- Produces: 6 个 Tasks 视图

- [ ] **Step 1: 创建"任务清单"表格视图**
  - 视图类型：Table
  - 排序：截止日期 Ascending
  - 显示字段：任务名称, 所属项目, 任务状态, 优先级, 截止日期, 任务类型

- [ ] **Step 2: 创建"状态流看板"视图**
  - 视图类型：Board
  - Group by: `任务状态`
  - 排序：优先级 Ascending
  - 卡片显示：所属项目, 截止日期

- [ ] **Step 3: 创建"今日待办"视图**
  - 视图类型：Table
  - 过滤：`计划日期` is `today`
  - 排序：优先级 Ascending

- [ ] **Step 4: 创建"本周计划"视图**
  - 视图类型：Table
  - 过滤：`计划日期` is within `this week`
  - 排序：截止日期 Ascending

- [ ] **Step 5: 创建"按项目分组"视图**
  - 视图类型：Board
  - Group by: `所属项目`
  - 排序：任务状态（自定义顺序：未开始, 进行中, 阻塞, 待验收, 已完成, 已取消）

- [ ] **Step 6: 创建"阻塞项"视图**
  - 视图类型：Table
  - 过滤：`任务状态` is `阻塞`
  - 显示字段：任务名称, 所属项目, 阻塞原因, 截止日期

- [ ] **Step 7: 验证视图**
  - 切换到每个视图，确认分组、排序、过滤正常工作
  - 在状态流看板中拖拽任务卡片，确认状态会改变

---

### Task 6: 创建 Obsidian 项目结构模板

**Files:**
- Create: Obsidian vault 目录 `Projects/`
- Create: Obsidian 模板文件 `Templates/项目索引模板.md`（推荐）

**Interfaces:**
- Consumes: 无
- Produces: Obsidian 项目目录结构与 README 模板

- [ ] **Step 1: 创建项目根目录**
  - 在 Obsidian vault 中创建文件夹 `Projects/`

- [ ] **Step 2: 创建项目索引模板**
  - 在 Obsidian 中创建 `Templates/项目索引模板.md`，内容如下：
  ```markdown
  # {{title}}

  - Notion 项目页：[链接]
  - 目标：
  - 当前阶段：
  - 关键截止日期：

  ## 关键笔记
  - [[相关资料]]

  ## 任务日志
  - [ ]
  ```

- [ ] **Step 3: 创建示例项目目录**
  - 在 `Projects/` 下创建 `示例研究项目/`
  - 子目录：`资料/`, `笔记/`, `任务/`
  - 根目录文件：`README.md`

- [ ] **Step 4: 填写示例 README**
  - 使用项目索引模板生成 `Projects/示例研究项目/README.md`
  - 将 `{{title}}` 替换为 `示例研究项目`
  - 在 Notion 中创建对应项目，填入 Obsidian 索引 URL

- [ ] **Step 5: 验证链接跳转**
  - 在 Notion 的 Projects 中点击 `Obsidian 索引` URL
  - 确认 Obsidian 打开并定位到 `Projects/示例研究项目/README.md`

---

### Task 7: 添加示例数据并验证端到端流程

**Files:**
- Modify: Notion `Projects` Database
- Modify: Notion `Tasks` Database
- Modify: Obsidian `Projects/示例研究项目/`

**Interfaces:**
- Consumes: 所有已配置的 Database 和视图
- Produces: 可运行的示例项目

- [ ] **Step 1: 创建示例项目**
  - 在 Projects 中新建：`示例研究项目`
  - 项目类型：`学术研究`
  - 当前阶段：`资料收集`
  - 项目状态：`进行中`
  - 优先级：`P0`
  - 开始日期：今天
  - 截止日期：30 天后
  - 项目目标：完成一份关于 Agent 研究调研的报告
  - Obsidian 索引：填入 Task 6 生成的链接

- [ ] **Step 2: 创建示例任务**
  在 Tasks 中创建以下任务并关联到 `示例研究项目`：

  | 任务名称 | 任务状态 | 优先级 | 任务类型 | 计划日期 | 截止日期 |
  |----------|----------|--------|----------|----------|----------|
  | 确定研究范围 | 已完成 | P0 | 研究 | 今天 | 3 天后 |
  | 收集核心文献 | 进行中 | P0 | 研究 | 今天 | 7 天后 |
  | 整理文献笔记 | 未开始 | P1 | 写作 | 7 天后 | 14 天后 |
  | 撰写调研报告 | 未开始 | P0 | 写作 | 14 天后 | 30 天后 |

- [ ] **Step 3: 验证自动汇总**
  - 回到 Projects，查看 `示例研究项目`
  - 确认：任务总数=4，已完成任务=1，完成百分比=25%

- [ ] **Step 4: 验证任务阶段继承**
  - 打开 Tasks 的表格视图
  - 确认所有示例任务的 `项目阶段` 字段都显示 `资料收集`

- [ ] **Step 5: 验证视图过滤**
  - 打开 Projects 的"阶段看板"，确认示例项目位于"资料收集"列
  - 打开 Tasks 的"状态流看板"，确认 4 个任务分布在对应状态列
  - 打开 Tasks 的"阻塞项"，确认没有示例任务（因为状态都不是阻塞）

- [ ] **Step 6: 测试 Obsidian 任务笔记**
  - 为任务"收集核心文献"在 Obsidian 中创建 `Projects/示例研究项目/任务/收集核心文献.md`
  - 将 Obsidian URL 填入该任务的 `Obsidian 笔记` 字段
  - 在 Notion 中点击链接，确认能跳转到 Obsidian 笔记

---

### Task 8: 配置可选 Notion 自动化

**Files:**
- Modify: Notion `Tasks` Database
- Modify: Notion `Projects` Database

**Interfaces:**
- Consumes: 已配置的数据库字段
- Produces: 自动化规则（如付费计划支持）

- [ ] **Step 1: 检查 Notion 计划权限**
  - 进入 Settings → Plans
  - 确认是否有 Automation 功能权限
  - 如果无权限，跳过本 Task，记录"当前计划不支持自动化"

- [ ] **Step 2: 创建"任务完成自动记录完成日"规则**
  - 触发：When `任务状态` is changed to `已完成`
  - 动作：Edit page → `实际完成日` → Set to `Today`

- [ ] **Step 3: 创建"任务阻塞自动上报项目风险"规则**
  - 触发：When `任务状态` is changed to `阻塞`
  - 动作：Edit page in `所属项目` → `项目状态` → Set to `阻塞`

- [ ] **Step 4: 创建"所有任务完成自动收尾项目"规则**
  - 触发：When `任务状态` is changed to `已完成`
  - 条件：All tasks in `所属项目` have `任务状态` is `已完成`
  - 动作：Edit page in `所属项目` → `项目状态` → Set to `已完成`
  - 动作：Edit page in `所属项目` → `当前阶段` → Set to `已完成`

- [ ] **Step 5: 验证自动化**
  - 将示例任务"收集核心文献"状态改为"已完成"
  - 确认 `实际完成日` 自动填充为今天
  - 将所有示例任务改为"已完成"
  - 确认 `示例研究项目` 的项目状态自动变为"已完成"

---

### Task 9: 编写使用说明并归档

**Files:**
- Create: `docs/superpowers/specs/2026-07-20-notion-project-database-usage.md`（可选）
- Modify: `docs/superpowers/plans/2026-07-20-notion-project-database-plan.md`

**Interfaces:**
- Consumes: 所有已完成的配置
- Produces: 使用说明文档

- [ ] **Step 1: 创建使用说明文档**
  - 在 `docs/superpowers/specs/` 下创建 `2026-07-20-notion-project-database-usage.md`
  - 内容包含：
    - 如何新建项目
    - 如何拆解任务
    - 如何推进任务
    - 如何做周回顾
    - 常见视图的使用场景

- [ ] **Step 2: 更新本计划文档**
  - 在文末添加"实施完成总结"小节
  - 记录实际实施日期、遇到的问题、最终数据库链接（可选）

- [ ] **Step 3: 提交文档**
  - 将新增的使用说明文档加入 git
  - 提交信息：`docs: add Notion project database usage guide`

---

## Self-Review

### Spec Coverage

| Spec 章节 | 对应 Task |
|-----------|-----------|
| Projects Database 字段 | Task 1 |
| Tasks Database 字段 | Task 2 |
| Relation 与 Rollup | Task 3 |
| Projects Views | Task 4 |
| Tasks Views | Task 5 |
| Obsidian 联动机制 | Task 6 |
| 示例流程 | Task 7 |
| 可选自动化 | Task 8 |
| 使用说明 | Task 9 |

### Placeholder Scan

- 无 TBD/TODO
- 无 "add appropriate error handling" 等模糊描述
- 所有 Formula、Rollup 配置均已给出具体参数
- 所有视图的分组/排序/过滤条件均已给出

### Type Consistency

- `任务状态` 选项在 Task 2、Task 3、Task 8 中保持一致
- `当前阶段` 选项在 Task 1、Task 3、Task 7 中保持一致
- `所属项目` Relation 在 Task 2 中创建，Task 3 中配置 Two-way relation
- `完成百分比` Formula 在 Task 3 中给出，避免除以零

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-20-notion-project-database-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
