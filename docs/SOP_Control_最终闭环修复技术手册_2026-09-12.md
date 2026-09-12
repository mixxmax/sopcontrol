# SOP Control 最终闭环修复技术手册

## ——动态规则、准入控制与兼容桥接的最终收口

| 项目 | 内容 |
|---|---|
| 目标仓库 | sopcontrol |
| 文档日期 | 2026-09-12 |
| 交付对象 | 外部模型、接手开发者、最终验收者 |
| 当前基线 | 7accbe5d05bbc4716bd5f7eb5c3ffa994b1c95cb7 |
| 当前定位 | 只收口 SOP Control 的控制能力，不接管业务系统的语义判断 |
| 完成标准 | 所有本文的负向用例、集成测试、gate 和发布检查均通过 |

> 这不是设计讨论稿，而是一份可以直接交给外部模型执行的最终实施手册。外部模型不得以“已有测试通过”“已有票据”“已有规则定义”代替本文的闭环验收。必须把每一个边界条件落实成代码、测试和可观察的失败结果。

---

## 1. 先明确：这次到底要解决什么

SOP Control 的产品职责是：

1. 确保系统按照已经声明的 SOP、任务契约和运行时规则运行。
2. 确保必需步骤被执行、禁止步骤不能执行、失败状态不能被伪装成成功。
3. 确保动态规则在不同任务、不同运行、不同模型能力下被正确合成，并且所有判定都绑定到同一份有效计划。
4. 确保外部系统通过受控入口执行，而不是因为适配器、脚本包装器或临时文件的差异而失去控制。
5. 在不必要的地方减少重复调用、重复审计和重复票据兑换，优先节省时间、token 和系统能耗。

SOP Control 不负责：

1. 判断 JobsFlow、JobsDB 或其他业务系统的材料内容是否符合业务目标。
2. 自行发明“独立审计”的风格、检查对象、容忍度、修正策略或审计轮数。
3. 替业务系统决定 reviewing、drafting 等业务术语哪个更好。
4. 默认启动第二个模型、子 agent 或人工审批。
5. 接管业务系统内部的产物格式、语义 lint 或内容生成逻辑。

如果业务系统声明“必须检查是否贴合 JD”“必须基于事实基线”“允许合理范围内的夸大”“只修正指定问题”“通过后不重复审计”，SOP Control 的职责是把这些声明当作受控规则输入，并确保系统确实经过了这些检查；SOP Control 不应自己重新定义这些检查。

这条边界必须写进实现与测试。任何把“控制流程”扩展成“代替业务系统判断内容”的修复，均属于范围漂移，应撤回。

---

## 2. 为什么之前总是“改了一部分但仍然不到位”

目前的问题不是单个 if 判断漏写，而是多个入口各自做了半套控制：

1. 动态规则可以被读取，但没有始终合成完整的有效控制计划。
2. 规则合成的大部分字段是收紧的，但某些隐含默认值、时间字段和布尔字段仍可能被较弱的层覆盖。
3. 判定器、任务绑定、票据签发和票据兑换不一定引用同一份计划摘要。
4. 桥接器能挑战和兑换票据，但不同启动方式可能构造出不同的指纹。
5. 票据秘密的生命周期与输出脱敏生命周期不一致，可能在父进程还没完成脱敏前就被删除。
6. 输入摘要对单文件有效，对目录只记录目录存在而不记录目录内容，导致输入没有真正被绑定。
7. 最大修复轮数的边界使用了“超过”而不是“达到”，会在最后一轮之后多发起一次修复。
8. 现有测试主要证明正常路径能通过，尚未充分证明“不可通过”的路径真的被阻断。

因此，本手册不接受只改一处调用、只加一个参数、只让当前测试通过的修复。最终实现必须形成下面的闭环：

    动态规则输入
      → 规范化
      → 单一有效计划
      → 有效计划摘要
      → 输入/基线/检查绑定
      → 受控入口执行
      → 判定
      → 修复或终止
      → 结果、票据、receipt 使用同一摘要

---

## 3. 当前基线与必须关闭的问题清单

以下问题是接手时的重点。行号可能随修改变化，外部模型应按符号和调用链定位，而不是机械依赖行号。

| 编号 | 优先级 | 问题 | 典型落点 | 完成判据 |
|---|---:|---|---|---|
| DR-01 | P1 | Base、Task、Run、Actor Capability 没有稳定地形成一份完整有效计划 | control_profile.py、control_result.py、capability.py | 所有入口只使用同一份 effective plan 及其 digest |
| DR-02 | P1 | 必需维度没有显式 mode 时的隐含 block 可能被 task profile 弱化 | control_profile.py 的合并逻辑 | base required 等价于 block，弱化必须拒绝 |
| DR-03 | P1 | expires_at 无效、now 缺失或时区不同可能放行 | control_result.py、control_profile.py | 无法证明时间有效时只能 unknown 或 block，不能 pass |
| DR-04 | P1 | max_rounds 恰好达到上限时仍可能继续请求修复 | control_result.py | 达到上限立即终止，不产生下一次修复动作 |
| DR-05 | P1 | 目录输入只写入 nonfile 标记，没有绑定实际内容 | task.py | 目录内内容变化必然改变 input digest |
| BR-01 | P1 | 不同 wrapper 启动方式生成不同 canonical invocation | bridge.py、bridge_scaffold.py | challenge、admit、execute 使用完全相同的规范载荷 |
| BR-02 | P1 | admit_ticket 提前删除 handoff，父进程随后无法可靠脱敏 | bridge.py | 子进程输出中的 secret 必须先脱敏，再清理 handoff |
| BR-03 | P1 | 期待 plan/phase 时，未绑定字段的 ticket 仍可能被接受 | tickets.py | 期待绑定存在时，ticket 缺失绑定必须拒绝 |
| DR-06 | P2 | repair、baseline、stop_when 的部分字段没有完整合并或绑定 | control_profile.py、control_result.py | 全字段都有明确的单调合并语义和回归测试 |
| BR-04 | P2 | scaffold 覆盖已有文件、恢复、权限和清单信任边界需要持续回归 | bridge_scaffold.py、bridge.py | 安装、重复安装、移除、恢复和失败回滚都可验证 |
| OPS-01 | P2 | CI 分支覆盖率命令与本地命令不一致，容易出现“本地绿、CI 红” | .github/workflows/ci.yml、pyproject.toml | CI 明确使用 branch coverage 并稳定通过 |
| OPS-02 | P2 | 生成投影、chronicle、gate 和测试结果没有作为同一交付物验收 | 项目治理命令 | 发布前所有一致性检查通过 |

