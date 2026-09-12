# SOP Control 动态规则控制能力增强技术手册

> 版本：2026-09-09
> 性质：SOP Control 控制层增强方案
> 适用对象：SOP Control 核心开发者、规则作者、适配器开发者
> 本文范围：增强动态规则的表达、解析、冻结、执行和验证能力
> 本文不负责：业务产品的语义检查算法、业务产物生成、业务文件存储和具体产品流程

---

## 0. 执行摘要

复杂任务中，用户往往不是要求系统始终严格或始终宽松，而是要求系统在不同维度采用不同标准：

- 只审查指定方面，不要自动扩大审查范围；
- 对关键事实严格，对合理表达差异宽松；
- 生成时接受已经确定的事实基线，不要临场重新质疑；
- 如果生成后出现偏差，只修正达到阈值的问题；
- 审查通过后停止，不要因为模型又想到新的优化点而重复审查。

这类要求具有动态性，但动态不等于每次执行都重新解释。SOP Control 的目标是：

> 允许规则在任务开始前动态组合和调整，但在一次运行内冻结为确定的执行契约。

SOP Control 不需要知道业务检查本身如何实现。它需要控制的是：

1. 本次任务启用了哪些检查；
2. 哪些检查明确排除；
3. 每个检查采用何种严格程度；
4. 基线是接受、验证还是协调；
5. 什么结果允许通过；
6. 什么结果必须阻断；
7. 允许多少次修正和重检；
8. 何时必须停止。

---

## 1. 产品边界

### 1.1 SOP Control 应该负责什么

SOP Control 负责把用户和项目的动态要求转化为可执行的控制契约，并在运行中约束执行器。

它应该负责：

- 动态要求的结构化；
- 规则优先级和冲突处理；
- 任务级或运行级范围；
- 基线使用模式；
- 检查能力的启用与排除；
- 严格程度和容忍度；
- 修正预算和停止条件；
- 结果的新鲜度、作用域和版本一致性；
- 任务状态和合法动作；
- 运行时放行或阻断；
- 最小控制证据。

### 1.2 SOP Control 不应该负责什么

以下内容不应被搬入 SOP Control：

- 具体业务语义检查算法；
- JD、材料或其他业务文件的完整内容；
- 业务系统的文件生成和存储；
- 业务引擎如何实现 LLMO；
- 替用户决定哪些表达在业务上更好；
- 默认要求人工审批或多个 Agent；
- 通过增加更多票据和日志来替代真正的流程控制。

SOP Control 可以要求外部系统完成某项检查，也可以验证外部系统返回的结果是否符合控制契约，但不应实现该检查的业务判断。

### 1.3 不改变现有骨架

现有 Rule、Evidence、Verdict、Task、Hook、Harness、Gate 和 Rule 生命周期继续保留。

本方案新增的是一层任务或运行级的动态配置，不是第二套永久规则库：

    Base Rule Set
        + Dynamic Control Profile
        = Effective Control Plan

Base Rule Set 是项目的长期规则。Dynamic Control Profile 是本次执行对已有规则和检查方式的选择。Effective Control Plan 是冲突解析后的冻结结果。

---

## 2. 核心设计原则

### 2.1 动态配置，静态执行

动态规则允许在任务开始前由用户、产品或项目上下文组合出来，但一次运行开始后必须冻结。

    捕获要求
        ↓
    规范化
        ↓
    冲突检查和预览
        ↓
    冻结为 revision
        ↓
    运行时只执行该 revision

执行过程中若确实需要改变，必须创建新的 revision，并重新计算受影响的动作。不得在同一个 revision 内静默改变含义。

### 2.2 严格控制规则，不严格控制一切内容

SOP Control 的严格对象是：

- 审查范围；
- 基线模式；
- 严格程度；
- 修正权限；
- 调用次数；
- 状态转移；
- 结果有效性。

它不是要求所有业务内容都字面一致，也不是让模型对所有可能问题都进行检查。

### 2.3 LLM 解释一次，控制器执行多次

不要让 LLM 在每一个步骤重新解释用户原话。可以在任务开始时把自然语言要求规范化成结构化配置，随后由 SOP Control 和适配器执行该配置。

LLM 可以参与初次规范化，但不能在后续步骤自行修改已冻结的配置。

### 2.4 正向规则和负向边界同等重要

只写“必须检查 JD 贴合度”不够，还要明确：

- 不检查哪些方面；
- 哪些发现不阻断；
- 哪些偏差允许保留；
- 哪些动作禁止自动触发。

