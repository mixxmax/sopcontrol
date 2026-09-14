# SOP Control 最终闭环问题修复执行技术手册

## ——给完全不了解 SOP Control 的外部模型

版本：2026-09-12
适用仓库：/Users/xiezhijie/sopcontrol
当前基线：dcec9fe
文档性质：执行手册，不是产品宣传文档，也不是 JobsFlow/JobsDB 的业务改造手册。

---

## 0. 你接手的任务是什么

你现在接手的是一个已经有较完整测试和控制机制的 Python 项目。上一轮交付声称已经完成最终闭环，但独立复核发现：

1. 普通回归测试通过，并不代表所有控制语义都已经成立。
2. 有效计划、任务结果、Capability Ticket、bridge 执行链之间仍存在不一致。
3. 部分负向场景没有被现有测试真正覆盖。
4. 这次要修的是 SOP Control 自身的控制平面，不是 JobsFlow/JobsDB 的抓取、材料生成或语义审计逻辑。

你的目标不是“让测试数字继续变大”，而是让下面这条链在真实运行中只有一套语义：

~~~text
用户/项目规则
    ↓
Base Profile + Task Profile + Run Override + Actor Capability
    ↓ 规范化、只能收紧、冻结
Effective Control Plan + effective_plan_digest
    ↓
Task Contract / ControlResult / Capability Ticket / Receipt
    ↓ 必须绑定同一份计划、输入、阶段和操作
受控入口 admission
    ↓
实际执行或明确拒绝
~~~

只有当这条链在正向和反向场景都成立时，才可以报告“最终闭环完成”。

---

## 1. 先理解 SOP Control 的产品边界

### 1.1 SOP Control 是什么

SOP Control 是一个 model-neutral、repository-local 的控制平面。它的核心工作是：

- 把用户和项目已经确定的决定记录为可执行的规则和任务契约；
- 将规则编译成当前任务真正有效的控制计划；
- 在模型、harness、session 或阶段切换时保持决定不漂移；
- 在受控入口阻止越权动作、错误阶段、旧结果、旧票据和不一致输入；
- 对控制动作形成可核对的证据和下一步原因。

### 1.2 SOP Control 不是什么

本次修复不能把 SOP Control 变成以下东西：

- 不是第二个 coding agent；
- 不是每次编辑都要调用的独立大模型；
- 不是 JobsFlow 的材料生成器；
- 不是 JobsFlow 的 JD 语义审计器；
- 不是沙箱，不能宣称本地解释器或合作型操作者绝对无法绕过；
- 不是通过增加 ticket 数量来替代业务系统自身的检查；
- 不是通过关闭 enforce、关闭 ticket 或放宽规则来消灭测试失败。

业务系统如果声明“必须先做 JD 贴合度检查”，SOP Control 的职责是确保这个检查被调用、结果被绑定并影响阶段转换；SOP Control 不负责定义 JD 贴合度的业务内容。

### 1.3 本次修复不碰的范围

除非测试需要建立最小夹具，否则不要修改：

- JobsFlow、JobsDB 或其他外部业务产品；
- JD 抓取、材料生成、事实基线内容；
- 业务语义 lint 的规则和算法；
- 用户的业务审计风格；
- .sopcontrol/rules/registry.yaml 的规则本体；
- 已经完成的历史任务和账本内容。

---

## 2. 接手后必须先读的文件

不要直接开始改代码。先按下面顺序读取：

1. README.md：理解产品定位、CLI 和 harness 边界。
2. README_ZH-CN.md：确认中文产品语义与英文一致。
3. DESIGN.md：理解 Rule、Evidence、Verdict、Task、Envelope 的设计决策。
4. PLAYBOOK.md：理解日常任务状态机和交付顺序。
5. SKILL.md：理解 SOP Control 自应用时的操作约束。
6. docs/SOP_Control_最终闭环修复技术手册_2026-09-12.md：理解上一轮闭环的目标和验收定义。
7. 本手册：只处理独立复核后仍然存在的缺口。

首次检查命令：

~~~bash
cd /Users/xiezhijie/sopcontrol

git status --short --branch
git log -1 --oneline
git log --oneline --decorate -8

rg -n "effective_plan|compose_effective|CapabilityTicket|verify_ticket|canonical_payload|handoff|submit_input_digest|stop_after_pass|recheck_unchanged|actor_snapshot" \
  sopcontrol tests docs .github/workflows
~~~

如果工作区已经有改动，先记录哪些是接手前已有的。不要使用以下命令覆盖用户改动：

~~~bash
git reset --hard
git checkout -- .
rm -rf .sopcontrol
~~~

### 2.1 .sopcontrol/ 的硬约束

不得直接编辑、删除或重写 .sopcontrol/ 中任何文件。包括：

- rules；
- tasks；
- ledger；
- evidence；
- projection；
- growth state；
- ticket 账本。

需要改变控制器状态时，只能使用项目已有的 sopctl 子命令。例如：

~~~bash
.venv/bin/python -m sopcontrol.cli task list
.venv/bin/python -m sopcontrol.cli task show TASK-ID
.venv/bin/python -m sopcontrol.cli gate .
.venv/bin/python -m sopcontrol.cli project check
.venv/bin/python -m sopcontrol.cli chronicle check
~~~

如果任务链把你阻断，不要手改任务文件；先查看当前任务和阻断原因，再按 CLI 的合法动作处理。若需要解决一个已阻断任务，应按项目已有的 --resolves 机制另开决议任务，而不是复活旧副作用。