其中 DR-01 至 DR-05、BR-01 至 BR-03 是本手册的主要阻断项。任何一个未关闭，都不能对外宣称“动态规则已经彻底闭环”。

---

## 4. 不可妥协的系统不变量

外部模型开始改代码前，必须把下面的不变量逐条转化为测试。测试名称可以不同，但测试语义不能缺失。

### 4.1 有效计划不变量

有效计划必须由以下四类输入合成：

    Base Rule Set
      + Task Profile
      + Run Override
      + Actor Capability
      = Effective Control Plan

要求：

1. 四类输入都必须有明确的来源、规范化结果和摘要。
2. 输入缺失时必须按字段定义处理；不能用空字典、旧 digest 或默认宽松值静默补齐。
3. 同一任务、同一运行、同一检查的判定、receipt、ticket 和审计结果必须引用同一个 effective_plan_digest。
4. actor capability 不是新的规则权威，只是当前执行者能力上限的约束投影。它只能收紧任务允许的修复次数、写入粒度、schema 严格度等既有控制项。
5. 如果 actor capability 未获批准、过期或无法验证，必须得到保守结果，不能当成 unrestricted。

### 4.2 只能收紧，不能放宽

规则层的组合必须是单调的：

1. Task 不能放宽 Base。
2. Run Override 不能放宽 Task 或 Base。
3. Actor Capability 不能放宽前面三层。
4. 未知字段、非法枚举、冲突范围、非法时间都不能默认为最宽松配置。
5. 如果两个层的语义无法比较，拒绝组合并给出具体冲突字段，而不是猜一个结果。

需要特别注意“没有显式写出”的默认值。若某一层把维度放入 required，而没有写 mode，则现有语义是该维度默认使用 block。这个隐含的 block 也属于该层的约束，不能因为 modes 字典里没有对应键就被下一层设成 report_only 或 advisory。

### 4.3 失败关闭

以下情况都不能得到 pass：

1. expires_at 格式非法。
2. expires_at 是无时区时间，而系统无法确定其时区。
3. 配置包含过期时间，但判定时没有可信的 now_iso。
4. 票据的任务、阶段、动作、运行、计划摘要不匹配。
5. required check 没有运行。
6. excluded check 被运行。
7. 输入、基线或有效计划摘要不匹配。
8. 发现 blocking finding 但修复预算已耗尽。
9. 规范载荷在 challenge 和 admit 之间发生变化。
10. 输出脱敏失败或无法确定是否已经脱敏。

“unknown”与“block”可以按现有公开 API 的语义区分：无法证明状态时使用 unknown，已经证明违反约束时使用 block；两者都不得继续当作成功执行。

### 4.4 受控入口不变量

只要一个动作会产生外部副作用、修改业务产物、访问受保护资源或触发不可逆操作，就必须从受控入口进入。只读动作可以按现有策略免票，但不能因此跳过必需的控制检查。

受控入口必须满足：

1. challenge 的规范 payload 与真正 admit 的规范 payload 完全相同。
2. operation_id、run_id、task_id、phase、action 和 effective_plan_digest 在重试时保持不变。
3. ticket secret 只能通过受保护的 handoff 文件或 file descriptor 传递，不放入命令行、普通日志、receipt 或模型上下文。
4. 失败不能通过反复重试自动获得新票据来绕过原始约束。
5. 只允许一次有限重试；payload 变化时必须明确报告 mismatch。

### 4.5 终止不变量

1. 通过后，如果输入、规则、基线和证据没有变化，则不重复审计。
2. 容忍项和 advisory 项不应自动升级为 blocking 项。
3. blocking finding 只允许执行声明的修复策略。
4. 修复轮数达到上限时立即停止，不能因为使用了大于比较而多发起一轮。
5. stop_after_pass 等终止规则必须在判定器中真正产生行为，而不能只出现在配置和 receipt 里。

---

## 5. 实施总原则：先统一模型，再修入口

不要从 bridge.py 的一个分支或 control_result.py 的一个 if 开始零散修补。建议按以下顺序实施：

1. 先补有效计划的数据结构、规范化和 digest。
2. 再补单调合并和 fail-closed 时间语义。
3. 再让 task、result、ticket 全部引用有效计划。
4. 再修输入 digest 与幂等键。
5. 最后修 bridge 的规范载荷、secret 生命周期和 scaffold 回滚。
6. 每个工作包先写负向测试，再改实现。
7. 每个工作包完成后运行定向测试；全部完成后再运行完整测试与 gate。

禁止的做法：

1. 只把测试断言改成当前实现的结果。
2. 在一个入口加参数、在另一个入口继续使用旧默认值。
3. 用 base_digest 作为 effective_plan_digest 的兼容 fallback。
4. 用环境变量全局关闭 ticket 或检查来“让流程先跑起来”。
5. 让模型或调用者手工复制 secret。
6. 通过增加第二个模型或无界重复审计来掩盖控制面本身的不一致。
7. 直接修改 .sopcontrol/ 内的规则、账本、投影或证据文件。

---

## 6. 工作包 A：收口 Effective Control Plan

### 6.1 目标

所有动态规则都必须先合成为一个不可变、可序列化、可摘要的有效计划。判定器不能在运行过程中分别读取 base、task、run override 的原始字典再自行解释。

### 6.2 建议落点

重点检查：

1. control_profile.py 的 ControlProfile、normalize_profile、compile_effective_profile、compose_effective_plan。
2. control_result.py 的 evaluate_control_result、decide_control_result。
3. capability.py 的 ModelProfile、ControlKnobs、effective_control_knobs、apply_knobs_to_open。
4. task.py 中打开任务、冻结契约、提交结果和验证结果的绑定字段。
5. tickets.py 中 ticket 的 plan 和 phase 绑定字段。

### 6.3 有效计划必须包含的字段

至少包含以下规范化字段：