否则模型会把“保证质量”扩展成“审查一切”。

### 2.5 规则的变化不能污染历史

任务级临时要求只能影响当前任务或运行。只有经过显式生命周期操作，才可以成为项目长期规则。

规则变化应通过新 revision 表达，不得覆盖旧规则并让历史证据失去可解释性。

---

## 3. Dynamic Control Profile

### 3.1 概念

Dynamic Control Profile 是一次任务或一次运行的动态控制配置。它不拥有业务语义，只声明外部检查和执行器必须遵守的边界。

建议包含以下维度：

    identity
    scope
    phase
    required checks
    excluded checks
    severity policy
    baseline mode
    tolerance policy
    repair policy
    budget
    stop conditions
    expiry

### 3.2 建议字段

以下为概念结构，字段可以与现有模型统一：

    profile_id: run-material-quality
    profile_revision: 4
    scope:
      project: current-project
      task: TASK-XXXX
      phase: material-audit
    checks:
      required:
        - jd_fit
        - factual_accuracy
        - llmo
      excluded:
        - style_polish
        - unrelated_quality
        - literal_baseline_rewrite
    baseline:
      source_ref: jd-snapshot
      generation_mode: authoritative
      audit_mode: compare_output_only
      challenge_without_explicit_request: false
    tolerance:
      reasonable_exaggeration: allowed
      material_misstatement: block
      minor_wording_drift: report_only
    repair:
      policy: hard_errors_only
      max_rounds: 1
      recheck_unchanged_input: false
      stop_after_pass: true
    budget:
      max_audit_calls: 1
      max_repair_calls: 1
    expires_at: null

该配置描述控制要求，不保存完整业务产物。

### 3.3 规则优先级

推荐优先级：

    系统不变量
        >
    项目已接受的基础规则
        >
    任务级动态配置
        >
    运行级临时配置

低层配置可以收紧上层要求，也可以关闭非强制检查，但不能关闭系统不变量或绕过已声明为 MUST 的控制。

### 3.4 任务级临时配置

用户临时说“这次只看 JD，不要过度纠结文字”，应形成任务级 profile，而不是直接修改项目永久规则。

任务结束后：

- 任务级 profile 自动失效；
- 其结果仍保留 profile revision；
- 不影响下一次任务；
- 如需长期使用，必须显式晋升为项目规则。

---

## 4. 动态规则的表达原语

### 4.1 必须支持的原语

    MUST_CHECK
      本次必须执行的检查。

    MUST_NOT_CHECK
      本次明确排除的检查。

    MUST
      不满足就阻断。

    SHOULD
      不满足时提示或记录，但默认不阻断。

    MAY
      允许执行，但不要求执行。

    STOP_WHEN
      满足条件后停止继续审查或修正。

    REPORT_ONLY
      只记录，不改变状态。

    REPAIR_ONLY_IF
      只有满足指定严重程度或条件才允许修正。

### 4.2 每个维度独立设置严格程度

不要只有一个全局的 strict 或 lenient 开关。不同检查可以采用不同模式：

    checks:
      jd_fit:
        mode: block
      factual_accuracy:
        mode: block
      llmo:
        mode: required
      wording_style:
        mode: ignore
      literal_baseline_match:
        mode: report_only

SOP Control 不需要理解这些检查的业务算法，只需要控制它们是否是当前任务的必需前置条件，以及不同结果如何影响状态迁移。

### 4.3 范围外发现

外部检查可能发现超出当前范围的问题。结果必须能标记为：

    out_of_scope

范围外发现：

- 不能阻断当前任务；
- 不能自动触发修正；
- 可以留作观察或候选；
- 只有明确纳入新 profile 后，才进入当前控制链。

---

## 5. 基线控制

### 5.1 三种基线模式

SOP Control 必须区分以下模式：

    authoritative
      基线是当前生成的权威依据，不自动质疑。

    verify
      本次明确要求验证基线本身是否正确。

    reconcile
      允许拿基线和外部信息比较，并产生冲突待决状态。

默认不得从 authoritative 自动升级到 verify 或 reconcile。

### 5.2 接受基线不等于审查基线

以下两个命题必须独立：

    接受基线作为工作依据
    ≠
    审查基线本身是否正确

如果用户要求基线作为本次工作的权威依据，执行器就不应把“质疑基线”自行加入审查范围。发现冲突时，应产生 baseline_conflict，等待明确决策，而不是静默修改基线。

### 5.3 生成与事后审计分离

用户可以同时要求：

1. 生成时尽量遵循基线；
2. 生成后不要为了字面一致而过度修改。

