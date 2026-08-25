# 建构决策记录（DESIGN.md）

本文件沉淀从产品手册（`docs/`）到代码之间的决策。手册回答"是什么、为什么"；
本文件回答"为什么长成这样"。

## 1. 第一性原理：三个不可再分的原子

整个系统无论换什么模型/harness/平台，不可再分的只有：

1. **Rule** —— 用户意图的规范化记录。只存在于 prompt 或文档里的规则不是规则。
2. **Evidence** —— 独立于模型自报的观测（E3/E4 级）。模型说"做完了"永远不是事实。
3. **Verdict** —— 确定性决策函数：`(规则, 事实, 状态) → 判定 + 理由 + 下一步`。

手册的九项能力都是这三个原子的组合。所以最小骨干产物不是某个引擎，而是三原子的
记录系统加纯函数判定器——它是总线，其他一切都是插卡。

## 2. 工程控制论推出的两条硬顺序约束

1. **可观测性先于可控性**：控制一个观测不到的对象必然失控。所以先建传感器与
   比较器（吸收审计器），后建执行器（拦截）。B0 只有观测，B1 才有终点拦截。
2. **先闭环后带宽**：先在最小对象上闭合并验证稳定（fail-closed、无误放行、
   正向对照不误报），再扩展回路带宽（逐步拦截、多 harness）。

三级回路共享同一条总线：快回路（任务内执行控制，B2+）、中回路（规则治理与吸收，
现在）、慢回路（模型/harness 能力校准，B4+）。

## 3. 宪法属性（不允许丑的三件事）

代码可以丑，但这三件事从第一行起就是对的，因为返工代价极高：

1. **记录 schema 的关键字段**：出处、强度、`valid_until`、`input_hash`。
   `valid_until` + `input_hash` 使"复查"成为账本的常驻行为而非一次性事件（Haft
   的教训：证据自带衰减，输入变了旧判定自动 stale）。
2. **判定函数纯度**：`verdict.py` 无 I/O、无 LLM、无隐藏状态。挑衅式宪法测试
   `test_purity.py` 把 `open` 炸掉后判定必须照常工作。判定器也不信任检测器——
   吸收等级由它从 Evidence 独立推导，Finding 仅被引用。
3. **每个判定自带解释**：`reason` + `next_action` 永远非空，禁止只返回
   `illegal_transition` 这类无法行动的信息。

## 4. 记录 id 内容寻址，且不含时间戳

Evidence/Finding 的 id 由内容 hash 生成，排除时间字段。效果：同一现场重复审计
产生相同 id，账本追加自动去重——审计幂等，账本不会随重复运行膨胀。这也是防篡改
校验（`Ledger.verify()`）的基础。

## 5. 语料的三层结构（通用性住在分层里）

- **模式库**（`corpus/patterns.yaml`）：产品中立的断口模式，如
  `documented_rule_no_consumer`。
- **夹具**（`corpus/fixtures/`）：模式在不同领域的最小现场。三领域起步：
  求职域蒸馏（JobsFlow 历史断口）、电商域、CI 域。
- **用例**（`corpus/cases.yaml`）：模式 × 夹具 × 期望判定，直接变成 pytest
  表驱动断言（OPA `opa test` 的形态）。

**双域验证规则**：一个模式至少在两个不相关领域夹具上命中，才算
`proven-on-multi-domains`。通用性靠经验检验，不靠直觉宣布。骨干代码零业务词汇。

"什么才算一条规则的消费者"不由宏大定义回答：每条规则显式声明
`consumer_markers`，其合理性由语料逐模式回答。这是诚实的 v0 限定。

## 6. 吸收等级的克制

`documented → wired → wired_and_tested → enforced`。**v0 最高只颁发
`wired_and_tested`**：enforced 需要手册 6.5 的七条件（含运行时 trace 与 bypass
分析），宪法测试显式断言 v0 永不颁发 enforced——宁可不声称，不制造治理幻觉。

## 7. 实效性验证：借业界便宜的路

调研结论（见 `docs/research/`）：没有一家同类产品建了庞大的验证子系统。采用
四件套——语料即测试（表驱动 + fail-on-empty）、`explain`（判定函数免费暴露）、
账本（本身就是仪器）、诚实登记表（RESIDUAL_RISKS.md，CC Safety Net 的做法）。
挑衅式测试（把 open 炸掉、篡改账本、正向对照）住宪法测试，不住新模块。

## 8. 阶段地图

| 阶段 | 内容 | 出口判据 |
|---|---|---|
| B0 行走骨架（现在） | 三原子 + registry + ledger + verdict + CLI + 1 组插件 + 语料 | 四条验收全过 |
| B1 终点执行器 | git hook / CI 消费 verdict + `sopctl self-test` | 真实阻断 + fail-closed |
| B2 快回路 | task contract + envelope + 单 harness 逐步 gateway | 手册 14.1 场景 1–9 |
| B3 有界修复 | gap contract → 隔离 worktree → 两轮熔断 | 修复收敛、无越权 |
| B4 校准与投影 | 能力握手、跨平台投影、接管包 | 换模型不重蹈副作用 |

每阶段内部三步循环：插一个模块 → 语料加它的挑衅用例 → 质检决定保留还是拔掉。

## 9. 自应用

模式库对准控制平面自身就是治理幻觉探针：一个没有真实运行时读取的 policy、一个
从没被触发过的 gate、一条没有挑衅测试的规则，状态都只能是 documented。B1 起，
`sopctl self-test` 将成为第一条把控制器自身当审计对象的用例。

## 10. B2 决策：任务状态机与完成门（2026-08-23 补）