1. profile_id、revision、scope。
2. required checks。
3. excluded checks。
4. 每个 check 的最终 mode。
5. baseline 的全部字段，包括 source_ref。
6. tolerance 的每个维度。
7. repair 的全部字段，包括 policy、max_rounds、recheck_unchanged_input、stop_after_pass。
8. budget 的全部字段。
9. stop_when。
10. expires_at 的规范化绝对时间。
11. task profile 的 id、revision、digest。
12. base profile 的 id、revision、digest。
13. run override 的规范化快照和 digest。
14. actor capability 的规范化快照和 digest。
15. plan schema version。

不要只把最终结果放进 digest；还要把各层来源放入 layers，便于发现“看起来一样但来源不同”的问题。

### 6.4 合并语义

#### required、excluded 和 scope

1. required 采用约束并集。
2. excluded 采用约束并集。
3. 同一 check 同时出现在 required 和 excluded 时直接拒绝配置。
4. 下层 scope 必须处在上层 scope 内；不能用 task scope 扩大 base scope。
5. scope 的比较必须使用规范化后的路径或资源标识，避免相对路径、大小写和分隔符造成绕过。

#### mode

1. 先为每个 required check 计算隐含 mode：没有显式 mode 时为 block。
2. 再与显式 modes 合并。
3. 最后按集中定义的严格度排序选择更严格值。
4. 任何下层试图把已有 block 变成 report_only 或 advisory，都必须拒绝。
5. 不允许在 control_profile.py、control_result.py 和 adapter 中分别定义一套 mode 排序。

建议至少覆盖以下测试：

1. base.required 包含 check-a，base.modes 为空；task.required 包含 check-a，task.modes 设置 report_only，结果必须拒绝。
2. base.required 包含 check-a；task.modes 设置 block，结果可以接受。
3. base.modes 为 block；task.modes 为 advisory，结果必须拒绝。
4. required 与 excluded 冲突，结果必须拒绝。
5. 未知 mode，结果必须拒绝或得到 unknown，不能默认为 advisory。

#### tolerance

1. 使用一个集中定义的严格度排序。
2. 下层只能提高严格度。
3. 未配置的维度继承上层，不得清空上层。
4. 容忍项只影响判定等级，不得隐式改变 check 的目标。
5. tolerance 不能把一个明确的 blocking finding 伪装成 pass。

#### budget 与 repair

1. 数量上限使用各层最小值。
2. 下层设置更大的 max_repairs 或 max_rounds 时拒绝，而不是静默截断后继续执行。
3. repair policy 必须有明确的严格度比较；无法比较时拒绝。
4. recheck_unchanged_input 的语义必须集中定义。若 true 表示即使输入未变也必须重检，则 true 是更严格值，合并使用 OR，并拒绝从 true 降为 false。
5. stop_after_pass 的语义必须集中定义。若 true 表示通过后立即终止，则 true 是更严格值，合并使用 OR，并拒绝从 true 降为 false。
6. 如果代码中的布尔字段语义与文档相反，先统一文档和类型命名，再改实现；不得用一个看不出方向的 bool 运算掩盖语义。

#### baseline

1. generation_mode、audit_mode、challenge_without_explicit_request、independence_required、require_accept、require_proven_independence 等字段都必须参与比较和 digest。
2. source_ref 不能被 task 静默覆盖。若 base 和 task 指向不同事实基线，必须拒绝，或依据公开且可测试的优先级规则重新绑定。
3. SOP Control 不判断 baseline 内容是否正确，只确保调用方声明的 baseline 被稳定引用。
4. baseline_digest 必须来自稳定的规范化输入，不得使用随机值、mtime 或显示文本。

#### expires_at

1. 每个 profile 在规范化阶段把 expires_at 解析为带时区的时间。
2. 建议统一转换为 UTC 的规范字符串后再进入 digest。
3. base 和 task 同时有过期时间时，取实际时间点更早者。
4. 不要使用字符串 min 比较不同 offset 的 ISO 字符串；例如 +08:00 和 Z 可能字典序正确但实际时间顺序不同。
5. 非法、无时区或无法解析的时间必须让 profile 无法编译，或在判定时产生 unknown；绝不能跳过过期检查。

### 6.5 让判定器只接收有效计划

推荐形成一个单一调用约束：

1. 任务打开时合成并冻结有效计划。
2. run override 或 actor capability 变化时，创建新的有效计划，不在原对象上就地修改。
3. 判定器收到 frozen effective plan 后只使用它，不再自行读取 raw base/task 配置。
4. 若 evaluate_control_result 仍保留 base_profile、run_override 等参数，必须保证只有一个组合点，并在组合后重新冻结；不能存在有时组合、有时直接评估 frozen profile 的两条语义不同路径。
5. 返回结果必须同时包含 plan_digest 和各来源摘要，且与 ticket 使用的 plan_digest 相同。

### 6.6 actor capability 的正确位置

actor capability 不是一个新的业务审计器，也不是允许模型自由修改规则的接口。它只表示当前执行者被允许使用的控制能力上限。

1. 复用 capability.py 已有的 ModelProfile、ControlKnobs 和审批状态。
2. 把真正应用到任务的 knobs 形成规范化 snapshot。
3. snapshot 至少包含 tier、max_repairs、write_granularity、strict_schema，以及其来源、evaluation_id、批准状态。
4. snapshot 和 digest 放入 effective plan layers。
5. capability 无法验证时，使用保守上限或直接 unknown，不得当作无限能力。
6. 若任务已冻结，而 actor capability 在执行期间改变，plan_digest 必须不匹配并要求重新冻结；不能继续使用旧 ticket 假装一致。

---

## 7. 工作包 B：修复时间与 fail-closed 判定

### 7.1 当前风险

时间解析函数如果对非法时间返回 None，而调用方只在 exp 和 now 都非 None 时比较，就会形成“解析失败即跳过检查”。同样，如果配置了过期时间但 state.now_iso 为空，也不能证明当前未过期。

### 7.2 必须实现的行为

| 情况 | 结果 |
|---|---|
| 没有 expires_at | 按现有无期限策略执行 |
| expires_at 合法，now_iso 合法且早于过期时间 | 可以继续 |
| now_iso 等于过期时间 | 按文档定义为已过期，建议返回 unknown 或 block |
| now_iso 晚于过期时间 | unknown 或 block |
| expires_at 非法 | 配置拒绝或 unknown/block |
| expires_at 无时区 | 配置拒绝或 unknown/block |
| 配置了 expires_at，但 now_iso 缺失 | unknown/block |
| base/task 时间有不同 offset | 先转绝对时间，再取更早者 |