这不是矛盾，而是两个不同阶段的规则：

    生成阶段
      尽量避免偏离基线。

    审计阶段
      只对达到修正阈值的问题采取行动。

例如基线中使用 reviewing，生成时应尽量使用 reviewing，而不是随意写成 drafting。如果已经出现 drafting，后续是否修改应由 tolerance 和 repair policy 决定，而不是由模型自行追求字面一致。

### 5.4 基线接受事件

任务开始时记录轻量状态：

    baseline_ref
    baseline_digest
    baseline_mode
    accepted_by
    accepted_at

该事件只表示本次如何使用基线，不表示基线本身已经通过验证。

---

## 6. 审计结果与状态门

### 6.1 不使用单一布尔值

仅有 independent_audit_passed 或 user_accepted 不足以表达动态规则。

至少需要区分：

    pass
      必需检查完成并满足要求。

    pass_with_warnings
      存在允许保留的提醒，不影响继续。

    block
      存在必须阻断的问题。

    not_run
      要求执行但尚未执行。

    unknown
      证据不足，不能判定。

    out_of_scope
      当前 profile 明确不检查。

### 6.2 审计结论与修正动作分离

“发现问题”不等于“必须修改”。结果至少要分开：

    finding_severity
    repair_action

建议使用以下等级：

    blocking
      达到阈值，阻断并允许有限修正。

    tolerated
      发现但允许保留，只记录。

    advisory
      仅提示。

    out_of_scope
      不进入本次任务的判定。

### 6.3 状态门的确定性规则

    required check 缺失
      → not_run 或 blocked

    required check 过期或 scope 不匹配
      → unknown 或 blocked

    存在 blocking finding
      → block

    只有 tolerated 或 advisory finding
      → pass_with_warnings

    所有 required check 满足且达到 STOP_WHEN
      → pass

模型不能把 warn 自行升级为 block，也不能把 unknown 或 not_run 自行解释成 pass。

### 6.4 独立性的配置化

独立审计不必默认等于人工审批或另一个 Agent，但独立性要求必须结构化：

    self_check
    separate_context
    separate_actor
    human_required

SOP Control 只负责检查实际结果是否符合当前配置。例如 profile 要求 separate_actor 时，生成者的自报理由不能作为独立审计通过凭据。

---

## 7. 修正和重复控制

### 7.1 修正策略

    repair:
      allowed_severities:
        - blocking
      max_rounds: 1
      preserve_tolerated_variance: true
      no_style_polish: true
      no_scope_expansion: true
      stop_after_pass: true

### 7.2 防止过度修正

某个偏差已经被判定为 tolerated 后，后续模型不能自行把它升级为 blocking。只有以下情况允许重新判定：

- 用户显式改变 profile；
- 基线、材料或证据发生变化；
- 更高优先级规则发生变化；
- 原判定被明确撤销。

### 7.3 审计幂等键

相同输入、基线、策略和检查能力不应重复消耗调用。建议使用：

    input_digest
    + baseline_digest
    + effective_plan_digest
    + check_id

生成幂等键。

幂等键不变且结果仍新鲜时，可以复用结果。

### 7.4 变化影响映射

如果变化只影响格式，不应重新执行 JD 贴合度检查；如果变化影响材料主体，才重新执行受影响的检查。

SOP Control 应允许外部执行器声明动作影响哪些检查维度，但最终是否需要重检由冻结的控制计划决定。

---

## 8. Effective Control Plan

### 8.1 生成过程

    Base Rule Set
        + Task Profile
        + Run Override
        + Actor Capability
        ↓
    conflict resolution
        ↓
    Effective Control Plan

Effective Control Plan 必须是确定性的。同样的输入、规则 revision、profile 和执行器能力，应得到同样的计划。

### 8.2 计划摘要

投影给 Agent 的内容只需要包括：

    当前范围
    明确排除范围
    基线模式
    各维度严格程度
    修正上限
    停止条件
    当前状态
    下一合法动作

完整历史和完整证据仍保留在控制面，不应每次全部注入模型上下文。

### 8.3 计划绑定

任务、运行授权、控制事件和外部检查结果应引用同一个：

    effective_plan_digest

这样可以防止任务按一套规则开始，却按另一套规则验收。

---

## 9. 与现有模块的结合

本节只规定 SOP Control 侧的改造方向，不规定任何业务产品内部实现。

### 9.1 registry 与规则生命周期

