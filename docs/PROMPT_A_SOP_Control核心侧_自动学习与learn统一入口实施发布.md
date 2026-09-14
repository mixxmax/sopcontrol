# Prompt A：SOP Control 核心侧实施与发布

> 用法：把本文件全文交给一个运行在 /Users/xiezhijie/sopcontrol 的执行模型。
> 目标：完成 SOP Control 自身的“默认自动识别 + 必要提醒 + 显式 /learn”能力。
> 前置：不依赖 JobsFlow；本 Prompt 不允许修改 JobsFlow 仓库。

---

## 你要执行的任务

你第一次接触 SOP Control。请在当前仓库内完成以下能力，并将其做成一个可被其他产品 Adapter 使用的稳定控制平面能力：

~~~
默认自动观察
    → 任务/阶段级汇总
    → 必要时调用一次受限 LLM 提炼
    → 结构化 Learning Proposal
    → 宿主显示确认提示
    → 用户选择控制层/文档/两者/仅本次/忽略
    → 控制层确认后进入 Registry、compile、select、enforce
~~~

同时保留显式入口：

~~~
/learn 或宿主等价请求
    → 指定当前会话、任务、阶段或主题
    → 复用同一个窗口、提炼、校验、确认和持久化流程
~~~

最终产品体验必须是：用户不需要主动记住 /learn，正常工作时系统可以无感观察；只有确实发现值得长期保留的经验时才提醒；用户想主动整理时仍可以显式使用 /learn。

---

## 0. 先读、先验证、不要相信自报

动代码前必须阅读：

1. 根目录 AGENTS.md、README.md、README_ZH-CN.md；
2. sopcontrol/model.py、registry.py、candidate.py、dynamic_sop.py、intent.py、project.py、cli.py；
3. 现有动态 SOP、候选、Registry、投影、桥接和测试；
4. docs/SOP_Control_自动学习与显式learn双入口统一规则提炼技术手册_2026-09-14.md；
5. 与动态规则、规则生命周期、低成本执行有关的既有手册。

然后用源码、测试和命令验证现状。尤其检查：

- 是否已经有 LearningEvent、LearningWindow、EvidenceBundle、LearningProposal；
- 是否已经有窗口级多事件汇总，而不是只有单句 observation；
- 当前 CLI 是否有 learn 或等价入口；
- 是否已经有宿主可消费的通知协议；
- Distiller 输出是否可以直接写 Registry；
- 普通消息路径是否会调用 LLM。

不要把 README、既有报告或注释中的“已完成”当作证据。没有源码和测试证据的项目必须标记 UNPROVEN。

---

## 1. 不得越界

本任务只修改 SOP Control 仓库。严禁：

- 修改 /Users/xiezhijie/ai-job-search；
- 修改 JobsFlow 业务代码、业务状态机、业务语义审查器或产品文档内容；
- 直接读写或修改 .sopcontrol/ 内文件来绕过正规命令；
- 让大模型直接写 Registry、规则账本或宿主文件；
- 每条消息调用一次 LLM；
- 启动常驻监督子 Agent；
- 因为一次模型错误就自动生成永久规则；
- 因为用户没有点击弹窗就默认接受；
- 把 /learn 写入文档当成运行时控制已经接入；
- 为了通过测试降低门槛、删除负向测试或吞掉失败。

已有实现如果满足要求，复用并补测试，不要平行重建第二套候选、确认或 Registry 流程。

---

## 2. 必须实现的产品架构

最终必须形成以下结构：

~~~
Host Adapter
  → LearningEvent Collector
  → LearningWindow
  → Deterministic Trigger/Aggregator
  → Optional Distiller Adapter
  → Proposal Validator
  → Notification Seam
  → Decision Router
  → Registry lifecycle / document handoff / session-only
~~~

这是“两个入口、一个管道”，不是两套系统：

~~~
自动观察 ─┐
          ├─> 同一个 Learning Proposal 流程
/learn  ──┘
~~~

按深 Module 设计：

- 核心 Module 暴露小而稳定的 Interface；
- 窗口切分、证据筛选、去重、归并、校验和成本控制隐藏在 Implementation 中；
- Claude/OpenCode/Codex/Antigravity/CLI 是 Adapter；
- LLM 是可替换 Distiller Adapter，不是规则权威；
- UI 是 Notification Seam，核心不能依赖某个桌面产品。

---