### 7.3 实现要求

1. 解析函数不能只返回 None 而不返回错误原因。可以使用 typed result、异常或明确的 validation error。
2. normalize_profile 阶段尽早拒绝非法配置。
3. decide_control_result 阶段仍要防御性检查，不能假设所有调用者都走过 normalize。
4. 当前时间应由 GateState 或调用方一次性提供，判定器不得在多个分支分别读取系统时间。
5. 时间值不得进入会导致同一操作 challenge/admit 不一致的 canonical invocation；时间只用于有效期校验。

### 7.4 必须增加的测试

1. 非法日期字符串不会得到 pass。
2. 无时区日期不会得到 pass。
3. expires_at 存在而 now_iso 为空不会得到 pass。
4. now_iso 等于 expires_at 的边界行为稳定。
5. 两个不同 offset 表示同一时刻时，摘要和比较结果稳定。
6. base 比 task 早一天时，有效计划使用 base 的绝对时间。
7. task 比 base 早一天时，有效计划使用 task 的绝对时间。
8. 修改过期时间会改变 effective_plan_digest。

---

## 8. 工作包 C：修复 stop_when 与修复轮数边界

### 8.1 先定义计数含义

实现前必须在代码注释、文档和测试中固定一个计数约定。推荐：

1. round 0 表示首次检查尚未消耗修复轮次。
2. rounds_used 表示本次结果前已经消耗的修复轮次。
3. repair_rounds_used 表示整个任务或运行已经消耗的修复轮次。
4. max_rounds 表示最多允许消耗的修复轮次。
5. 当已有轮数达到 max_rounds 时，不得再发起修复。

因此：

1. max_rounds=0：任何 blocking finding 都直接 block。
2. max_rounds=1，当前已用 0 轮：可以发起一次声明中的修复。
3. max_rounds=1，当前已用 1 轮：blocking finding 必须终止，不能发起第二次修复。
4. 当前已用值大于 max_rounds：状态已经越界，必须 block 或 unknown，不能继续。

### 8.2 stop_when 行为矩阵

至少覆盖以下语义：

| 状态 | 允许继续修复 | 最终结果 |
|---|---:|---|
| required 未运行 | 否 | not_run 或 block |
| 有 blocking finding，预算未耗尽 | 仅按声明的 repair policy | repair_pending 或等价状态 |
| 有 blocking finding，达到 max_rounds | 否 | block |
| 只有 tolerated/advisory finding | 不应自动修复 | pass_with_warnings |
| 所有 required 通过 | 若 stop_after_pass 为 true，不继续 | pass |
| 输入/规则/证据变化 | 可生成新检查 | 新的 plan 或新的 idempotency key |
| stop_when=block | blocking finding 立即 block | block |
| stop_when=max_rounds | 达到上限立即停止 | 不得多跑一轮 |

不要用“为了让 stop_when 生效而把结果改成 pass”的方式修复。终止条件和结果等级是两个概念，必须保持清晰。

### 8.3 必须增加的测试

1. round=0、max_rounds=0。
2. round=max_rounds-1 且有 blocking finding。
3. round=max_rounds 且有 blocking finding。
4. round=max_rounds+1 的损坏状态。
5. stop_after_pass=true 时通过后不会再次调用审计或修复。
6. tolerated finding 不会进入 repair。
7. 只有 required 完成且没有 blocking finding 才能 pass。
8. 审计调用计数能证明达到边界后没有多一次调用。

---

## 9. 工作包 D：让输入摘要真正绑定输入内容

### 9.1 当前风险

如果 submit_input_digest_for 对目录只写入路径和 nonfile 标记，那么目录内文件内容变化不会反映到 input digest。模型可以在同一个目录下替换材料，而系统仍可能认为输入未变。

### 9.2 推荐的目录摘要算法

对每个输入路径执行以下步骤：

1. 解析为受允许 root 约束的规范路径。
2. 拒绝越界路径。
3. 文件：记录相对路径、类型、字节长度和内容 hash。
4. 目录：递归枚举其内部条目，按 POSIX 相对路径排序。
5. 对目录内每一个普通文件记录相对路径、类型、字节长度和内容 hash。
6. 空目录也要有稳定的目录标记，使空目录和不存在目录可区分。
7. 符号链接、设备文件、socket 等特殊文件必须按项目安全策略处理：允许时记录规范目标并防止循环；不允许时直接返回明确失败，不能伪装成普通文件。
8. 内容 hash 必须分块读取，不能因为一个大文件把整个文件一次性载入内存。
9. 不使用绝对路径、mtime、inode、随机数或文件权限作为内容等价性的主要依据。
10. 最终摘要使用固定 schema version、稳定字段顺序和稳定编码。

### 9.3 幂等键必须包含的字段

至少包含：

    input_digest
    baseline_digest
    effective_plan_digest
    check_id
    idempotency_schema_version

如果业务动作需要 task_id、phase 或 operation_id，也必须以明确字段加入，而不是把它们拼在一个无法解释的字符串里。

特别注意：

1. check_id 不能只存在于外层 checked 集合而没有进入每一个结果的幂等身份。
2. 不能再把 base_digest 当作 effective_plan_digest 的备用值。
3. 同一内容、同一基线、同一有效计划和同一 check_id 可以复用已验证结果。
4. 任一内容、基线、规则、检查目标变化都必须产生新键。
5. 同样大小但内容不同的文件必须产生不同 digest。
6. 目录中新增加、删除、重命名或修改文件都必须产生不同 digest。

### 9.4 必须增加的测试

1. 单文件同大小替换内容，digest 改变。
2. 目录内单个文件内容改变，digest 改变。
3. 目录新增、删除、重命名文件，digest 改变。
4. 同一目录不同枚举顺序，digest 不变。
5. 目录存在但为空，与目录不存在不相同。
6. 越界路径、符号链接循环和特殊文件得到明确失败。
7. 大文件摘要不需要一次性读入全部内容。
8. check-a 与 check-b 使用同一输入时，幂等键仍然不同。