- 基础 Rule 继续由 registry 管理；
- Dynamic Control Profile 不直接变成永久 Rule；
- 任务级 profile 独立保存；
- Rule 的 accept、suspend、narrow、supersede、deprecate 继续走现有生命周期；
- Rule revision 变化时，受影响的 Effective Control Plan 和旧结果应失效。

### 9.2 task

任务契约增加：

    control_profile_id
    control_profile_revision
    effective_plan_digest

任务进入执行状态后，执行器不能自行扩大 profile。显式变更必须创建新的 revision。

### 9.3 verdict

Verdict 应支持按检查维度聚合，而不是只保存一个总布尔值。聚合结果必须能解释：

- 哪些 required check 已完成；
- 哪些检查未执行；
- 哪些发现被容忍；
- 哪些发现阻断；
- 为什么达成或没有达成停止条件。

### 9.4 tickets

能力授权绑定：

    project_id
    task_id
    phase
    effective_plan_digest
    allowed_actions
    expires_at

推荐按任务阶段或运行发放短期授权，而不是每个低风险动作单独挑战。高风险不可逆动作可以继续单独收紧。

### 9.5 ledger、trace 与 events

控制面只记录：

    profile 使用了哪个 revision
    执行了哪些必需控制
    哪些结果被接受
    哪些状态迁移被阻断或放行
    关联了哪些外部结果

不复制完整业务产物。外部系统可以提供 result_id、artifact_ref 或 digest，SOP Control 只保存引用并验证其与当前计划的对应关系。

### 9.6 doctor、audit 与 coverage

SOP Control 自身应检查：

- profile 能否解析；
- profile 是否存在冲突；
- required 和 excluded 是否重叠；
- 任务是否绑定有效 plan digest；
- 结果是否引用相同 revision；
- 动态配置是否过期；
- 是否存在导致重复审查的旁路状态；
- 规则消费者和控制入口是否仍然存在。

这些检查验证控制协议是否可靠，不代替业务系统执行语义检查。

---

## 10. 低成本路径

### 10.1 本地确定性预处理

范围、优先级、预算、排除项、幂等键和状态门应尽量在本地完成，不需要额外模型调用。

### 10.2 一次编译，多次执行

一次生成 Effective Control Plan，后续只传摘要和 digest，不重新解释完整自然语言。

### 10.3 分层检查

低成本的结构和状态检查先执行，只有确实需要语义判断的维度才进入高成本检查。

### 10.4 阶段级授权

将多个同一阶段的低风险动作绑定到一张短期授权，降低先取票再执行的重复往返。

### 10.5 达到停止条件立即停止

通过后的结果应具有终止性。除非输入、规则或证据变化，不允许模型以“可以再优化”为理由重新开启流程。

### 10.6 成本指标

至少记录：

    每个任务的审计调用次数
    重复审计次数
    平均修正轮数
    范围外 finding 数
    容忍偏差数
    因 profile 冲突产生的阻断数

目标是让成本来自用户明确要求的控制，而不是模型自行扩大或重复执行。

---

## 11. 建议的控制结果协议

外部检查结果至少应能被转换为以下结构：

    result_id
    task_id
    profile_id
    profile_revision
    effective_plan_digest
    input_refs
    checked_dimensions
    excluded_dimensions
    findings
    verdict
    repair_action
    rounds_used
    stop_reason
    producer

SOP Control 需要验证：

1. profile 和 plan digest 是否一致；
2. 输入是否属于当前任务；
3. required check 是否全部出现；
4. excluded check 是否没有改变当前判定；
5. verdict 是否符合 profile；
6. 结果是否新鲜；
7. 独立性模式是否满足；
8. 结果是否被重复或越权使用。

SOP Control 不需要理解每个业务 finding 的完整文本，但不能只接受一段自由文本理由作为放行依据。

---

## 12. 测试要求

### 12.1 解析测试

至少覆盖：

- 单一 required check；
- required 与 excluded 同时存在；
- 同一检查在不同维度采用不同模式；
- 临时 profile 只作用于当前任务；
- profile 和基础 Rule 冲突；
- baseline mode 缺失或非法；
- 修正预算缺失、为负或超出系统上限；
- 同一 profile 归一化后生成稳定 digest。

### 12.2 行为测试

至少验证：

1. 只要求一个检查时，不会自动增加其他检查；
2. excluded finding 不会阻断；
3. authoritative 不会自动升级为 verify；
4. warn 不会自动升级为 block；
5. not_run 不能满足 required check；
6. tolerated 偏差不会触发修正；
7. 达到停止条件后不会重复审计；
8. 相同输入和策略只产生一个有效结果；
9. Rule revision 改变会使旧结果失效；
10. 换执行器不会放宽当前计划。