## 3. 必须存在的数据模型

若仓库已有等价模型，兼容扩展；不要创建同义重复模型。

### 3.1 LearningEvent

事实事件，不是规则：

~~~
event_id: le-...
event_type: user_correction | user_instruction | model_action | tool_call |
            control_denial | accepted_resolution | plan_change |
            cost_signal | task_boundary
source:
  adapter: claude | opencode | codex | antigravity | cli | product
  ref: 会话/消息/工具调用/任务引用
task_id: optional
session_id: optional
phase: optional
product: optional
actor: optional
occurred_at: ISO-8601
exact_quote: optional
actual: optional
expected: optional
action: optional
operation: optional
metadata: redacted structured data
~~~

不变量：

- 原话存在时必须逐字保留；
- 事件必须有可追溯来源；
- 不得保存 secret、token、cookie、授权值或未脱敏正文；
- 事件只能描述发生过的事，不能声明规则已生效；
- 同一事件重复提交必须幂等。

### 3.2 LearningWindow

任务/阶段级回顾范围：

~~~
window_id: lw-...
task_id: optional
session_id: optional
phase: optional
time_start: optional
time_end: optional
event_refs: []
status: open | ready | reviewed | no_candidate | failed
max_events: ...
max_input_chars: ...
max_llm_calls: 0 or 1
digest: ...
~~~

窗口在任务完成、阶段结束、重复错误即将发生或用户显式 /learn 时关闭/回顾。不能每条消息重新回顾全历史。

### 3.3 LearningProposal

提案是未授权的建议：

~~~
proposal_id: lp-...
window_id: lw-...
source:
  type: automatic_observation | explicit_learn | external_rule_file | product_adapter
  ref: ...
evidence_refs: []
original_quotes: []
summary: ...
rule_class: constitution | dynamic_sop | natural_logic | unknown
trigger: {}
must: []
must_not: []
may: []
exceptions: []
non_goals: []
scope: {}
durability: permanent_candidate | once_only_candidate | uncertain
recommended_destination: control | document | both | once_only | none
confidence: high | medium | low | not_proven
related_rule_ids: []
unsupported_claims: []
status: proposed | presented | deferred | rejected | accepted_control |
        accepted_document | accepted_both | once_only | compiled | blocked
~~~

强制字段：evidence_refs、summary、trigger、must、must_not、exceptions、non_goals、confidence。

模型建议的 rule_class 和 recommended_destination 只能是建议，不能代表用户选择。

---

## 4. 自动识别和窗口级汇总

### 4.1 默认观察必须低成本

普通消息路径：

- 不调用 LLM；
- 不启动 Agent；
- 不申请高影响 capability ticket；
- 只追加轻量事件或本地缓冲；
- 不写永久 Registry；
- 不弹窗。

### 4.2 确定性触发器

先由纯函数或确定性代码决定是否值得回顾。

高价值信号：

- “以后、今后、每次、始终、长期、默认”等持久性表达；
- 用户明确纠正执行顺序、范围、修正策略或停止条件；
- 用户指出模型扩大了不必要的处理范围；
- 同一执行模式被重复纠正；
- 模型即将再次执行已被否定的路径。

中价值信号：

- 单次“应该先 A 再 B”；
- 工具调用被用户要求撤回/重做；
- 计划改变且最终解决方式可能复用。

低价值信号：

- 格式、拼写、措辞调整；
- 只对本次有效的范围；
- 没有执行影响的偶然偏好；
- 只有模型推断、没有用户认可的自然逻辑。

建议规则：

| 信号 | 行为 |
|---|---|
| 无信号 | 静默 |
| 只有低信号 | 只保留 observation |
| 一个高信号 | 在自然边界汇总并生成提案 |
| 两个同主题中信号 | 归并后生成提案 |
| “仅本次” | 只能进入 once-only 分支 |
| 证据冲突 | not_proven，不强制 |
| 同一指纹重复 | 升级优先级，不重复弹同一卡片 |

阈值集中配置，必须测试边界值。

### 4.3 汇总必须是“归并”，不是复制

归并时：

1. 按共同目标、对象、动作和顺序聚类；
2. 删除岗位名、具体 ID、具体时间等一次性细节；
3. 保留先后顺序、过滤条件、范围上限、停止条件和例外；
4. 将“不应该做”放入 must_not 或 non_goals；
5. 不同目标不得强行合并；
6. 相互冲突的意见拆分或标记 not_proven；
7. 已有同义规则形成修订提案，不创建重复规则；
8. 原话和证据永远保留。