---

## 10. 工作包 E：统一 bridge 的 canonical invocation

### 10.1 核心问题

票据指纹必须绑定“真正要执行的业务命令和参数”，而不是绑定某一次包装器的偶然启动形式。以下值通常不应直接进入规范业务 invocation：

1. 临时 wrapper 的路径。
2. shell 中的 $0。
3. Python 或 Node 解释器通过哪种方式启动 wrapper。
4. 临时 handoff 文件路径。
5. challenge 时间、随机数、显示文本。
6. ticket secret。

如果系统的公开契约明确要求绑定 wrapper 身份，则所有启动形式必须重建同一个 wrapper 身份；不能一部分使用 wrapper 路径，一部分使用业务命令。更推荐规范化为“配置的业务命令 token + 用户参数”。

### 10.2 建议的共享结构

在 bridge.py 和 bridge_scaffold.py 之间形成一个共享的规范化构造器，或者形成等价的、经过测试的稳定函数。它应产生类似以下字段：

1. integration_id。
2. action。
3. method、host、path 或其他资源定位字段。
4. 业务命令的 argv token 数组。
5. side_effect 类型。
6. task_id、phase、operation_id、run_id。
7. effective_plan_digest。
8. capability binding。

字段顺序、空值表达、路径规范化和 Unicode 编码必须固定。argv 必须保持 token 边界，不能把参数拼成 shell 字符串后再次解析。

### 10.3 challenge、admit、execute 必须使用同一个 envelope

推荐链路：

    生成 operation_id 和稳定 run_id
      → 构造 canonical envelope
      → challenge
      → 写入短期 handoff
      → 用同一个 envelope admit
      → 执行业务命令
      → 记录脱敏 receipt

要求：

1. challenge 和 admit 由同一份 canonical payload builder 生成。
2. 重试不重新生成 run_id、operation_id 或用户参数。
3. 业务参数改变时必须得到 fingerprint mismatch，而不是签发另一张票据继续尝试。
4. 自动重试最多一次，并且只允许使用原始 handoff。
5. 票据不存在、过期、已消费、阶段不匹配或计划不匹配时，返回具体失败原因。

### 10.4 必须覆盖的启动方式

对每一种方式都断言 challenge fingerprint 与 admit fingerprint 相同，或明确返回“不支持该启动方式”的失败：

1. 直接执行生成的可执行 wrapper。
2. 以 Python 解释器启动 Python scaffold。
3. 以 shell 启动 shell scaffold。
4. 以 Node 启动 Node scaffold。
5. 通过 bridge run 再调用 scaffold。
6. 无参数、多个参数、包含空格的参数。
7. 包含引号、美元符号、反斜杠、Unicode 和换行的参数。
8. 修改一个参数后必须失败，不能仍然使用原 ticket。

如果某种启动形式无法安全重建规范 argv，就不要通过“猜 $0”继续放行，应在安装自检或运行时给出可操作的错误信息。

---

## 11. 工作包 F：修复 secret handoff、脱敏和清理顺序

### 11.1 必须分离的三个生命周期

1. ticket 兑换生命周期：什么时候验证并标记一次性消费。
2. secret 可用生命周期：父进程什么时候仍需要它来脱敏。
3. handoff 文件生命周期：什么时候可以从磁盘删除。

兑换成功不等于父进程已经不需要 secret。如果 admit_ticket 在子进程内先删除 handoff，父进程随后就可能拿不到 secret，导致子进程输出中的 secret 无法脱敏。

### 11.2 推荐执行顺序

1. challenge 产生票据并写入权限为 0600 的短期 handoff。
2. 父进程在启动子进程前读取 secret 到本次执行的脱敏上下文。
3. 子进程只获得 handoff 路径或 file descriptor，不获得明文 secret。
4. 子进程在真正 admission 点兑换票据。
5. 捕获 stdout、stderr、异常文本和命令摘要。
6. 对所有捕获内容执行统一 secret scrub。
7. 只有在 scrub 完成并准备好 receipt 后，删除 handoff。
8. receipt 只保存脱敏后的 command、summary、digest 和必要状态。
9. 失败路径也必须执行 scrub 和清理；过期 handoff 由有界 sweep 清理。

如果保留“成功兑换后立即删除 handoff”的策略，必须证明父进程已经在删除前读取了 secret，并由测试保证这一点。否则应让删除责任归属于最外层执行器。

### 11.3 禁止泄露的位置

secret 不得出现在：

1. argv。
2. 普通环境变量值。
3. 日志。
4. stdout、stderr。
5. receipt。
6. 错误对象的 str 或 repr。
7. task 摘要。
8. 模型上下文。
9. git diff 或生成的报告。

redact_argv、redact_command 和 summary 生成器必须共享同一套脱敏规则。不要只脱敏命令行而忘记异常文本，也不要只替换完整 secret 而忘记可能出现的 URL、JSON 或 shell 转义形式。

### 11.4 必须增加的测试

1. 子进程主动打印完整 secret，外层 stdout 不含 secret。
2. 子进程主动打印部分 secret、JSON 转义 secret 和 URL 形式，输出仍脱敏。
3. receipt 不含 secret。
4. command 摘要不含 secret。
5. 成功路径 handoff 最终删除。
6. 失败路径 handoff 最终删除或在明确的短期重试窗口后删除。
7. admit_ticket 删除 handoff 的实现不会破坏父进程 scrub。
8. ticket 已消费、过期和 fingerprint mismatch 的错误输出都不泄露 secret。

---

## 12. 工作包 G：收紧 Capability Ticket 的绑定并降低开销

### 12.1 票据应绑定什么

对有副作用的动作，ticket 至少绑定：

1. project_id。
2. task_id。
3. phase。
4. action。
5. operation_id 或稳定 run_id。
6. effective_plan_digest。
7. capability binding。
8. allowed_actions。
9. expires_at。
10. payload fingerprint。

当 admit 调用显式传入 expected_plan_digest 或 expected_phase 时：

1. ticket 必须存在相同绑定。
2. ticket 字段为空不能视为通配。
3. ticket 不同必须拒绝。
4. 不能用“只有 ticket 有值才比较”的条件形成未绑定票据的绕过。

### 12.2 低成本方案