### 12.3 反事实测试

对控制协议做受控变异：

- 删除一个 required check 的结果；
- 把 excluded 项伪装成 required；
- 修改 baseline mode；
- 修改 max_rounds；
- 使用旧 plan digest；
- 重放已消费的结果；
- 用自由文本理由替代结构化结果；
- 伪造 producer 或独立性状态。

预期结果：

- 缺失、过期、冲突或伪造的结果被拒绝；
- 合法的宽松 profile 仍能正常通过；
- 控制器不会擅自扩大审查范围。

### 12.4 成本测试

对同一输入、同一 profile 和同一执行器重复执行，验证：

- 不会产生重复高成本审计；
- 不会出现无限修正；
- 阶段授权不会退化成每动作双调用；
- profile 变化只重检受影响维度；
- 停止条件生效后不会继续调用。

---

## 13. 实施顺序

### P0：动态策略模型

- 新增 Dynamic Control Profile；
- 支持 required、excluded、mode、baseline、tolerance、repair、budget；
- 生成并冻结 Effective Control Plan；
- 将 plan digest 绑定到任务。

### P0：状态门可信

- 将单一审计布尔值改为结构化结果；
- 阻止被控执行器用自由文本理由自我放行；
- 区分 not_run、unknown、out_of_scope、warn 和 block；
- 按 profile 计算 accept、render 等状态迁移。

### P1：防发散和防重复

- 增加基线模式；
- 增加显式排除范围；
- 增加修正预算和停止条件；
- 增加审计幂等键；
- 增加受影响维度重检；
- 增加 profile 变更的影响分析。

### P1：成本优化

- 能力授权改为阶段级或运行级；
- 结果缓存；
- 本地完成范围和冲突解析；
- 仅对必要维度调用高成本检查。

### P2：验证与度量

- profile fixtures；
- 过严、过松、过审、重复审计的金标准；
- 计划 digest 一致性测试；
- 跨执行器结果协议测试；
- doctor 输出当前 profile、风险和成本。

---

## 14. 不应采取的方向

以下做法不符合本方案：

1. 把所有业务语义算法搬入 SOP Control；
2. 让 LLM 在每次调用时重新解释动态要求；
3. 只设计一个全局 strict 或 lenient 开关；
4. 不设置 excluded 范围，只要求模型“尽量检查”；
5. 把 finding、repair 和 verdict 合并为一个布尔值；
6. 用增加人工审批或多个 Agent 代替协议设计；
7. 让模型自行改变 baseline mode；
8. 让模型把合理偏差升级为必须修正；
9. 让模型在通过后自行开启下一轮审查；
10. 让任务级临时偏好自动变成项目永久规则；
11. 用更多 ticket、receipt 和 hash 记录掩盖入口和状态门没有闭合；
12. 让 SOP Control 接管外部系统的业务文件写入。

---

## 15. 最终验收标准

动态规则能力达到目标，需要同时满足：

1. 用户可以指定本次必须审查的方面；
2. 用户可以指定本次明确不审查的方面；
3. 不同维度可以有不同严格程度；
4. 系统可以区分接受基线与验证基线；
5. 基线模式不会被 LLM 自行改变；
6. 审查结论和修正动作彼此独立；
7. 合理偏差不会触发无意义重写；
8. 审查通过后不会自动循环；
9. 相同输入和策略不会重复消耗审查调用；
10. 动态配置只作用于声明的任务或运行；
11. 规则变化会产生新 revision；
12. 旧结果不会静默用于新策略；
13. 缺失、过期或自报结果不能被当成通过；
14. SOP Control 只控制协议、范围、状态和证据引用；
15. 任意执行器只能在冻结的 Effective Control Plan 内行动。

## 16. 结论

SOP Control 对复杂动态场景的增强，不是把自己变成业务规则管理器，也不是替代外部系统完成语义审查，而是增加一层轻量、可冻结、可验证的动态控制契约。

它严格控制：

    审查什么
    不审查什么
    基线如何使用
    什么算问题
    什么问题才修
    最多修几次
    什么时候必须停止

业务系统负责执行具体检查，LLM 负责在允许范围内完成判断，SOP Control 负责确保 LLM 不能临场扩大目标、改变标准、质疑已接受的基线或重复消耗资源。

最终目标不是让 LLM 更谨慎，也不是让 LLM 更宽松，而是让它严格服从用户本次明确选择的谨慎程度和宽松程度。