---

## 3. 必须掌握的对象和术语

### 3.1 Profile

Profile 是一组控制规则配置，可能来自四层：

| 层 | 含义 | 是否可以扩大权限 |
|---|---|---|
| Base | 项目或全局基础控制配置 | 作为上限来源 |
| Task | 当前任务声明的约束 | 不可以 |
| Run | 当前一次运行的临时约束 | 不可以 |
| Actor | 当前模型/执行者的能力上限 | 不可以 |

Profile 的原始输入可以不完整，但进入判定器前必须变成完整、规范化、可冻结的有效计划。

### 3.2 Effective Control Plan

Effective Control Plan 是四层配置合成后的唯一结果。判定器、Task、Result、Ticket 和 Receipt 不得各自重新解释原始层。

有效计划至少应有：

- profile_id、revision、schema version；
- required checks 和 excluded checks；
- 每个 check 的最终 mode；
- baseline 的全部字段，包括 source_ref；
- tolerance 全部维度；
- repair 的全部字段；
- budget 全部字段；
- stop_when；
- 规范化后的 expires_at；
- task/base/run/actor 各层摘要和 digest；
- 最终 effective_plan_digest。

### 3.3 Frozen Plan

Frozen Plan 是某个任务在某个 revision 下冻结的 Effective Plan。冻结后：

- 不能就地修改；
- actor 能力变化必须生成新计划；
- run override 变化必须生成新计划；
- 旧的 Result、Ticket、Receipt 不能静默继续用于新计划。

### 3.4 ControlResult 和 Verdict

ControlResult 是一次具体检查的结构化结果。它不是模型的自由文本声明，至少要能绑定：

- task；
- phase；
- baseline；
- input digest；
- effective plan；
- check_id；
- operation/run；
- 判定时间；
- 受控入口状态；
- 结构化 findings 和 evidence。

判定器必须返回固定语义的结果，例如：

~~~text
unknown              无法证明满足或违反，不能当作 pass
block                已证明违反硬约束
not_run              必须检查但没有实际运行
pass_with_warnings   允许继续，但保留警告
pass                 满足当前计划
~~~

### 3.5 Input Digest

Input Digest 是检查输入内容的摘要，不是文件名列表。目录中的文件新增、删除、重命名或内容变化，都必须影响摘要。

### 3.6 Capability Ticket

Capability Ticket 只授权一次受控入口的特定动作。它不是全局通行证，也不是模型自己生成的字符串。

有副作用的 Ticket 至少要绑定：

- project_id；
- task_id；
- phase；
- action；
- operation_id 或稳定 run_id；
- effective_plan_digest；
- capability binding；
- allowed_actions；
- expires_at；
- payload fingerprint。

字段为空时，不能被解释成“任意值”。

### 3.7 Canonical Invocation

Canonical Invocation 是真正要执行的业务命令及其参数的规范表示。它必须保留 argv token 边界。

以下两种参数不能得到同一个指纹：

~~~text
["echo", "a b"]
["echo", "a", "b"]
~~~

包装器路径、$0、临时 handoff 路径、时间戳和 secret 不属于业务命令指纹。

### 3.8 Handoff、Admission、Receipt

~~~text
challenge  签发 ticket，不执行
handoff    将短期票据安全传给子进程
admission  在真正执行入口兑换和验证 ticket
execute    执行业务命令
receipt    保存脱敏后的结果和绑定摘要
~~~

兑换成功不等于父进程已经不需要 secret。父进程必须先取得脱敏所需的 secret，再启动子进程。

---

## 4. 全局不变量：所有修复都必须满足

### 4.1 单一有效计划

所有入口必须消费同一份 frozen effective plan：

~~~text
Base ⊕ Task ⊕ Run ⊕ Actor
       ↓
normalize → validate → compose → freeze
       ↓
effective_plan_digest
~~~

不得存在以下两条不同语义的路径：

~~~text
路径 A：原始 base/task → 自己合并 → 判定
路径 B：frozen effective plan → 判定
~~~

判定器必须只接受有效计划。兼容旧调用者时，应在一个明确的组合入口完成转换后再冻结，不能让判定器内部偷偷 fallback。

### 4.2 只能收紧，不能放宽

下层配置只能使控制更严格：

- mode 只能向更严格方向移动；
- tolerance 不能扩大；
- budget 和 repair 上限取最小值；
- baseline 必须一致；
- stop_when 只能增加；
- expires_at 取更早时间；
- scope 只能变窄；
- actor capability 只能提供更小的可用上限。

任何无法比较的配置都应拒绝，而不是默认采用宽松值。

### 4.3 失败关闭

以下情况绝不能得到 pass：

- 计划字段非法或未知；
- 当前时间缺失而计划有过期时间；
- 时间无时区或不可解析；
- task、phase、plan、operation、input 或 capability 绑定缺失；
- 输入路径逃逸或无法读取；
- ticket 已消费、过期或指纹不匹配；
- handoff 无法读取；
- canonical 参数无法安全重建；
- 子进程执行状态无法确定；
- 受控入口未真实接通。

### 4.4 成本不通过弱化正确性解决

SOP Control 的目标是减少模型无意义的漂移和额外调用，因此允许：

- 只读动作不申请 ticket；
- 同一 task/phase/plan/operation 使用有限的 phase-level grant；
- 同一链路复用稳定 run_id；
- 自动重试最多一次。

不允许：