用户的第一优先级是节省时间、token 和能耗，因此不要把每一个内部写动作都设计成一次独立的 challenge/admit 往返。推荐：

1. 只读动作默认不申请 ticket。
2. 对同一 task、phase、effective plan 和 operation，签发一个短时、单用途或有限动作集合的 phase-level grant。
3. allowed_actions 明确列出该阶段允许的动作。
4. 不允许把 phase-level grant 变成跨项目、跨任务、跨阶段的全局票据。
5. 对一次链式执行，沿用同一个稳定 run_id，不要每次重试重新生成。
6. 在 wrap 或 bridge 内部完成 challenge、handoff、admit 和执行，让模型不需要复制 ticket。
7. 自动重试最多一次；第二次仍失败就报告产品缺口，不进入死循环。
8. 禁止用全局 JOBSFLOW_SOPCONTROL_TICKETS=off 或等价开关作为生产解决方案。

票据的作用是证明“这个受控入口允许执行”，不是替代业务系统的语义检查。票据数量减少后，语义检查仍由业务系统按其声明的计划执行。

### 12.3 必须增加的测试

1. expected plan 存在、ticket plan 为空时拒绝。
2. expected phase 存在、ticket phase 为空时拒绝。
3. ticket action 不在 allowed_actions 时拒绝。
4. 同一 ticket 第二次兑换失败。
5. run_id 改变时失败。
6. effective_plan_digest 改变时失败。
7. 只读动作不产生无必要的 ticket 往返。
8. 同一 phase 的低风险动作可以按设计共享一次授权，但跨 phase 不可以。
9. challenge 失败不会无界签发新票据。

---

## 13. 工作包 H：输入、结果、票据三方一致性

### 13.1 统一绑定关系

一个可接受的控制结果必须能回答：

1. 针对哪个 task。
2. 针对哪个 phase。
3. 使用哪个 baseline。
4. 使用哪个 input digest。
5. 使用哪个 effective plan。
6. 执行了哪个 check_id。
7. 使用了哪个 operation/run。
8. 结果在什么时候判定。
9. 是否经过了规定的受控入口。

建议让以下对象都携带同一 plan digest：

1. frozen task contract。
2. ControlResult。
3. ticket。
4. receipt。
5. external check result。
6. repair proposal。

### 13.2 禁止的兼容逻辑

以下逻辑必须通过搜索清除或改成显式失败：

1. “effective_plan_digest 为空就使用 base_digest”。
2. “ticket 没有 plan 绑定就当成任意 plan”。
3. “目录不是文件所以只记 nonfile”。
4. “时间解析失败所以不做过期比较”。
5. “当前 run_id 不同，但只要 action 相同就继续”。
6. “旧 receipt 有 pass，所以新规则下也可以复用”。

如果确实需要兼容历史数据，必须有 schema version、迁移逻辑和明确的“旧数据不能用于新 enforce 判定”测试。

---

## 14. 工作包 I：桥接安装、覆盖与回滚

当前已有对既有 wrapper 备份、权限保存和 remove 恢复方向的实现，但仍必须按失败路径回归，不能因为安装成功测试通过就认为完成。

### 14.1 安装要求

1. 安装前识别目标是新文件、已有文件、符号链接还是特殊文件。
2. 已有文件必须安全备份，且备份路径只能位于受控 rollback 目录。
3. 记录原始 mode，并尽量保留必要元数据。
4. 写入应尽量使用临时文件加原子替换。
5. 备份失败时不能继续覆盖目标。
6. 重复安装不能无限叠加备份或破坏最初文件。
7. 生成的 wrapper 必须包含与 bridge 相同的 canonical invocation 语义。

### 14.2 移除要求

1. 只移除由本工具安装的内容。
2. 不删除其他产品已有的 hook、plugin 或配置。
3. 恢复文件前验证备份清单来自受控目录，不能信任用户可任意篡改的路径字段。
4. 恢复文件内容和 mode。
5. 没有本工具安装痕迹时，detach 应给出无副作用的明确结果。
6. 删除动作本身应有测试覆盖，不得把任意路径交给 unlink。

### 14.3 必须增加的测试

1. 目标不存在时 install/detach。
2. 目标已存在时 install/detach。
3. 目标为可执行文件时 mode 保持。
4. 重复 install 后仍能恢复原始内容。
5. 备份写入失败时目标不变。
6. manifest 或 rollback 字段被篡改时不读取任意路径。
7. Claude/OpenCode 未安装时不会凭空创建无效 harness 目录。
8. 只移除 sopctl 自己的 hook，保留其他 hook。

---

## 15. 工作包 J：测试矩阵与反例驱动验收

### 15.1 动态规则单元测试

至少覆盖：

1. required 默认 block。
2. mode 降级拒绝。
3. required/excluded 冲突拒绝。
4. scope 扩大拒绝。
5. tolerance 降级拒绝。
6. budget 增大拒绝。
7. repair max_rounds 增大拒绝。
8. baseline source_ref 改变拒绝或按明确优先级处理。
9. 所有 repair 字段都被合并。
10. 所有 stop_when 字段都被执行。
11. 四层输入都进入 layers 和 digest。
12. 同一输入得到稳定 digest。
13. 任一层改变都会改变 effective_plan_digest。
14. 未知字段不会静默通过。

### 15.2 判定器单元测试

至少覆盖：

1. plan digest 缺失。
2. plan digest 不匹配。
3. task revision 不匹配。
4. profile 过期。
5. now 缺失。
6. invalid expires_at。
7. required check 未运行。
8. excluded check 被运行。
9. blocking finding。
10. tolerated finding。
11. advisory finding。
12. stop_after_pass。
13. max_rounds=0。
14. max_rounds 边界。
15. 旧结果输入 digest 不匹配。
16. 结果没有 check_id。

### 15.3 输入绑定测试

至少覆盖：

1. 单文件同大小改内容。
2. 目录内容改动。
3. 目录排序差异。
4. 新增和删除文件。
5. 符号链接。
6. 越界路径。
7. 大文件流式 hash。
8. baseline 改动。
9. plan 改动。
10. check_id 改动。

### 15.4 Bridge 集成测试

至少覆盖：