### 4.4 默认逻辑必须保留反向路径

自然逻辑提案必须写成：

~~~
默认采用最自然、最经济的路径；
用户明确改变目标、存在真实依赖或产品强规则时允许反向执行。
~~~

不得把“先过滤再评分”自动扩大成“所有任务永远先过滤再评分”。

---

## 5. LLM Distiller Adapter

### 5.1 LLM 的权限

LLM 只负责：

- 从已筛选证据中提炼摘要；
- 将多次纠正归并成一条候选经验；
- 提炼触发条件、必须做、不得做、例外和非目标。

LLM 不能：

- 写 Registry；
- 修改规则账本；
- 自行确认用户；
- 新增没有证据的业务事实；
- 改变用户的规则分类或永久性决定；
- 调用宿主写文件或执行命令。

### 5.2 调用预算

- 每个窗口默认最多一次调用；
- 自动路线不因每条事件调用模型；
- /learn 可以强制回顾，但仍只回顾一个有界窗口；
- 重试最多一次并使用幂等键；
- 无 LLM 时核心仍可运行并返回 not_proven 或待整理候选。

### 5.3 输出约束

Distiller 必须输出结构化 JSON，至少包含：

~~~
{
  "schema_version": "1",
  "window_id": "lw-001",
  "proposals": [],
  "no_candidate_reason": ""
}
~~~

每一条 proposal 必须有证据引用、适用范围、正向动作、负向边界、例外和非目标。解析失败、引用不存在、字段缺失或含有执行命令时，标为 not_proven，不得进入控制层。

---

## 6. 确认卡和 Notification Seam

核心不直接弹窗，只输出结构化通知：

~~~
{
  "notification_type": "learning_proposal",
  "proposal_id": "lp-001",
  "priority": "normal",
  "interrupt": false,
  "title": "发现一条可能需要长期保留的执行规则",
  "summary": "先筛选目标子集，再执行高成本处理。",
  "scope_summary": "当前产品的搜索/评分阶段",
  "evidence_count": 4,
  "available_decisions": [
    "control", "edit_control", "document", "both",
    "once_only", "defer", "reject"
  ]
}
~~~

卡片必须展示：摘要、适用范围、必须做、不得做、例外、非目标、证据数量和“尚未生效”提示。

决策语义：

- control：进入控制规则正规生命周期；
- edit_control：以用户编辑后的结构化内容进入生命周期；
- document：交给产品文档机制，不写 Registry；
- both：创建关联的文档记录和控制规则；
- once_only：只写会话级记录；
- defer：保持 pending，不自动过期；
- reject：拒绝并按指纹抑制重复。

没有 UI 时提供 CLI/JSON 降级。没有用户点击时不能默认任何决定。

---

## 7. /learn 入口

实现 learn review 或同等语义的入口，支持：

~~~
/learn
/learn 只提炼当前任务中关于执行顺序的长期经验
/learn 回顾最近一次失败修复
~~~

显式入口可以跳过自动触发阈值，但不能跳过窗口裁剪、证据校验、Distiller schema 校验、用户选择和控制层生命周期。

外部宿主提交的 /learn 结果、AGENTS/Rules/Skills 文件变化只能作为：

- explicit_learn 提案；或
- external_rule_file 提案。

不得直接获得 Registry 权限。SOP Control 自己的投影块必须排除在外部导入之外，防止投影回环。

---

## 8. 控制层和文档层分流

用户选择控制层后必须复用已有正规链路：

~~~
Proposal → Candidate/confirm → Rule → accepted → compile → select → active
~~~

确认后的 dynamic_sop：

- 无 TTL；
- 重启、换模型、换 harness 后仍存在；
- 只有显式修订、暂停或退役才能改变；
- 未激活只表示当前上下文不匹配，不是过期。

文档-only：

- 不进入 Registry；
- 不伪装成运行时控制；
- 不覆盖用户文档；
- 可保留 proposal/digest 关联。

两边都写：控制规则和文档条目共享 proposal_id，但拥有独立 digest 和生命周期。

---

## 9. 与现有代码的改造顺序

按以下顺序实现，已经满足的部分只补证明：

### P0：基线与数据模型