- 全局关闭 ticket；
- 把空绑定当通配符；
- 用模型自报替代真实 admission；
- 为了省一次检查而复用不同计划下的旧结果。

---

## 5. 修复总览和优先顺序

按以下顺序执行，不能先修改低优先级安装细节而跳过核心绑定：

| 批次 | 工作包 | 主要文件 | 优先级 |
|---|---|---|---|
| 1 | 有效计划合并与 actor 规范化 | control_profile.py、capability.py | P1 |
| 2 | Result、Task、Plan 三方绑定 | control_result.py、task.py | P1 |
| 3 | Ticket 严格绑定和低成本授权 | tickets.py、bridge.py | P1 |
| 4 | canonical bridge 和 scaffold | bridge.py、bridge_scaffold.py | P1 |
| 5 | secret handoff、脱敏和失败关闭 | bridge.py | P1 |
| 6 | 输入摘要和路径规范化 | task.py、worktree.py | P1/P2 |
| 7 | 安装、备份、移除和回滚 | bridge.py、bridge_scaffold.py | P2 |
| 8 | CI 和最终验收命令 | .github/workflows/*、docs | P2 |

每个工作包都必须先加一个能证明当前缺陷的反例测试，再改实现。不要先改实现、再只写正向测试。

---

## 6. 工作包 A：修复 Effective Control Plan

### 6.1 当前问题

当前合并逻辑存在以下风险：

- baseline.source_ref 没有作为完整字段继承和比较；
- repair.recheck_unchanged_input 没有按严格度合并；
- repair.stop_after_pass 没有按严格度合并；
- 某些 scope 组合可以用 current-project 扩大范围；
- actor snapshot 仍可能以未规范化自由字典进入计划；
- raw profile 和 frozen profile 可能有两套调用路径。

### 6.2 正确的实现策略

#### 第一步：各层先独立规范化

对 Base、Task、Run、Actor 的输入分别做：

1. 类型校验；
2. unknown field 拒绝；
3. mode、tolerance、budget、repair、scope、expires_at 规范化；
4. required/excluded 冲突检查；
5. baseline 完整性检查；
6. actor capability 白名单化。

不要用“task 的默认值”覆盖 base 的真实值。配置对象的默认值必须能区分：

- 用户明确设置为 false/空；
- 用户没有设置，应该继承上层。

如果当前数据模型无法区分这两者，应先调整数据模型或引入显式的 unset 表示，再修改合并逻辑。

#### 第二步：required、excluded 和 mode

合并顺序：

~~~text
required = base.required ∪ task.required ∪ run.required
excluded = base.excluded ∪ task.excluded ∪ run.excluded
~~~

如果同一 check 同时出现在 required 和 excluded，直接 ProfileError。

对每个 required check：

1. 没有显式 mode 时物化为 block；
2. 将各层 mode 按一个集中定义的 rank 比较；
3. 选择最严格值；
4. 下层尝试把已有 block 改为 report_only 或 advisory 时拒绝。

不能在 control_profile.py、control_result.py 和 adapter 中各写一套 mode 排序。

#### 第三步：tolerance、budget 和 repair

- tolerance 的每个维度都要继承，不能因为下层未配置就清空；
- budget、max_repairs、max_rounds 取各层最小值；
- 下层设置更大的上限时拒绝，而不是静默截断；
- repair policy 如果不能比较，拒绝；
- recheck_unchanged_input=true 表示更严格，合并用 OR；
- stop_after_pass=true 表示通过后立即结束，合并用 OR；
- 不能只把这些字段写进 digest，却不让判定器产生实际行为。

#### 第四步：baseline

以下字段都必须参与比较和 digest：

~~~text
generation_mode
audit_mode
challenge_without_explicit_request
independence_required
require_accept
require_proven_independence
source_ref
~~~

source_ref 不允许被 task 静默覆盖。Base 和 Task 指向不同事实基线时，必须拒绝，或者执行一个文档明确、测试明确的重新绑定流程。

SOP Control 不判断 baseline 内容是否正确；它只保证调用方声明的 baseline 被稳定引用。

#### 第五步：scope

实现真正的“下层是上层子集”比较：

- current-project 只能作为明确的项目根范围，不能在一个已经收窄到具体 task/phase 的层中重新扩大；
- 相对路径先规范化；
- ..、绝对路径、不同分隔符和大小写变体不能逃逸或扩大范围；
- 任何无法判断包含关系的 scope 直接拒绝。

#### 第六步：actor capability

actor 只表示执行者能力上限，不是新的审计规则来源。建议定义一个明确的 typed snapshot，至少包含：

~~~text
tier
max_repairs
write_granularity
strict_schema
source
evaluation_id
approved
approval_expires_at
~~~

只允许白名单字段进入 effective plan。未批准、过期、不匹配或无法验证的 actor 必须使用保守上限或返回 unknown。

#### 第七步：唯一组合入口

compose_effective_plan 应成为唯一组合点：

~~~text
raw layers
  → normalize each layer
  → merge tighten-only
  → validate complete fields
  → create immutable plan
  → compute layer digests and effective_plan_digest
~~~

evaluate_control_result 如果仍接收 raw base_profile 或 run_override，必须先调用同一个组合入口并重新冻结；不能一部分调用组合、一部分直接评估。

### 6.3 必须添加的反例测试

建议测试名和断言：

~~~text
test_merge_preserves_baseline_source_ref
test_baseline_source_ref_mismatch_is_rejected
test_recheck_unchanged_input_cannot_be_weakened
test_stop_after_pass_cannot_be_weakened
test_current_project_cannot_widen_narrow_scope
test_unknown_actor_fields_are_rejected
test_unapproved_actor_uses_conservative_ceiling
test_all_layers_are_present_in_effective_plan_digest
test_raw_and_frozen_evaluation_have_one_semantics
~~~

每个测试都要检查最终值和 digest，不要只检查对象能否构造。

---

## 7. 工作包 B：修复 Task、ControlResult 和 Plan 绑定

### 7.1 当前问题

目前组合计划的层结构类似：

~~~python
layers = {
    "base": {...},
    "task": {"digest": task_digest, ...},
    "run": {...},
    "actor": {...},
}
~~~

但判定器读取了 layers["task_digest"] 这一不存在的顶层字段，可能回退到整体计划 digest，导致真实绑定任务得到 unknown。

### 7.2 修复要求

1. 统一层结构。推荐使用 layers["task"]["digest"]，并在一个 typed accessor 中读取。
2. 不要在多个地方直接拼接字符串读取层字段。
3. 如果为了兼容旧数据保留 task_digest，必须有 schema version，并明确旧数据不能用于新的 enforce 判定；不能用静默 fallback。
4. Task Contract、ControlResult 和 Frozen Plan 必须使用同一个 task digest。
5. 结果的 effective_plan_digest 必须等于冻结计划的 digest。
6. check_task_profile_gate 必须检查存储的 effective plan digest，而不能只检查 base/profile digest。
7. 当 actor snapshot 变化时，旧 plan digest 和旧 ticket 必须失效。

### 7.3 幂等键

idempotency_key 至少显式包含：

~~~text
schema_version
task_id
phase
operation_id 或 run_id（如果该动作需要）
input_digest
baseline_digest
effective_plan_digest
check_id
~~~

check_id 不能为空。不能把 task、phase、run 拼到一个无法解释的字符串里，也不能使用以下兼容逻辑：

~~~text
effective_plan_digest 为空 → 使用 base_digest
ticket plan 为空 → 当成任意 plan
~~~

### 7.4 时间判定

Profile 规范化和 Result 判定必须使用同一个时间解析语义：

- 无时区时间拒绝；
- 非法时间拒绝；
- expires_at 存在而 now 缺失，不能 pass；
- 先转换为 aware UTC，再比较；
- now >= expires_at 按项目定义稳定处理为过期；
- 一次判定只读取一个 now，不要在不同分支重复读取系统时间。

不要让 control_result.py 单独把 naive 时间强行当 UTC，而 control_profile.py 又拒绝它。

### 7.5 stop_when 和 rounds

明确计数：

- round0 表示首次检查尚未消耗修复轮数；
- 每次修复完成后才递增 rounds_used；
- 达到上限时不能再调用修复；
- clean pass 与 blocking finding 的边界要分别测试；
- stop_after_pass=true 时首次通过后立即结束，不再追加审计或修复；
- 所有返回值都携带 next_action，不能只返回模糊的 illegal transition。

### 7.6 必须添加的反例测试

~~~text
test_bound_task_composed_plan_passes_with_nested_task_digest
test_bound_task_wrong_plan_returns_unknown
test_stored_effective_plan_digest_is_required
test_result_task_phase_operation_binding_is_exact
test_empty_check_id_is_rejected
test_idempotency_keys_differ_across_task_phase_run
test_effective_plan_digest_never_falls_back_to_base_digest
test_missing_now_with_expiry_never_passes
test_naive_expiry_is_rejected
test_stop_after_pass_stops_without_second_call
test_max_rounds_has_no_extra_repair_call
~~~

---

## 8. 工作包 C：收紧 Capability Ticket

### 8.1 当前问题

当前风险不是“有没有 ticket”，而是“ticket 是否绑定了正确的上下文”。以下情况不能被接受：

- expected plan 存在，但 ticket plan 为空时仍通过；
- expected phase 存在，但 ticket phase 为空时仍通过；
- expected task 存在，但 ticket task 为空时被当作通配；
- bridge 计算出了 operation，却没有让 ticket 本身绑定 operation；
- adapter 校验只检查 action/fingerprint，没有检查完整预期绑定。

### 8.2 正确的校验接口

建议让所有真实 admission 都走同一个严格校验函数，显式接收：

~~~text
expected_project_id
expected_task_id
expected_phase
expected_action
expected_operation_id
expected_run_id
expected_plan_digest
expected_capability_binding
expected_input_fingerprint
expected_side_effect
~~~

规则：

1. expected 字段非空时，ticket 对应字段必须非空且完全相等；
2. ticket 字段为空不能作为通配；
3. allowed_actions 必须包含本次 action；
4. ticket 已消费、过期或签名/secret 不匹配，直接拒绝；
5. verify_ticket_for_admission 与 redeem_ticket 不要各自维护不同的绑定语义；
6. redeem_ticket 成功只能发生一次；
7. phase-level grant 必须显式列出允许动作，不能成为跨 phase 全局票据。

### 8.3 challenge 和 redeem

challenge 时使用的 payload 必须包含并固定：

~~~text
integration_id
action
canonical business argv
side_effect
task_id
phase
operation_id/run_id
effective_plan_digest
capability_binding
input_fingerprint
~~~

admit 时必须由同一份 canonical payload 重新计算 expected 值，再逐字段比较。

不能让模型手工复制 ticket secret。优先通过 wrap 或 bridge 内部完成：

~~~text
challenge → handoff → child admission → execute
~~~

### 8.4 降低 ticket 开销

目标是减少额外调用，不是删除保护：

- 只读动作不申请 ticket；
- 同一 task/phase/plan/operation 可以使用限定动作集合的短期 grant；
- 同一链路复用稳定 operation_id/run_id；
- 自动重试最多一次；
- 第二次失败后返回结构化产品缺口；
- 禁止使用 TICKETS=off 或同等全局开关作为生产修复。

### 8.5 必须添加的反例测试

~~~text
test_expected_plan_rejects_empty_ticket_plan
test_expected_phase_rejects_empty_ticket_phase
test_expected_task_rejects_empty_ticket_task
test_operation_id_is_bound_in_ticket
test_allowed_actions_are_enforced
test_ticket_cannot_cross_phase
test_consumed_ticket_cannot_be_replayed
test_run_id_change_is_rejected
test_plan_digest_change_is_rejected
test_readonly_action_has_no_ticket_roundtrip
test_challenge_failure_does_not_issue_unbounded_tickets
~~~

---

## 9. 工作包 D：修复 canonical bridge 和 scaffold

### 9.1 当前问题

当前 canonical_payload 先把 argv 用空格拼成字符串，再交给 shell 风格分类器：

~~~python
command = " ".join(str(item) for item in argv)
~~~

这会丢失 token 边界，使不同业务参数获得同一个 fingerprint。与此同时，Python scaffold 使用 JSON 布尔值生成 Python 源码，可能生成 true/false，导致运行时 NameError。

### 9.2 canonical payload 的实现要求

Canonical payload 必须是结构化对象，至少包含：

~~~json
{
  "schema": "canonical-invocation-v1",
  "integration_id": "...",
  "action": "...",
  "argv": ["token-1", "token-2"],
  "surface": "...",
  "operation": "...",
  "target": "...",
  "side_effect": "...",
  "task_id": "...",
  "phase": "...",
  "operation_id": "...",
  "run_id": "...",
  "effective_plan_digest": "...",
  "capability_binding": "..."
}
~~~

要求：

1. argv 保持 list token，不得先 join 后重新解析；
2. digest 使用稳定 JSON 编码、稳定字段顺序和固定 schema；
3. wrapper 路径、$0、解释器路径、handoff 路径、时间和 secret 不进入业务 fingerprint；
4. display command 可以另行生成，但不能参与身份 digest；
5. operation_id 和稳定 run_id 从同一 canonical payload 派生；
6. challenge、admit、execute 都使用同一 canonical builder；
7. 参数任意变化都必须造成 fingerprint mismatch。

### 9.3 启动方式矩阵

必须分别覆盖并断言以下启动方式：

1. 直接执行 wrapper；
2. python scaffold.py args...；
3. sh scaffold.sh args...；
4. node scaffold.js args...；
5. bridge run 再调用 scaffold；
6. 无参数、多个参数、带空格参数；
7. 引号、美元符号、反斜杠、Unicode、换行；
8. 修改任意一个业务参数后旧 ticket 必须失败。

如果一种启动方式无法安全还原业务 argv，必须在安装自检或运行时明确拒绝，不要猜测 $0 或 wrapper 路径继续放行。

### 9.4 scaffold 生成要求

不同语言的源码字面量必须使用对应语言语法：

- Python 使用 True / False，或使用 Python 的 repr(bool_value)；
- JavaScript 使用 true / false；
- shell 使用安全的单引号/转义策略；
- 用户参数不得重新进入 shell 解析。

最稳妥的方式是让生成的 scaffold 只负责收集 argv 并调用共享 bridge 入口，而不是在每种语言中复制一套 admission 逻辑。

### 9.5 必须添加的反例测试

~~~text
test_argv_token_boundaries_change_fingerprint
test_argv_special_characters_are_not_reparsed
test_direct_wrapper_matches_bridge_fingerprint
test_python_interpreter_matches_direct_wrapper
test_shell_wrapper_matches_direct_wrapper
test_node_wrapper_matches_direct_wrapper
test_nested_bridge_uses_business_argv
test_python_scaffold_executes_with_side_effect
test_python_scaffold_executes_readonly
test_parameter_mutation_rejects_old_ticket
test_operation_and_run_are_stable_across_retry
~~~

---

## 10. 工作包 E：修复 secret handoff、脱敏和失败关闭

### 10.1 三个生命周期必须分开

不要把下面三件事混成一个“兑换成功就删除”的动作：

1. ticket 兑换生命周期；
2. 父进程持有 secret 以便脱敏的生命周期；
3. handoff 文件存在于磁盘的生命周期。

### 10.2 正确执行顺序

~~~text
challenge
  ↓
写入 0600 handoff
  ↓
父进程读取 secret 到本次 scrub 上下文
  ↓ 读取失败则立即 fail-closed，不启动子进程
启动子进程
  ↓
子进程在真实入口 admission/redeem
  ↓
执行并捕获 stdout/stderr/异常
  ↓
统一 scrub 所有用户可见文本和 receipt
  ↓
生成 receipt
  ↓
删除 handoff
~~~

如果成功兑换路径提前删除 handoff，必须证明父进程已经读取 secret，并有测试证明输出仍能脱敏。更安全的默认是由最外层执行器负责清理。

### 10.3 失败路径

以下任何失败都不能继续执行并返回“看起来成功”的结果：

- handoff 文件不存在；
- handoff 无法读取；
- JSON 损坏；
- secret 缺失；
- operation 或 plan 不匹配；
- 子进程启动失败；
- 超时；
- admission 结果无法解析。

run_bridge 不能在读取 handoff 异常时简单 pass。读取失败意味着无法建立可靠的脱敏上下文，应结构化返回错误并清理短期文件。

### 10.4 脱敏要求

secret 不得出现在：

- argv；
- 普通环境变量值；
- stdout；
- stderr；
- receipt；
- 异常对象的 str/repr；
- task 摘要；
- git diff；
- 模型上下文。

脱敏至少要覆盖：

- 完整 secret；
- JSON 转义形式；
- URL 编码形式；
- shell 转义形式；
- 任意位置出现的连续 secret 片段，而不是只检查几个固定 offset。

对于短片段无法可靠区分普通文本和 secret 的情况，必须明确产品策略：

- 要么使用全量输出不回显策略；
- 要么使用最小片段阈值并在文档中声明边界；
- 要么采用按 secret 生成所有连续子串的有限 scrub 集合。

不能声称“任何 partial secret 都安全”，但实现只替换固定的几个片段。

### 10.5 必须添加的反例测试

~~~text
test_handoff_read_error_blocks_before_child_start
test_child_printing_full_secret_is_scrubbed
test_child_printing_arbitrary_secret_fragment_is_scrubbed
test_json_escaped_secret_is_scrubbed
test_url_encoded_secret_is_scrubbed
test_secret_never_enters_receipt
test_secret_never_enters_error_text
test_success_handoff_is_removed_after_scrub
test_failure_handoff_is_cleaned
test_subprocess_start_failure_returns_structured_receipt
test_timeout_output_is_scrubbed
~~~

测试不能只写 count("***") >= 2；必须断言实际 secret 和规定长度以上的片段不在最终 stdout、stderr、receipt 和错误文本中。

---

## 11. 工作包 F：修复输入摘要和路径规范化

### 11.1 路径规则

submit_input_digest_for 对每个输入路径必须先：

1. 拒绝 NUL；
2. 拒绝绝对路径；
3. 拒绝包含 .. 的路径；
4. 规范化分隔符；
5. 规范化相对路径；
6. 检查路径仍位于允许 root 内；
7. 对规范化后重复的路径去重或拒绝，不能产生两套身份。

不要只调用 resolves_inside 就认为路径已经规范化。x/../a 可能仍被解析到 root 内，但它不是稳定的规范输入。

### 11.2 目录摘要

对每个输入路径：

- 普通文件：记录规范相对路径、类型、字节长度、完整内容 hash；
- 目录：递归枚举全部条目，按 POSIX 相对路径排序；
- 空目录：使用独立稳定标记；
- 不存在路径：和空目录区分；
- 符号链接：默认拒绝；若产品明确允许，必须记录规范目标、防循环并阻止逃逸；
- 设备文件、socket、FIFO 等特殊文件：默认拒绝；
- 无法读取的目录或文件：拒绝，不能只追加一个 unreadable 标记后继续；
- 大文件：分块读取；
- 不使用 mtime、inode、绝对路径或权限作为内容等价性的主要依据；
- 推荐使用完整 SHA-256，不要只截取过短的摘要。

“标记后继续”不能作为 enforce 模式下的成功输入证明。若某类文件需要兼容，必须让 profile 显式声明策略，并在结果中保持 unknown/block 语义。

### 11.3 必须添加的反例测试

~~~text
test_absolute_input_path_is_rejected
test_parent_segment_is_rejected
test_duplicate_normalized_paths_are_not_ambiguous
test_directory_file_content_changes_digest
test_directory_add_delete_rename_changes_digest
test_directory_order_does_not_change_digest
test_empty_directory_differs_from_missing_path
test_symlink_escape_is_rejected
test_symlink_loop_is_rejected
test_special_file_is_rejected
test_unreadable_input_fails_closed
test_large_file_is_stream_hashed
test_same_size_content_change_changes_digest
~~~

---

## 12. 工作包 G：修复安装、备份、移除和回滚

### 12.1 安装要求

安装目标前必须使用 lstat 或等价方式区分：

- 不存在；
- 普通文件；
- 符号链接；
- 目录；
- 特殊文件。

要求：

1. 符号链接和特殊文件默认拒绝覆盖；
2. 已有普通文件必须先备份；
3. 备份只能写到受控 rollback 目录；
4. 备份失败时目标不能改变；
5. 写入使用同目录临时文件加原子替换；
6. 尽量保留原 mode；
7. 重复安装不能无限叠加备份；
8. 生成 wrapper 使用与 bridge 完全相同的 canonical 语义。

### 12.2 移除要求

remove_wrapper 或 detach 只能删除 SOP Control 自己安装且能被可信 manifest 证明的内容：

- 不能信任用户可任意修改的路径字段；
- 不能对任意路径直接 unlink；
- 没有安装痕迹时无副作用返回；
- 只删除自己的 hook/plugin；
- 保留第三方 hook；
- 恢复原文件内容和 mode；
- manifest 或 rollback 清单被篡改时拒绝恢复。

### 12.3 必须添加的反例测试

~~~text
test_install_new_target_and_remove
test_install_existing_file_backups_once
test_install_preserves_original_mode
test_install_rejects_symlink_target
test_install_rejects_special_target
test_backup_failure_leaves_target_unchanged
test_install_is_atomic_on_write_failure
test_repeated_install_restores_original_file
test_remove_does_not_delete_unowned_file
test_tampered_manifest_path_is_rejected
test_remove_preserves_third_party_hooks
test_absent_harness_is_not_created_implicitly
~~~

---

## 13. 工作包 H：统一 CI 和文档验收

### 13.1 覆盖率命令

当前不能只依赖本地手工命令。github workflow 中的 ci.yml 和 gate.yml 必须使用同等覆盖率要求。

推荐统一为：

~~~bash
.venv/bin/pytest -q

COVERAGE_FILE=/tmp/sopcontrol-coverage-final \
  .venv/bin/pytest -q --cov --cov-branch --cov-report=term-missing
~~~

覆盖率阈值至少保持项目现有的 85.0%。不要以 skipped 代替关键行为测试，不要只报告定向测试。

### 13.2 静态验收

~~~bash
.venv/bin/ruff check sopcontrol plugins tests
git diff --check
~~~

如果要检查已经提交但尚未推送的内容，不能只运行没有差异的 git diff --check；还要针对基线到当前 HEAD 检查：

~~~bash
git diff --check BASE_COMMIT..HEAD
~~~

文档文件末尾不能包含多余空白行。

### 13.3 SOP Control 自身验收

~~~bash
.venv/bin/python -m sopcontrol.cli gate .
.venv/bin/python -m sopcontrol.cli project check
.venv/bin/python -m sopcontrol.cli chronicle check
~~~

如果 sopctl 已正确安装，也可以使用：

~~~bash
sopctl gate .
sopctl project check
sopctl chronicle check
~~~

不能用关闭 hook、删除 .sopcontrol、修改 enforce 默认值或 ticket-off 来掩盖失败。

### 13.4 定向危险模式扫描

~~~bash
rg -n "effective_plan_digest.*base_digest|base_digest.*effective_plan_digest" sopcontrol tests
rg -n "task_digest.*frozen|layers.*task" sopcontrol tests
rg -n "json\.dumps\(bool|join\(str\(item\).*argv" sopcontrol tests
rg -n "except .*pass|handoff.*unlink|verify_ticket_for_admission" sopcontrol tests
~~~

每个命中项都要说明它是：

- 已修复的生产实现；
- 合法的兼容迁移；
- 明确的负向测试；
- 仍然存在的阻断。

不能只把搜索结果粘到交付报告里。

---

## 14. 推荐的实际执行顺序

### 阶段 0：建立基线

~~~bash
git status --short --branch
git log -1 --oneline
.venv/bin/pytest -q
~~~

记录：测试总数、失败数、覆盖率、当前工作区改动。已有 .sopcontrol/evidence/ 改动不要擅自删除。

### 阶段 1：先写 P1 反例

先添加本手册第 6–10 节列出的最小反例。反例必须：

- 使用真实公开 API；
- 不通过 monkeypatch 绕开 admission；
- 不伪造 verified 状态；
- 能在修复前稳定失败；
- 能在修复后证明正确拒绝或正确通过。

### 阶段 2：修复有效计划

完成第 6 节后，只运行相关测试，确认：

- source_ref 不丢失；
- repair 布尔字段真正合并；
- scope 不扩大；
- actor 只能收紧；
- 只有一个 compose/freeze 入口。

### 阶段 3：修复结果和任务绑定

完成第 7 节后，确认一个真实 bound task 在合法 plan/result 下可以通过，而错误 plan、旧 plan、错误 actor、错误 phase 都不能通过。

### 阶段 4：修复 ticket

完成第 8 节后，确认：

- 空绑定不再通配；
- phase 和 operation 被绑定；
- 重放失败；
- 只读动作没有不必要的 ticket 往返；
- 自动挑战不会无限签发新 ticket。

### 阶段 5：修复 bridge 和 secret

完成第 9–10 节后，必须实际执行 Python、shell、Node 和 nested bridge 形式。只检查生成文件文本不算完成。

### 阶段 6：修复输入和安装

完成第 11–12 节后，跑文件系统负向测试和失败回滚测试。不要为了让旧测试继续通过而保留 marker 后 pass 的行为。

### 阶段 7：统一 CI

完成第 13 节后，更新两个 workflow 的覆盖率命令，清理文档末尾空白，并重新执行完整验收。

### 阶段 8：最终验收

完整执行第 16 节，不要只执行定向测试。

---

## 15. 最终验收矩阵

| 领域 | 必须成立 | 失败时的结果 |
|---|---|---|
| 有效计划 | 四层合成完整、稳定、只能收紧 | ProfileError 或 unknown |
| baseline | 全字段一致，含 source_ref | 拒绝编译 |
| actor | 只有规范化能力上限进入 digest | 保守上限或 unknown |
| Task/Result | task、phase、input、plan、actor 精确一致 | unknown/拒绝 |
| idempotency | task、phase、run/operation、check 都纳入 | 不同身份不得复用 |
| Ticket | 空绑定不通配，允许动作和阶段严格匹配 | admission 拒绝 |
| canonical | 所有启动形式同一业务 argv | 不支持则明确拒绝 |
| 参数 | token 边界保留，参数改变指纹改变 | 旧 ticket 失败 |
| scaffold | Python/shell/Node 实际可执行 | 结构化失败 |
| secret | 完整、编码和规定片段均不出现在输出 | fail-closed + scrub |
| 输入 | 目录内容、路径和特殊文件安全处理 | 明确失败 |
| 安装 | 原子写入、可信备份、只恢复自己的内容 | 目标不变或安全回滚 |
| rounds | 达到边界没有额外 repair | 终止并说明原因 |
| stop_after_pass | 通过后不重复调用 | 立即终止 |
| CI | 本地和 workflow 都含 branch coverage | 不能报告完成 |

---

## 16. 必须执行的最终命令

在没有所有反例测试之前，不要使用“最终完成”措辞。完成前执行：

~~~bash
cd /Users/xiezhijie/sopcontrol

.venv/bin/pytest -q

COVERAGE_FILE=/tmp/sopcontrol-coverage-final \
  .venv/bin/pytest -q --cov --cov-branch --cov-report=term-missing

.venv/bin/ruff check sopcontrol plugins tests

git diff --check

.venv/bin/python -m sopcontrol.cli gate .
.venv/bin/python -m sopcontrol.cli project check
.venv/bin/python -m sopcontrol.cli chronicle check

git status --short --branch
git log -1 --oneline
~~~

还要执行：

~~~bash
rg -n "effective_plan_digest.*base_digest|base_digest.*effective_plan_digest" sopcontrol tests
rg -n "json\.dumps\(bool|join\(str\(item\).*argv" sopcontrol tests
~~~

危险模式的每一个命中都必须人工确认，不能因为搜索命中位于测试文件就自动忽略。

---

## 17. 不能接受的“伪完成”方式

以下结果都不算完成：

1. 只报告 pytest 通过，不跑新增反例；
2. 只跑覆盖率而不带 --cov-branch；
3. 只检查 scaffold 文件存在，不实际执行 Python/shell/Node；
4. 发现 task 绑定返回 unknown 后，把绑定检查删掉；
5. 发现 ticket 卡住后打开全局 ticket-off；
6. 发现 secret scrub 漏片段后只增加几个固定 offset；
7. 发现目录特殊文件处理失败后继续写 nonfile 标记并返回 pass；
8. 用 base digest 代替 effective plan digest；
9. 用空 ticket 字段表示任意 task/phase/plan；
10. 把业务参数拼成 shell 字符串再解析；
11. 修改测试断言以适应错误实现；
12. 直接改 .sopcontrol/ 账本、任务、投影或证据文件；
13. 为了“清理工作区”删除接手前已有的证据或用户改动；
14. 把业务语义审计内容硬编码进 SOP Control；
15. 没有证据时把 gap、unknown 或 not_run 报成 pass。

---

## 18. 外部模型交付报告模板

外部模型完成后必须按下面格式交付，不要只说“已修复”：

~~~text
# SOP Control 最终闭环修复报告

## A. 结论
- 状态：完成 / 未完成 / 阻断
- 是否满足本手册全部验收条件：是 / 否
- 若否，列出每个阻断和复现命令

## B. 代码修改
- 文件：
- 修改点：
- 是否修改 JobsFlow/JobsDB：否（若是，说明原因）
- 是否修改 .sopcontrol：只能通过 sopctl 产生的证据写入；不得直接编辑

## C. 有效计划证据
- 四层合成：
- source_ref：
- repair/stop_when：
- actor snapshot：
- effective_plan_digest 一致性：

## D. Task/Result/Ticket 证据
- task_id、phase、input、plan、operation/run 绑定：
- 空绑定负向测试：
- 重放和跨阶段测试：

## E. Bridge 和 secret 证据
- 直接 wrapper：
- Python：
- shell：
- Node：
- nested bridge：
- 参数 token 边界：
- secret 完整/编码/片段脱敏：
- handoff 清理顺序：

## F. 输入和安装证据
- 路径规范化：
- 目录内容摘要：
- symlink/special/unreadable：
- 原子安装和回滚：
- 第三方 hook 保留：

## G. 测试命令和结果
- pytest：
- branch coverage：
- ruff：
- diff check：
- gate：
- project check：
- chronicle check：

## H. 剩余风险
- 只列真实存在的限制；不要把未验证内容写成 verified。

## I. Git 状态
- HEAD：
- 远端：
- 是否 push：
~~~

### 18.1 完成措辞的严格要求

只有下列条件全部满足，才能写“完成”：

- 所有 P1 反例通过；
- 全量测试和 branch coverage 通过；
- bound task 的真实组合路径可以合法通过；
- Python/shell/Node/nested bridge 都有实际执行证据；
- secret 负向测试没有泄露；
- CI workflow 与本地命令一致；
- gate、project check、chronicle check 通过；
- 没有用关闭 enforce、删除 hook、ticket-off 或修改业务语义来规避问题。

如果任何一项未满足，必须写“未完成”或“有条件完成”，并列出阻断，不得用“整体质量已达到 8.5”替代证据。

---

## 19. 给执行模型的最后指令

你不需要重新设计 SOP Control，也不需要扩大产品范围。请把它当作一次严格的闭环修复：

1. 先读项目文件和现有实现；
2. 先用反例证明问题；
3. 只在对应模块修复；
4. 让所有对象共享同一个有效计划和 digest；
5. 让所有受控入口共享同一个 canonical payload；
6. 让未知、缺失、过期、无法读取和无法证明的情况 fail-closed；
7. 用有限授权和稳定 run_id 降低开销，而不是取消保护；
8. 不替 JobsFlow 定义业务语义；
9. 不直接改 .sopcontrol/；
10. 不在证据不足时宣布完成。

最终要证明的不是“模型愿意遵守 SOP”，而是：即使换模型、换 session、换启动方式、改变参数、改变输入、改变 actor 或重放旧 ticket，SOP Control 仍然只允许当前有效计划明确允许的动作继续执行。