1. challenge→handoff→admit→execute→receipt 完整链路。
2. challenge/admit canonical payload 完全相同。
3. 参数修改会失败。
4. run_id 修改会失败。
5. plan digest 修改会失败。
6. ticket 重放会失败。
7. ticket 过期会失败。
8. child 输出 secret 会被 scrub。
9. receipt 不含 secret。
10. handoff 最终清理。
11. wrapper 的三种解释器启动形式。
12. bridge run 套 scaffold。
13. 失败时不会无限重试。

### 15.5 端到端测试

建立一个最小虚拟业务命令，不涉及 JobsFlow 业务语义，只验证控制面：

1. 配置一个 required check。
2. 配置一个 excluded check。
3. 配置一个 tolerated check。
4. 配置一个 blocking finding。
5. 使用 base、task、run、actor 四层输入。
6. 经过 bridge 执行一次。
7. 让业务命令返回成功、失败、打印 secret、改变输入四种结果。
8. 检查每一种结果的 verdict、next_action、plan digest、receipt 和 ticket 状态。

端到端测试的目的，是证明“所有组件合起来仍遵守同一份计划”，不是测试业务系统是否会做出正确的语义判断。

---

## 16. 建议的执行顺序

外部模型应按下面的批次推进，不能一次性大面积改动后只跑一遍全量测试。

### 批次 1：建立基线

1. 读取 AGENTS.md、PLAYBOOK.md、DESIGN.md 和本文。
2. 检查 git status、当前分支和 HEAD。
3. 使用 sopctl task list、task show 查找当前链头。
4. 如果已有任务处于 blocked，不要直接重做；使用 sopctl task open --resolves 创建解决任务。
5. 不直接读取或写入 .sopcontrol 内文件；需要状态时使用 sopctl 子命令。
6. 记录当前完整测试、覆盖率、ruff、gate 和 project check 结果。

### 批次 2：先写反例测试

先为 DR-01 至 DR-05 写失败测试，再实现代码。每一个测试都必须说明：

1. 初始配置。
2. 调用入口。
3. 预期 verdict 或异常。
4. 为什么不能 pass。
5. 使用了哪个 plan/input/ticket digest。

### 批次 3：收口有效计划

完成工作包 A，再运行 control_profile、control_result、capability、task 相关定向测试。没有 plan digest 一致性之前，不要继续修 bridge。

### 批次 4：收口时间、终止和输入绑定

完成工作包 B、C、D。重点观察：

1. 解析失败是否真的不再 pass。
2. 达到 max_rounds 后是否真的没有下一次 repair call。
3. 目录内容变化是否真的改变 digest。

### 批次 5：收口 bridge 与 ticket

完成工作包 E、F、G、I。每次修改后至少运行对应 bridge 单测和一个完整链路测试。

### 批次 6：全量验收

运行第 18 节的全部命令。任何命令失败，都不能通过删测试、跳过测试、降低 coverage threshold 或关闭 enforce 来结案。

### 批次 7：治理收口

1. 使用 sopctl project all . 刷新生成投影。
2. 使用 sopctl project check 检查投影没有 stale。
3. 使用 sopctl chronicle check 检查编年完整性。
4. 使用 sopctl gate . 检查最终控制面。
5. 提交代码和文档前检查 git diff --check。
6. 最终报告必须列出未修改的业务系统范围。

---

## 17. 代码修改的精确落点建议

这不是要求机械照搬的 patch，而是外部模型定位调用链时的最小边界。

### control_profile.py

需要重点检查和可能修改：

1. profile 规范化和非法字段拒绝。
2. 所有 profile 字段的 merge。
3. 隐含 required→block 的计算。
4. baseline.source_ref 的比较。
5. repair 的所有字段。
6. stop_when 的所有字段。
7. expires_at 的 aware datetime 规范化。
8. base/task/run/actor 的 layers 和 digest。
9. 不可比较或降级时的异常类型和可观察原因。

### control_result.py

需要重点检查和可能修改：

1. 时间失效和 now 缺失的 fail-closed 行为。
2. mode 的唯一来源。
3. effective plan 的唯一使用路径。
4. max_rounds 的边界。
5. stop_after_pass 的实际终止行为。
6. required、excluded、tolerated、advisory、blocking 的结果区分。
7. result 中的 plan/input/baseline/check 绑定。
8. 不得保留 base_digest fallback。

### task.py

需要重点检查和可能修改：

1. 输入路径安全解析。
2. 文件和目录的递归内容摘要。
3. 稳定排序和流式 hash。
4. 幂等键的 check_id、baseline_digest、effective_plan_digest。
5. submit 与 verify 使用同一摘要算法。

### tickets.py

需要重点检查和可能修改：

1. plan、phase、action、task、run 的严格匹配。
2. expected binding 存在时不允许空字段通配。
3. 单次兑换。
4. 过期和错误状态。
5. 票据 secret 不出现在异常和返回文本。

### bridge.py

需要重点检查和可能修改：

1. canonical invocation builder。
2. challenge/admit 的 envelope 一致性。
3. stable run_id 和 operation_id。
4. handoff 读取、脱敏、删除顺序。
5. stdout、stderr、异常和 receipt 的统一 scrub。
6. 自动重试上限。
7. wrapper 备份、恢复和权限。

### bridge_scaffold.py

需要重点检查和可能修改：

1. shell、Python、Node 三种 scaffold 是否使用相同规范命令。
2. 直接执行和解释器启动是否得到相同 envelope。
3. 参数是否保持 token 边界。
4. 不把 $0、sys.argv[0] 或 process.argv[1] 当成不稳定的业务命令指纹。
5. 失败安装时不覆盖目标。

### .github/workflows/ci.yml 与 pyproject.toml

需要重点检查：

1. CI 是否明确启用 branch coverage。
2. 本地和 CI 的测试入口是否使用同一套参数。
3. coverage threshold 没有被降低。
4. 新测试没有被默认排除。

---

## 18. 最终验收命令

外部模型必须在仓库根目录执行以下检查。命令参数以当前项目实际 CLI 为准，但不得省略语义。

### 18.1 测试与覆盖率

    .venv/bin/pytest -q

    COVERAGE_FILE=/tmp/sopcontrol-coverage-final .venv/bin/pytest -q --cov --cov-branch --cov-report=term-missing