- 保护现有 dynamic/candidate/registry 行为；
- 新增或统一四个核心模型；
- 增加旧 observation/candidate 到新模型的转换；
- 证明 observation/candidate 不会直接拦截运行时。

### P1：窗口、触发、归并

- 任务/阶段窗口；
- 事件裁剪和脱敏；
- 确定性触发；
- 主题归并、冲突拆分、同义去重；
- 关联已有规则。

### P2：Distiller 和提案确认

- Distiller Interface；
- fake adapter；
- real adapter（仅在当前环境允许时）；
- schema、证据、权限、超时和降级；
- 提案确认和持久化路由。

### P3：CLI 和宿主通知

- learn review/list/show/decide/ingest 或等价命令；
- Notification JSON；
- CLI 降级；
- /learn 输入 Adapter；
- 文档导入去回环。

### P4：成本和发布

- 调用数、token、延迟、弹窗率、接受率指标；
- 正常消息零 LLM；
- 单窗口最多一次 Distiller；
- 全量测试、gate、包构建和干净环境冒烟。

---

## 10. 必须通过的测试

至少覆盖：

1. 普通聊天不弹窗；
2. 一次低价值偏好不写永久规则；
3. 明确长期表达形成高优先级候选；
4. 多次分散纠正归并为一条提案；
5. 不同目标不会错误合并；
6. 冲突证据变成 not_proven；
7. “仅本次”不进入 Registry；
8. Distiller 输出没有证据时被拒；
9. Distiller 不能写 Registry；
10. 用户未点击不等于接受；
11. control/document/both 分流正确；
12. defer 不自动过期、不重复刷屏；
13. /learn 复用同一管道；
14. 外部文档只形成提案；
15. 自有投影不会回环；
16. accepted→compiled→active 顺序正确；
17. dynamic_sop 重启后仍存在；
18. natural_logic 允许用户明确反向目标；
19. 普通路径 LLM 调用数为 0；
20. 单窗口最多一次 LLM 调用；
21. LLM 超时/不可用可以降级；
22. secret 不出现在事件、提案、通知和日志；
23. 不启动常驻监督 Agent；
24. 无真实宿主时诚实标记 UNPROVEN。

---

## 11. 验收和发布

根据实际仓库入口运行：

~~~
python3 -m pytest -q
ruff check .
git diff --check
python3 -m sopcontrol.cli gate
~~~

如果仓库有 sopctl，运行等价命令。必须完成：

- 包构建；
- 干净环境导入；
- 版本探针；
- 新旧规则加载；
- 自动路线演示；
- /learn 路线演示；
- 低成本指标。

发布时：

1. 只提交属于本任务的代码、测试和必要文档；
2. 不把 .sopcontrol/ 中无关的运行状态一把提交；
3. 生成明确版本号和不可变 commit；
4. 在报告中输出：

~~~
SOPCONTROL_VERSION=<version>
SOPCONTROL_COMMIT=<clean commit>
PACKAGE_DIGEST=<digest>
~~~

如果没有明确 push 授权，只提交并报告 commit，不要自行推送。没有干净 commit 就不能让 JobsFlow 更新 vendor。

---

## 12. 最终报告格式

~~~
# SOP Control 自动学习双入口实施报告

## A. 结论
- 状态：Complete / Partial / Blocked
- 自动观察：PASS / PARTIAL / UNPROVEN
- 窗口级汇总：PASS / PARTIAL / UNPROVEN
- LLM Distiller：PASS / PARTIAL / UNPROVEN
- 提案确认：PASS / PARTIAL / UNPROVEN
- /learn 入口：PASS / PARTIAL / UNPROVEN
- 控制层生命周期：PASS / PARTIAL / UNPROVEN
- 文档/控制分流：PASS / PARTIAL / UNPROVEN
- Notification Seam：PASS / PARTIAL / UNPROVEN

## B. 修改清单
逐文件写原因、Interface 和测试。

## C. 真实演示
提供自动路线和 /learn 路线各一份 evidence bundle、proposal 和 decision。

## D. 成本
报告正常路径 LLM=0、每窗口调用数、token、延迟、弹窗率。

## E. 负向证据
列出直接写 Registry、无证据提案、未确认生效、once-only 晋升、文档回环等测试。

## F. 发布信息
版本、干净 commit、包摘要、是否已 push。

## G. 未完成
逐项写原因、证据和关闭条件；不能用“理论上支持”替代真实证据。
~~~