**不新增第四种真相。** TaskContract / Envelope 是三原子的组合：契约引用 Rule，
完成判定消费 Verdict，每步迁移写 Envelope 记录（可回放）。无独立数据库——任务
就是 `.sopcontrol/tasks/TASK-xxxx.yaml`，revision 字段防旧上下文覆盖新状态（手册 5.5）。

**状态机刻意收窄**（相对手册 5.7）：`contract_proposed → executing →
verification_pending → verified | repair_required | blocked | failed_unverified；
verified → delivered`。INTAKE 并入 open（创建即带完整契约字段），PLAN_VALIDATED
与 DELIVERY_PREVIEW 留到有真实 plan/副作用时再加——先闭环后带宽。`blocked` 与
`failed_unverified` 为终态：前者需人工，后者是修复预算耗尽（默认两轮，手册 10.5）。

**完成判定复用吸收等级**：任务的 required_rules 全部 `pass` 才可 verified——
"声称接线了规则 X"由审计器独立证实（E3），不信自报。有 `fail`（绕过存活）→
blocked（策略违反，模型不可自行绕过）；有 `gap` → repair_required（可修）。

**范围走私不进 blocked**：submit 的 changed 超出 allowed_writes → 拒绝该次
submit、留在 executing，自行改路径可重试（可自愈）；blocked 留给策略违反与
信任根问题。路径先规范化，绝对路径与 `..` 直接拒绝。

**任务语料**：`corpus/task_cases.yaml` 以脚本化步骤驱动真实 API（拷贝夹具到
临时目录后执行），覆盖手册 14.1 中当前层能诚实覆盖的场景（2/5/8/9/11 + 正向
对照 + 篡改）；场景 1/6/7 依赖 harness 与模型层，登记到 B4，不造假覆盖。

**意图编译器 v0 = 确定性种子**：`sopctl intake` 从 doc_scan 证据生成
CandidateRule（status=observed，落 candidates.yaml），晋升必须显式
`rule add`——LLM 分类器是未来的插件位，产 Candidate、永不写终态（手册 5.2）。

**verifier 自证防护（2026-08-24 补，14.1 场景6）**：`manifest.yaml` 声明
`controller_paths`（构成控制器/验证器自身的路径前缀；本仓库为 sopcontrol/ 与
plugins/）。任务的 changed_paths 落在其中且未提交基线（git status 脏）→ 完成门
直接 blocked（手册 9.3：不得在被验证代码与验证器同改后自行批准）；git 不可用
fail-closed 视为脏。提交基线后照常裁决。这把"改 verifier 自证通过"从信任问题
降级为流程问题：先 commit（可审计），再验证。彻底方案仍是 CI 从可信分支验证
（手册 9.3 末条），单机 v1 到此为止。

## 11. B4 决策：capability handshake（模型维度，2026-08-25 补）

**问题**：harness 画像只答"这台工具有没有钩子"；控制强度还要跟*模型实测能力*
走（手册 5.9）。品牌名不可信——同一 harness 换模型后行为方差大。

**不新增第四种真相。** 模型画像是慢回路校准产物，落盘
`.sopcontrol/model-profile.yaml`；契约仍是 Rule/Evidence/Verdict 的组合。
调节只动已有旋钮：`max_repairs` 与 `allowed_writes` 粒度——不发明新权限，
更强模型只拿更大表达空间，副作用上限不变。

**三维探针（合成评测，脊柱零 LLM）**：
1. `json_stability`——能否只吐合法 JSON（偶发失败→更严 schema / 更少轮次）
2. `boundary_follow`——声明的改动是否落在给定写入范围（越界→文件级粒度）
3. `instruction_follow`——是否服从显式约束（跳步倾向→更紧预算）

打分是确定性字符串/JSON 检查；响应由夹具注入或显式文件提供（本切片不强制
烧真实 token）。三探针全过 → `strong`；JSON 或指令失手 → `fragile`；边界失手
→ `weak`；无画像 → `unknown`（保持默认，不假装测过）。

**旋钮映射（纯函数 `control_knobs`）**：

| tier | max_repairs | write_granularity |
|---|---|---|
| strong / unknown | 2 | prefix（目录前缀可） |
| fragile | 1 | prefer_file（目录可，记录建议） |
| weak | 1 | file（open 时拒绝纯目录前缀） |

**接入点**：`task open` 在用户未显式改 `--max-repairs`（仍为默认 2）时读取画像
套用；显式传参优先于画像。`accept` 对 `file` 粒度再拦一道，理由可行动。
harness 画像与模型画像并列，不互相覆盖。

## 12. 场景1 决策：对话意图层 v0（2026-08-25 补）

**问题**：用户说「只讨论，不修改」时，模型仍可能改代码——讨论被误判为实施授权
（手册 14.1 场景1 / Phase 0 验收）。

**脊柱仍零 LLM。** 分类器是确定性插件位：`classify_utterance` 纯函数，按显式
标记词判定 `discuss_only` / `implement` / `rule_candidate` / `unknown`。LLM 分类器
仍是未来插卡，约定不变——只产 Candidate，永不写终态（与 intake 文档路径一致）。

**产物**：
- 会话意图落盘 `.sopcontrol/session-intent.yaml`（`intent` + `source_excerpt`）；
- 永久政策句 → `candidates.yaml`（status=observed），晋升仍须 `rule add`；
- `harness-check` 在 CLI 边界读会话意图并注入决策函数：`discuss_only` 时拒绝
  Write/Edit（bash 仍走既有受控清单，不在本切片扩面）。

**不做什么**：不自动开任务、不自动 accept 规则、不把「讨论」写成实施 envelope。
清除 discuss_only 靠用户说出实施标记（或 `sopctl intent clear`）。