覆盖率必须不低于项目当前阈值 85.0%。不能只运行定向测试后报告完成。

### 18.2 静态检查

    .venv/bin/ruff check sopcontrol plugins tests

    git diff --check

### 18.3 SOP Control 自身检查

    .venv/bin/sopctl gate .

    .venv/bin/sopctl project check

    .venv/bin/sopctl chronicle check

如 sopctl 不在 PATH，使用项目已有的等价 python -m sopcontrol.cli 入口。不要用修改 PATH、关闭 enforce 或删除 hook 的方式掩盖失败。

### 18.4 代码扫描式验收

使用 rg 对实现和测试进行定向检查，确认不存在以下危险模式，除非它们只出现在明确的负向测试说明中：

1. plan digest 不匹配时 fallback 到 base digest。
2. expires_at 解析失败后直接跳过检查。
3. expires_at 存在但 now_iso 缺失仍继续 pass。
4. 目录输入只产生 nonfile 标记。
5. challenge 使用一个 argv，admit 使用另一个 argv。
6. 使用 $0 或 sys.argv[0] 作为不稳定业务命令指纹。
7. handoff 删除发生在父进程读取 secret 和 scrub 之前。
8. expected plan/phase 存在但空 ticket 字段被当作通配。
9. rounds_used 只用大于 max_rounds 判断是否能继续 repair。
10. 全局 ticket-off 作为生产默认路径。

扫描结果应写入外部模型的交付报告，说明每个命中项是已修复、合法实现还是负向测试。

---

## 19. “彻底完成”的硬性定义

只有同时满足下面条件，才可以报告完成：

1. DR-01 至 DR-05、BR-01 至 BR-03 全部关闭。
2. DR-06、BR-04、OPS-01、OPS-02 有实现和测试证据。
3. 所有新增反例测试通过。
4. 完整测试通过，不能以 skipped 代替关键行为测试。
5. branch coverage 达到至少 85.0%。
6. ruff、diff check、sopctl gate、project check、chronicle check 全部通过。
7. 所有 task、result、ticket、receipt 使用同一 effective_plan_digest。
8. 任何非法时间、缺失 now、缺失绑定、输入变化和参数变化都不会得到 pass。
9. max_rounds 到达边界后没有额外修复调用。
10. 子进程打印 ticket secret 时，任何用户可见输出和 receipt 都不包含 secret。
11. 直接 wrapper、解释器 wrapper、bridge run 的规范 fingerprint 一致，或不支持时明确拒绝。
12. 没有新增无限重试、全局绕过开关或业务语义判断。
13. 生成投影和治理账本处于一致状态。
14. 交付报告列出修改文件、测试命令、测试结果、覆盖率、剩余已知限制和未触碰的业务系统范围。

以下结果不算完成：

1. “859 个测试通过，所以完成”，但没有新增反例。
2. “coverage 通过”，但运行的是没有 branch coverage 的命令。
3. “ticket 可以使用”，但只能人工复制 secret。
4. “bridge 可以运行”，但参数改变后仍能使用原票据。
5. “profile 有 digest”，但判定器、task 和 ticket 的 digest 不同。
6. “有 independent audit 字段”，但 SOP Control 自己替业务系统决定审计内容。
7. “失败可以重试”，但每次重试都重新生成 run_id 或新票据。
8. “安装成功”，但没有验证覆盖已有文件和恢复原文件。

---

## 20. 最终交付报告模板

外部模型完成后必须按下面结构报告，不能只说“已修复”：

### A. 结论

说明是否达到本文“彻底完成”的定义；如果没有，明确列出阻断项。

### B. 修改清单

按 control_profile.py、control_result.py、task.py、tickets.py、bridge.py、bridge_scaffold.py、测试和 CI 分组列出修改内容。

### C. 规则语义

说明：

1. 四层计划如何合成。
2. 每个字段如何单调合并。
3. invalid/unknown/block/pass 的边界。
4. max_rounds 和 stop_after_pass 的计数语义。
5. actor capability 如何参与而不变成新的业务审计器。

### D. 票据与桥接

说明：

1. canonical payload 的字段。
2. stable run_id/operation_id 的来源。
3. handoff 的生命周期。
4. scrub 的执行顺序。
5. wrapper 各启动方式的结果。
6. ticket 往返次数和 phase-level grant 策略。

### E. 测试证据

逐条列出：

1. 定向测试命令及结果。
2. 完整测试命令及结果。
3. branch coverage 结果。
4. ruff 和 diff check。
5. gate、project check、chronicle check。
6. 关键负向用例的名称和结论。

### F. 未修改范围

明确说明没有修改业务系统的：

1. JD 抓取。
2. 材料生成。
3. 语义 lint。
4. 事实基线内容。
5. 业务产品的审计风格。

### G. 剩余风险

只列出已经确认、无法在本任务内解决的风险，并说明为什么不属于 SOP Control 控制面；不能用“未来再看”代替风险描述。

---

## 21. 给外部模型的最后指令

请把本文当作验收契约执行：

1. 先读项目规则和当前实现，再修改。
2. 先写会失败的反例测试，再写修复。
3. 任何动态规则都必须进入同一份有效计划。
4. 任何有效计划都必须有稳定、可追踪的 digest。
5. 任何失败路径都必须 fail-closed。
6. 任何受控入口都必须使用同一份 canonical payload。
7. 任何 secret 都必须在 receipt 和用户可见输出之前完成脱敏。
8. 任何输入目录都必须绑定实际内容。
9. 任何达到上限的修复都必须立即终止。
10. 不新增第二个业务审计者，不扩大 SOP Control 的职责，不以增加模型调用换取表面上的谨慎。
11. 不直接修改 .sopcontrol/，不关闭 enforce，不删除 hook，不降低覆盖率门槛。
12. 如果发现当前任务已经 blocked，按项目规则另开 resolves 任务，不重做已交付副作用。
13. 只有在所有硬性验收项都通过后，才可以报告“最终闭环完成”。

最终要证明的不是“代码看起来更严”，而是：

    规则由业务系统声明，
    SOP Control 忠实合成并执行规则，
    任何入口都无法悄悄放宽规则，
    不必要的重复动作被终止，
    失败、漂移和绕过都能被明确暴露，
    同时不替业务系统发明它没有要求的语义审计。

