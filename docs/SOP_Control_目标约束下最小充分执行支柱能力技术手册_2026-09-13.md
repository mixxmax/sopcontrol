# SOP Control 目标约束下最小充分执行支柱能力技术手册

## ——先保证目标与输出充分，再选择最自然、最经济的执行逻辑

- 版本：v1.1
- 日期：2026-09-13
- 能力中文名：目标约束下的最小充分执行
- 能力英文名：Goal-Constrained Minimum Sufficient Execution
- 简称：MSE
- 定位：SOP Control 支柱能力之一
- 执行范围：SOP Control 通用能力及其产品接入协议
- 不在范围：替 JobsFlow 或其他业务产品实现业务语义判断
- 面向执行者：第一次接触 SOP Control 的外部模型

---

## 0. 给外部模型的第一条指令

你要实现的不是一个固定工作流引擎，也不是把“先筛选再评分”写死在 SOP Control 中。

你要实现的是一项通用控制能力：

> 先证明执行计划能够通过正式管线产生用户要求的质量与结果，再在所有充分计划中，只允许目标一致、处理范围更小、成本更低、风险更低、无无关动作的计划。用户纠正目标、质量、范围或顺序后，旧计划必须立即失效；只有真实依赖或明确的新目标才能使更宽、更贵或相反顺序成为合法计划。

MSE 的固定优先级是：

1. 目标解释正确；
2. 输出质量充分；
3. 使用能够产生该质量的正式管线；
4. Gate 与当前任务目标集合使用同一作用域；
5. 在满足以上条件的计划中最小化范围、成本和风险；
6. 用户纠正后停止旧计划；
7. 目标已满足后停止额外工作。

开始修改前必须：

1. 阅读 AGENTS.md、DESIGN.md、PLAYBOOK.md、SKILL.md、pyproject.toml；
2. 阅读当前 action、task、profile、bridge、ticket、surface inventory 和 control result 实现；
3. 建立当前 Git 和测试基线；
4. 先添加失败测试，再实现；
5. 不直接修改 .sopcontrol 权威文件；
6. 不把 JobsFlow 业务语义写进 SOP Control；
7. 不增加每一步人工审批；
8. 不启动额外大模型来判断是否“自然”；
9. 不以关闭 enforce、降低测试或放宽断言的方式完成；
10. 最后按照本手册第 27 节提交证据报告。

本手册本身不授权 commit、push 或发布。只有任务发起者另行明确授权时才执行。

---

## 1. 为什么它必须成为支柱能力

SOP Control 已经形成或正在形成三项主要能力：

1. 随产品生长而生长的规则空间；
2. 低接入成本和完整执行表面覆盖；
3. 动态 SOP 的编译与执行。

如果缺少 MSE，这三项能力仍然可能出现一个共同失败：

- 所有入口都接入了；
- 每个动作都有 ticket；
- 每一步都留下 receipt；
- required check 也执行了；
- 但模型选择了一条明显更慢、更贵、范围更大的路径。

例如：

    任务目标：
    检索过去一周的目标职位，并对尚未入表的岗位评分。

    计划 A：
    检索
    -> 时间和职位筛选
    -> 排除已入表岗位
    -> 只对剩余岗位评分

    计划 B：
    检索
    -> 对全部岗位评分
    -> 时间和职位筛选
    -> 排除已入表岗位

如果评分结果不参与前面的筛选，A 与 B 可以产生相同最终结果，但 A 处理对象更少，成本更低，风险更小。B 是一条被 A 支配的计划。

没有 MSE 时，SOP Control 只能证明 B 的每一步都经过控制，却不能证明为什么 B 不应该被执行。

MSE 的作用就是补上：

> “动作合规”与“整体执行逻辑合乎目标”之间的空白。

---

## 2. 支柱能力之间的关系

SOP Control 的最终产品可以按四个支柱理解。

### 支柱一：可生长规则空间

负责：

- 发现产品变化；
- 发现新能力和新入口；
- 继承已有规则；
- 生成规则候选；
- 规则版本化、接受、撤销和回滚。

### 支柱二：低摩擦完整接入

负责：

- 一次安装或简单引导；
- 中途接入；
- CLI、wrapper、harness、plugin、subprocess 覆盖；
- 统一 side-effect 分类和 admission；
- 安全 attach/detach/rollback。

### 支柱三：动态 SOP

负责：

- Base、Task、Run、Actor 多层规则；
- required/excluded checks；
- tolerance；
- repair；
- stop；
- budget；
- scope；
- baseline；
- 有效计划和稳定 digest。

### 支柱四：MSE

负责：

- 明确任务真正需要的输出；
- 区分输出质量与 preview/commit 等副作用模式；
- 验证计划是否使用能够产生必需工件的正式管线；
- 明确每个操作对数据范围和属性的作用；
- 识别仍可提前执行的低成本范围收缩；
- 阻止昂贵动作处理目标集合之外的数据；
- 阻止 scoped task 被无关的 run 级欠账扩大；
- 阻止与目标无关的动作；
- 优先复用有效结果；
- 用户纠正后使旧计划和旧 ticket 失效；
- 阻止没有新证据的重复失败策略；
- 在宣布产品缺口前要求完成入口和计划自检；
- 达到目标后停止；
- 接受由真实依赖或明确目标变化导致的非默认顺序。

四个支柱组合后形成：

    产品变化
      -> 规则空间发现新操作
      -> 产品声明或确认操作性质
      -> 动态 SOP 编译当前任务约束
      -> MSE 选择/验证最小充分计划
      -> 完整接入层控制实际执行
      -> receipt 更新状态和集合沿袭
      -> 后续变化继续进入规则空间

---

## 3. MSE 的准确语义

### 3.1 最小不等于步骤最少

MSE 不是简单选择步骤最少的计划。

一个计划必须先满足：

1. 用户目标；
2. 必需业务前置条件；
3. 安全和合规规则；
4. 数据完整性；
5. required checks；
6. 产品声明的正确性约束。

只有在以上条件全部满足的计划之间，才比较：

- 处理对象数量；
- 计算成本；
- 外部调用次数；
- token；
- 时间；
- side effect；
- 风险；
- 可恢复性；
- 无关动作数量。

不得为了省成本跳过必需检查。

### 3.2 充分的含义

计划必须产生用户真正需要的输出，并包含产生该输出不可缺少的步骤。

如果输出要求：

- 过去一周；
- 某职位；
- 未入表；
- 有评分；

那么最终输出必须同时满足四项。不能因为最小化而漏掉其中一项。

### 3.3 目标约束的含义

成本最小化必须相对于当前目标。

如果用户改变目标为：

- 给所有检索到的岗位评分；
- 未入表岗位单独展示；

那么评分全部岗位就是目标的一部分，不再是多余工作。

### 3.4 默认的含义

默认不是永恒规则。

默认表示：

- 用户没有明确指定相反流程；
- 业务依赖没有要求相反顺序；
- 产品没有声明另一个合法策略；
- 当前任务没有额外目标；
- 没有合规、缓存或批处理原因要求扩大范围。

只有在这些条件成立时，采用最小充分路径。

### 3.5 充分性优先于经济性

一个更便宜的计划，如果不能产生用户要求的结果质量，就不是最小充分计划。

例如“预览检索”可能有两种错误解释：

    解释一：
    只展示门户返回的原始清单。

    解释二：
    运行正式检索、筛选、评分和语义管线，
    但不执行最终入表。

如果产品已经声明“预览只改变最终副作用，不降低数据质量”，解释一即使更便宜，也必须在执行前被判定为 insufficient_plan。

因此 MSE 必须同时检查：

- required outputs；
- required artifacts；
- required quality level；
- required checks；
- canonical production route；
- side-effect mode；
- completion definition。

### 3.6 质量模式与副作用模式正交

不得把 preview、dry-run、simulation 自动解释为低质量模式。

建议分别建模：

    quality_mode:
      raw | normalized | scored | validated | production_equivalent

    side_effect_mode:
      preview | propose | commit

同一个 quality_mode 可以搭配不同 side_effect_mode。例如：

    production_equivalent + preview
    production_equivalent + commit

二者走同一前置处理管线，只在最终 sink 或 write 阶段分叉。

### 3.7 合法动作不等于合法计划

以下动作可以全部单独合法：

- search；
- scan；
- score；
- semantic check；
- push proposal。

但如果它们：

- 使用了错误入口；
- 缺少必需工件；
- 处理了目标之外的数据；
- 在用户纠正后继续旧计划；
- 被无关全局 Gate 强制扩大；
- 重复执行没有进展的高成本策略；

整体计划仍然必须被阻断。

MSE 的控制对象是“动作组成的计划及其数据沿袭”，不是只检查单个动作。

---

## 4. 形式化判定

设：

- G 为任务目标；
- C 为强制约束集合；
- P 为候选执行计划；
- Result(P) 为计划输出；
- Cost(P) 为成本向量；
- Risk(P) 为风险向量；
- Scope(P) 为处理范围；
- Effects(P) 为副作用；
- Required(P) 为所有必要前置和检查是否满足。
- Quality(P) 为计划能够产生的输出质量；
- Route(P) 为实际采用的生产入口；
- GateScope(P) 为完成门实际检查的对象集合；
- TargetScope(G) 为当前目标集合；
- Revision(P) 为计划绑定的用户目标和纠正版本。

计划 P 合法的基本条件：

    Result(P) satisfies G
    Quality(P) satisfies required output quality
    Route(P) can produce all required artifacts
    GateScope(P) is congruent with TargetScope(G)
    Revision(P) is current
    P satisfies C
    Required(P) = true

若存在另一个计划 Q：

    Result(Q) is equivalent to Result(P)
    Q satisfies C
    Required(Q) = true
    Cost(Q) <= Cost(P)
    Risk(Q) <= Risk(P)
    Scope(Q) is not broader than Scope(P)
    Effects(Q) are not greater than Effects(P)

并且至少有一项严格更优，则 P 被 Q 支配。

默认情况下，被支配计划不得进入昂贵或高影响执行步骤。

实际实现不需要搜索所有可能计划。第一版只实现一组可证明安全的局部支配规则。

如果计划不满足结果、质量、正式入口或 Gate 作用域要求，应先返回 insufficient、route_mismatch 或 gate_scope_mismatch；不能进入成本比较，也不能因为它更便宜而放行。

---

## 5. 第一版必须支持的局部支配规则

### 5.1 谓词下推

如果筛选谓词不依赖某个昂贵操作的输出，则筛选应先执行。

    Filter(Score(S))  ->  Score(Filter(S))

成立条件：

- Filter 不读取 score；
- score 不改变 Filter 所需字段；
- 两种顺序最终结果等价；
- score 成本高于 Filter。

### 5.2 排除和去重前置

如果某些对象已经处理过、已经入表或重复，则应在昂贵操作前排除。

    Score(AntiJoin(S, Existing))
    优于
    AntiJoin(Score(S), Existing)

成立条件：

- 是否 existing 与 score 无关；
- 已存在对象不需要重新评分；
- 没有显式 refresh_all 目标。

### 5.3 投影下推

如果后续步骤只需要少量字段，不应提前加载或生成所有字段。

    Fetch(required_fields)
    优于
    Fetch(all_fields)

前提是业务产品能够声明 required fields。

### 5.4 缓存优先

有效、未过期、与目标和输入 digest 一致的结果应在重新计算前复用。

不得复用：

- 输入变化；
- 规则变化；
- baseline 变化；
- operator version 变化；
- 用户明确要求刷新；
- 缓存缺少必需字段；
- 缓存来源不可证明。

### 5.5 批处理优先

同一操作支持批处理且批处理不会改变语义时，不应对每个对象重复初始化相同控制或网络会话。

### 5.6 达标即停

当目标输出已经满足，且没有 required check 或 postcondition 未完成时，应停止无关操作。

### 5.7 不扩大下游范围

高成本操作的输入集合不得大于满足目标所需的最小候选集合，除非：

- 扩大范围属于目标；
- 依赖关系要求；
- 用户明确要求；
- 产品声明的合规规则要求；
- 有可验证的缓存预计算目标。

### 5.8 必需安全步骤不可优化掉

以下步骤即使增加成本也不能删除：

- required check；
- 安全校验；
- 权限检查；
- 数据完整性检查；
- 合规步骤；
- 必需的用户确认；
- rollback 准备；
- 产品声明的不可省略步骤。

---

## 6. “反逻辑”的正确处理

不要把所有不同顺序都叫作例外。

### 6.1 真实依赖导致的顺序

例如：

    检索
    -> 全部评分
    -> 保留评分大于 80 的岗位
    -> 排除已入表

因为筛选条件依赖 score，评分必须先执行。这是正常计划，不是例外。

### 6.2 用户改变目标

例如：

    给过去一周所有目标岗位评分，
    并额外标出未入表岗位。

此时 required output 包含所有岗位的 score。评分全部对象不再是多余工作。

### 6.3 明确的次级目标

例如：

- 为未来任务预计算缓存；
- 做全量评分基准测试；
- 比较入表和未入表岗位；
- 校验评分模型一致性。

次级目标必须进入 GoalContract，不能只存在于模型自由文本中。

### 6.4 无依据的扩张

如果：

- 用户目标未变化；
- 筛选不依赖 score；
- 没有次级目标；
- 没有合规原因；
- 没有缓存预计算授权；

模型仍然选择 score(all)，则属于无依据扩张，应被 MSE 阻断。

---

## 7. 产品与 SOP Control 的职责边界

### 7.1 产品负责

适用产品负责声明：

- 业务实体；
- 可用操作；
- 操作输入和输出；
- 操作产生哪些字段；
- 操作需要哪些字段；
- 操作会缩小、保持还是扩大集合；
- 操作大致成本；
- 操作是否有副作用；
- 哪些业务谓词依赖哪些字段；
- 当前用户请求的目标；
- 必需业务检查；
- 允许的刷新、预计算或特殊目标。

产品不需要把自己的完整业务实现复制进 SOP Control。

### 7.2 SOP Control 负责

SOP Control 负责：

- 验证产品声明的契约；
- 编译 GoalContract 和 OperatorContract；
- 验证模型提出的计划；
- 识别局部支配关系；
- 冻结有效计划；
- 在昂贵动作前检查前置状态；
- 检查实际输入集合是否符合计划；
- 绑定 task、run、plan、operator、lineage；
- 防止临时扩大目标；
- 管理明确的 override；
- 记录最小充分性决策；
- 在产品能力变化时生成规则/契约候选。

### 7.3 SOP Control 不负责

SOP Control 不负责：

- 判断某岗位是否真的适合用户；
- 实现职位筛选算法；
- 实现数据库反连接；
- 给岗位评分；
- 判断材料内容是否真实；
- 发明业务谓词；
- 猜测 score 是否应该参与业务筛选；
- 用另一个 LLM 代替产品契约。

如果产品没有提供足够信息，SOP Control 应返回 unproven，而不是假装理解业务。

---

## 8. 总体架构

建议新增四个核心模块，并接入现有控制链。

### 8.1 goal_contract.py

职责：

- 定义任务目标；
- 定义目标集合；
- 定义输出字段；
- 定义次级目标；
- 定义范围上限；
- 定义完成条件；
- 规范化和 digest。

### 8.2 operator_contract.py

职责：

- 定义操作性质；
- 定义输入输出；
- 定义谓词和字段依赖；
- 定义集合变化；
- 定义成本；
- 定义副作用；
- 定义缓存和幂等性；
- 版本化。

### 8.3 execution_logic.py

职责：

- 验证候选计划；
- 构建依赖图；
- 应用局部支配规则；
- 计算 plan verdict；
- 生成可操作的 next_action；
- 不做 I/O；
- 不调用模型。

### 8.4 lineage.py

职责：

- 保存集合和产物沿袭摘要；
- 绑定 input/output digest；
- 记录谓词已满足证明；
- 记录 cardinality；
- 防止陈旧集合被复用；
- 不保存业务正文。

### 8.5 与现有模块的接点

需要检查并按最小范围修改：

- sopcontrol/control_profile.py
  - 增加 execution policy；
  - 保持多层只收紧合成；
  - 将 MSE 配置纳入 plan digest。

- sopcontrol/task.py
  - 绑定 GoalContract digest；
  - 绑定初始 ExecutionPlan digest；
  - 状态转换中校验计划更新。

- sopcontrol/action_model.py
  - ActionEnvelope 增加 step、operator、input lineage 等非敏感字段。

- sopcontrol/action_plane.py
  - 在昂贵或高影响动作前调用 MSE 纯判定；
  - 普通低成本观察动作避免额外 ticket。

- sopcontrol/bridge.py
  - 将 plan_step_id、operator_id、lineage digest 进入 canonical operation；
  - receipt 返回实际 input/output lineage 摘要。

- sopcontrol/tickets.py
  - ticket 绑定 MSE plan digest 和 step id；
  - 计划改变后旧 ticket 失效。

- sopcontrol/control_result.py
  - 检查 required postcondition；
  - 检查目标完成和 stop；
  - 不让结果自由文本代替 lineage 证据。

- sopcontrol/surface_inventory.py
  - 新 surface 发现后生成 OperatorContract 候选；
  - 不能自动编造业务依赖。

- sopcontrol/cli.py
  - 提供 contract、plan、explain、check 和 cost 命令；
  - 命令名称以仓库现有风格为准。

---

## 9. GoalContract 数据模型

建议模型字段如下。

    GoalContract:
      schema_version: string
      goal_id: string
      revision: integer
      entity_type: string
      intent:
        normalized_statement: string
        correction_revision: integer
        authoritative_source: string
      target_set:
        source_ref: string
        predicates: list[PredicateRequirement]
        maximum_scope: optional string
      required_outputs: list[OutputRequirement]
      required_artifacts: list[ArtifactRequirement]
      quality:
        required_level: string
        preview_same_quality_as_commit: boolean
        forbidden_downgrades: list[string]
      execution_mode:
        side_effect_mode: preview | propose | commit
        canonical_route: optional string
        allowed_routes: list[string]
      secondary_goals: list[SecondaryGoal]
      completion:
        minimum_count: optional integer
        maximum_count: optional integer
        require_all_matching: boolean
      refresh_policy:
        allow_recompute: boolean
        maximum_age: optional duration
      cost_budget:
        max_expensive_items: optional integer
        max_external_calls: optional integer
        max_tokens: optional integer
        max_duration_ms: optional integer
      created_by: string
      source_ref: string
      digest: string

### 9.1 PredicateRequirement

    PredicateRequirement:
      predicate_id: string
      parameters: object
      required_fields: list[string]
      evidence_type: string
      must_hold_before: list[string]

例如：

    predicate_id: published_within
    parameters:
      days: 7

    predicate_id: title_matches
    parameters:
      title: product_manager

    predicate_id: not_in_table
    parameters:
      table_ref: jobs_main

### 9.2 OutputRequirement

    OutputRequirement:
      field_id: string
      required_for: string
      freshness: optional duration
      produced_by: optional operator_id
      quality_level: optional string
      required_route: optional string

例如：

    field_id: score
    required_for: target_set_only
    produced_by: jobs.score
    quality_level: scored
    required_route: jobsflow.production_pipeline

### 9.3 ArtifactRequirement

    ArtifactRequirement:
      artifact_id: string
      schema_ref: string
      required_fields: list[string]
      produced_by: list[operator_id]
      minimum_quality: string
      required_for_completion: boolean

例如预览也必须具备：

    artifact_id: scored_job_preview
    required_fields:
      - initial_score
      - lane
      - semantic_status
    minimum_quality: production_equivalent
    required_for_completion: true

### 9.4 GoalContract 规则

- goal_id 和 revision 必须稳定；
- digest 包含所有会影响结果和成本的字段；
- correction_revision 必须在用户明确纠正目标、范围、质量或顺序时递增；
- required_artifacts 缺失时不得 deliver；
- preview_same_quality_as_commit=true 时，preview 不能走 raw-only route；
- side_effect_mode 变化不能隐式改变 required quality；
- canonical_route 存在时，替代入口必须证明输出等价；
- 模型不得在运行中增加 secondary goal；
- 用户改变目标时产生新 revision；
- 目标变化必须重新编译计划；
- 旧 ticket 和旧 plan 不得继续使用；
- 自由文本只能作为说明，不能代替结构化字段。

---

## 10. OperatorContract 数据模型

建议模型字段如下。

    OperatorContract:
      schema_version: string
      operator_id: string
      version: string
      product_id: string
      action: string
      phase: string
      role: source | reducer | anti_join | deduplicator | projector |
            enricher | scorer | aggregator | validator | sink
      consumes:
        entity_type: string
        required_fields: list[string]
        required_predicates: list[string]
      produces:
        entity_type: string
        fields: list[string]
        predicates: list[string]
      cardinality:
        effect: reduce | preserve | expand | unknown
        estimate: optional number
      dependencies:
        output_fields_used_by_predicates: map
        must_run_after: list[operator_id]
        must_run_before: list[operator_id]
      cost:
        class: negligible | low | medium | high | external
        unit: item | batch | run
        estimate: optional number
      side_effect:
        class: none | local_write | network | external_write |
               database_write | irreversible
      execution:
        deterministic: boolean
        idempotent: boolean
        cacheable: boolean
        batchable: boolean
      evidence:
        adapter_ref: string
        schema_ref: string
      digest: string

### 10.1 操作角色

- source：产生初始集合；
- reducer：根据谓词缩小集合；
- anti_join：排除另一个集合中的对象；
- deduplicator：删除重复对象；
- projector：保留必要字段；
- enricher：增加属性；
- scorer：高成本 enrich 的常见形式；
- aggregator：聚合多个对象；
- validator：验证但不改变业务集合；
- sink：写入、展示、发布或发送。

### 10.2 未知字段

如果 operator 的 cardinality、dependency 或 side effect 不可证明：

- 标记 unknown；
- observe 模式记录；
- warn 模式提示；
- block 模式下，在高成本或高影响动作前阻断；
- 不自动推断为安全；
- 生成 OperatorContract candidate。

---

## 11. SetLineage 数据模型

SOP Control 不保存业务数据，只保存足够证明范围和沿袭的摘要。

    SetLineage:
      schema_version: string
      set_id: string
      entity_type: string
      producer_step_id: string
      parent_set_ids: list[string]
      predicates_proven: list[PredicateProof]
      fields_available: list[string]
      cardinality: integer
      content_digest: string
      source_snapshot_digest: string
      operator_digest: string
      goal_digest: string
      plan_digest: string
      created_at: datetime
      expires_at: optional datetime

### 11.1 PredicateProof

    PredicateProof:
      predicate_id: string
      parameters_digest: string
      producer_operator_id: string
      evidence_digest: string
      source_snapshot_digest: string

### 11.2 沿袭不变量

- output 的 parent_set_ids 必须来自当前 plan；
- predicates_proven 只能由声明能够产生该谓词的 operator 添加；
- scorer 不能自行声明 not_in_table；
- content_digest 变化后旧 ticket 失效；
- source snapshot 变化后依赖它的 anti_join 证明失效；
- cardinality 不能为负；
- reducer 输出 cardinality 默认不得大于输入；
- anti_join 输出 cardinality 不得大于左输入；
- enricher 默认保持 cardinality；
- expand 操作必须有明确目标或规则；
- lineage 不能只靠模型自由文本创建。

---

## 12. ExecutionPlan 数据模型

    ExecutionPlan:
      schema_version: string
      plan_id: string
      revision: integer
      task_id: string
      goal_digest: string
      effective_profile_digest: string
      operator_contract_digests: map
      steps: list[PlanStep]
      required_postconditions: list[string]
      estimated_cost: CostVector
      logic_verdict: pass | warn | block | unproven
      reasons: list[string]
      alternatives: list[PlanAlternative]
      digest: string

    PlanStep:
      step_id: string
      operator_id: string
      input_set_refs: list[string]
      output_set_ref: string
      preconditions: list[string]
      postconditions: list[string]
      allowed_next: list[string]
      expected_cardinality: optional range
      required: boolean
      expensive: boolean
      side_effect: string

### 12.1 Plan digest

必须包含：

- goal digest；
- effective profile digest；
- operator versions/digests；
- step order；
- dependencies；
- input/output refs；
- cost policy；
- override；
- required postconditions。

不得包含：

- secret；
- ticket id；
- 临时 handoff 路径；
- wrapper 绝对路径；
- 不稳定当前时间；
- 模型自由文本。

---

## 13. MSE 判定器

建议提供纯函数：

    evaluate_execution_plan(
        goal,
        operators,
        plan,
        policy,
        known_lineage
    ) -> LogicEvaluation

返回：

    LogicEvaluation:
      outcome: pass | warn | block | unproven
      reasons: list[string]
      output_gaps: list[string]
      artifact_gaps: list[string]
      quality_downgrades: list[string]
      route_mismatches: list[string]
      gate_scope_mismatches: list[string]
      stale_correction_revision: boolean
      repeated_failed_strategy: boolean
      dominated_steps: list[string]
      pending_reducers: list[string]
      unnecessary_steps: list[string]
      scope_violations: list[string]
      estimated_savings: CostVector
      next_action: string
      normalized_plan_digest: string

### 13.1 判定顺序

固定优先级：

1. schema 和身份错误；
2. 目标或 correction revision 过期；
3. 缺少目标、operator 或 required artifact；
4. 输出质量不足或 preview 非法降级；
5. 未使用可产生目标质量的正式管线；
6. Gate 作用域与任务目标集合不一致；
7. 不满足强制规则；
8. 依赖图不成立或目标无法完成；
9. scope 扩大；
10. 用户纠正后继续旧计划；
11. 没有新证据的重复失败策略；
12. 存在可证明的支配改写；
13. 成本预算；
14. 警告；
15. pass。

### 13.2 不确定性

unproven 与 block 必须区分：

- block：已证明违反规则；
- unproven：缺少足够契约，不能证明计划合理；
- warn：存在可能浪费，但影响低或当前模式不阻断；
- pass：计划满足目标且没有可证明的支配问题。

高成本、高影响动作在 enforce 模式下遇到 unproven 应停止。低成本探索动作可以继续 observe，但不能把观察结果当成后续高成本动作的有效前置证明。

以下 reason_code 必须区分：

- insufficient_output；
- missing_required_artifact；
- quality_downgrade；
- canonical_route_mismatch；
- gate_scope_mismatch；
- stale_plan_after_correction；
- repeated_failed_strategy；
- product_gap_unproven；
- dominated_expensive_step；
- scope_expansion。

---

## 14. 局部优化与依赖图

### 14.1 图结构

建立有向图：

- 节点：PlanStep；
- 边：数据依赖、字段依赖、谓词依赖、显式顺序依赖；
- 根：source；
- 终点：required outputs 和 sink。

### 14.2 无关动作检测

如果一个 step 的输出：

- 不进入任何 required output；
- 不满足任何 required predicate；
- 不是 required check；
- 不影响任何后续必需步骤；
- 不属于明确 secondary goal；

则该 step 与当前目标无关，默认拒绝或删除。

### 14.3 安全交换条件

两个相邻步骤 A、B 只有在以下条件满足时才能交换：

- B 不需要 A 产生的字段；
- A 不需要 B 产生的字段；
- A/B 的副作用顺序不受业务或合规约束；
- 交换不会改变最终集合；
- 交换不会破坏 required check；
- 交换不会扩大 scope；
- operator contract 明确支持。

不能只根据名字包含 filter 或 score 就重新排序。

### 14.4 循环

第一版可以：

- 默认拒绝无界循环；
- 允许有 max_iterations 的循环；
- repair 和 retry 使用现有 budget；
- 每轮必须证明状态前进或输入变化；
- 同输入、同 operator、同输出 digest 的重复循环立即停止；
- 循环不能绕过 cost budget。

---

## 15. 动态 SOP 中的 MSE 配置

建议在 ControlProfile 中增加 execution_policy。

    execution_policy:
      mode: observe | warn | block
      require_output_sufficiency: true
      preserve_quality_across_preview: true
      require_canonical_route: true
      require_gate_scope_congruence: true
      require_minimal_scope: true
      push_down_reducers: true
      deduplicate_before_expensive: true
      prefer_valid_cache: true
      stop_when_goal_satisfied: true
      reject_unrelated_steps: true
      invalidate_on_user_correction: true
      stop_repeated_failed_strategy: true
      require_gap_self_check: true
      allow_speculative_work: false
      unknown_expensive_action: block
      max_scope_expansion_ratio: 1.0
      max_expensive_items: optional integer
      max_external_calls: optional integer
      exception_policy: explicit_goal_revision

### 15.1 多层合成

Base、Task、Run、Actor 只能收紧：

- observe -> warn -> block；
- require_output_sufficiency、preserve_quality_across_preview、
  require_canonical_route、require_gate_scope_congruence 只能从 false 收紧为 true；
- false -> true 的强制项可以收紧；
- true 不得降为 false；
- max_scope_expansion_ratio 只能降低；
- max_expensive_items 只能降低；
- max_external_calls 只能降低；
- allow_speculative_work 从 true 改 false 属于收紧；
- unknown_expensive_action 只能向严格变化；
- invalidate_on_user_correction、stop_repeated_failed_strategy、
  require_gap_self_check 只能从 false 收紧为 true；
- absent 表示继承；
- explicit default 与 absent 必须区分。

MSE 配置进入 effective plan digest。

### 15.2 用户临时要求

用户本次明确要求扩大目标时：

- 修改 Task 层 GoalContract；
- 生成新 goal revision；
- 重新编译 plan；
- 新 plan digest；
- 旧 ticket 失效；
- 不把一次性要求自动升级为 Base 规则。

---

## 16. 运行时 admission

### 16.1 哪些步骤需要检查

不必给每个纯函数增加 ticket。

建议：

- source/reducer/projector：低成本、无副作用时只做轻量 lineage 检查；
- scorer/enricher：高成本时做 MSE precondition；
- network/browser/database/write/sink：做 MSE + 现有 capability admission；
- validator：按现有 required check 机制；
- pure cached read：验证 digest 后可复用。

### 16.2 昂贵动作前检查

执行 scorer/enricher 前检查：

- 当前 goal digest；
- 当前 plan digest；
- 当前 step id；
- operator digest；
- input set digest；
- input cardinality；
- required predicates 是否已证明；
- 是否存在尚未执行且独立的 reducer/anti_join/dedup；
- cost budget；
- ticket 和 operation binding。

如果违反：

    decision: block
    reason_code: scope_not_minimized
    pending_steps:
      - filter_by_title
      - exclude_existing
    next_action: 先生成符合条件且未入表集合，再执行 score
    estimated_avoided_items: 128

### 16.3 动作执行后检查

产品执行完成后返回：

- output set digest；
- cardinality；
- produced fields；
- produced predicate proofs；
- operator version；
- source snapshot；
- execution cost；
- actual side effect。

SOP Control 验证后更新 lineage。

### 16.4 输出充分性和正式管线路由

在任何被用户视为交付、预览或候选输出的动作前，检查：

- required outputs 是否存在；
- required artifacts 是否存在；
- quality level 是否达到 GoalContract；
- artifact 是否由允许的 operator 产生；
- 实际 route 是否为 canonical route 或已证明等价；
- preview 是否只关闭最终副作用，而没有跳过评分、归一化或 required check。

缺少评分、lane、语义状态等必需工件时，不得把“原始列表”作为有效预览，也不得把缺失工件当成可接受终态。

### 16.5 Gate 作用域一致性

每个完成门必须声明 gate_scope：

- set_id；
- target predicates；
- source snapshot；
- task_id；
- run_id；
- plan digest；
-是否要求全局完成。

执行前必须比较：

    gate_scope == task_target_scope

或者证明：

    gate_scope is a declared required superset of task_target_scope

如果 scoped task 只处理某个子集，而 Gate 因同一 run 中无关对象的 pending 阻断，应返回 gate_scope_mismatch，不能自动扩大任务去清理无关对象。

只有产品明确声明“全局 run 完成是该子任务的必要业务不变量”时，run 级 Gate 才可以阻断子集任务。

如果产品没有 scoped gate，SOP Control 应报告 adapter capability gap，并在昂贵清理动作前停止；不得自行绕过 Gate，也不得要求模型默认清理全部无关欠账。

### 16.6 用户纠正与计划失效

以下用户表达应视为权威纠正事件：

- 目标对象变化；
- 输出质量变化；
- preview/commit 语义澄清；
- 处理范围变化；
- 默认顺序变化；
- 明确否定当前计划；
- 指出某个中间状态不应被视为正常终态。

收到纠正后：

1. correction_revision 递增；
2. 旧 ExecutionPlan 标记 stale；
3. 旧 ticket、next_action 和未执行 step 失效；
4. 重新编译 GoalContract 和计划；
5. 继续旧计划的动作返回 stale_plan_after_correction；
6. 一次性纠正只作用于 Task 层，除非另有规则吸收流程。

不得因为模型已经投入较多时间，就继续一个已被用户否定的计划。

### 16.7 重复失败策略和停滞检测

为高成本步骤计算 strategy fingerprint，至少包含：

- goal digest；
- correction revision；
- 计划结构；
- input scope；
- operator sequence；
- query/window 参数；
- previous outcome；
- 实际新增有效对象数；
-执行成本。

若满足：

    目标未变化
    + 计划近似相同
    + 上次没有实质推进
    + 用户已否定或要求收窄
    + 没有新证据

则返回 repeated_failed_strategy，在再次扫描、评分或清理前阻断。

只有输入、依赖、目标、产品状态或用户授权发生实质变化时才允许重试。

### 16.8 产品缺口归因前自检

在报告 product_gap 或要求修改产品前，必须依次证明：

1. 使用了正式入口；
2. GoalContract 和输出质量定义正确；
3. 输入满足入口契约；
4. 使用了最小充分范围；
5. 失败可以用最小 fixture 复现；
6. 不存在已有的正确 route；
7. Gate 作用域确实无法表达当前任务；
8. 不是模型误解、旧计划或陈旧状态造成。

未完成上述证明时，只能报告 execution_path_unproven 或 plan_mismatch，不能把问题归因于产品。

---

## 17. Receipt 和 ticket 扩展

### 17.1 ticket 绑定

ticket 至少增加或确认绑定：

- goal_digest；
- correction_revision；
- execution_plan_digest；
- plan_step_id；
- operator_id；
- operator_digest；
- input_set_digest；
- input_cardinality；
- expected_side_effect；
- required_quality；
- route_digest；
- gate_scope_digest；
- strategy_fingerprint；
- task_id；
- run_id；
- phase；
- operation_id。

输入集合、目标或计划改变后，旧 ticket 不得继续使用。

### 17.2 receipt

receipt 增加非敏感摘要：

- logic_outcome；
- output_sufficiency；
- quality_level；
- side_effect_mode；
- route_id；
- gate_scope_digest；
- correction_revision；
- strategy_fingerprint；
- plan_step_id；
- operator_id；
- input_set_digest；
- input_cardinality；
- output_set_digest；
- output_cardinality；
- predicates_before；
- predicates_after；
- estimated_cost；
- actual_cost；
- avoided_work；
- override_ref；
- goal_satisfied；
- next_legal_actions。

不要记录业务正文、完整岗位数据、JD、简历或 secret。

### 17.3 成本控制

一个昂贵逻辑动作尽量：

- 一次 MSE 纯判定；
- 一次 challenge；
- 一次 admit；
- 一次 execute；
- 一次 postcondition 更新。

不得因为 MSE 再启动独立 LLM 审查。

---

## 18. 与产品衔接的最小协议

产品接入不应要求重构内部业务代码。提供三种接入方式。

无论使用哪种接入方式，产品至少需要暴露四类最小事实：

1. 哪个 route 能产生哪种输出质量和工件；
2. preview、propose、commit 分别改变哪些副作用；
3. 每个 operator 处理和产生哪个集合；
4. Gate 是 scoped 还是 global，以及它检查哪个集合。

如果产品声明 preview 与 commit 等质量，SOP Control 只在最终副作用边界分叉，不能选择一个不经过评分、归一化或验证的 raw route。

### 18.1 声明文件

产品可以提供一个小型配置文件，例如：

    product_id: jobsflow
    contract_version: "1"

    quality_contract:
      canonical_route: jobsflow.production_pipeline
      preview_same_quality_as_commit: true
      preview_disables:
        - final_table_write
      required_preview_artifacts:
        - initial_score
        - lane
        - semantic_status

    gate_contracts:
      - id: jobs.target-set-ready
        scope: set
        accepts_set_ref: true
      - id: jobs.run-completed
        scope: run
        global_required: false

    entities:
      - job

    operators:
      - id: jobs.search
        role: source
        cost:
          class: external
          unit: run
        side_effect:
          class: network

      - id: jobs.filter
        role: reducer
        consumes:
          required_fields: [title, published_at]
        produces:
          predicates: [published_within, title_matches]
        cost:
          class: low
          unit: item

      - id: jobs.exclude_existing
        role: anti_join
        consumes:
          required_fields: [job_id]
        produces:
          predicates: [not_in_table]
        cost:
          class: low
          unit: batch

      - id: jobs.score
        role: scorer
        produces:
          fields: [score]
        cost:
          class: high
          unit: item
        side_effect:
          class: external_write

声明文件不包含实现，只描述接口性质。

### 18.2 SDK/函数装饰器

产品可在已有入口旁增加轻量声明：

    register_operator(
        id="jobs.score",
        role="scorer",
        cost_class="high",
        preserves_cardinality=True,
        produces_fields=["score"],
    )

SOP Control 不接管函数内部逻辑，只在调用边界检查。

### 18.3 CLI/bridge 参数

无法修改产品代码时，可以通过 wrapper/bridge 映射：

    sopctl bridge install
      --integration-id jobsflow.score
      --operator-id jobs.score
      --role scorer
      --cost-class high
      --side-effect external_write

具体 CLI 以仓库实际命令为准。外部模型不得机械添加不符合现有 CLI 风格的参数，先设计统一 schema 和迁移。

### 18.4 产品 Gate 适配

产品 adapter 应提供类似能力：

    evaluate_gate(
        gate_id,
        target_set_ref,
        task_id,
        plan_digest,
        source_snapshot_digest
    )

返回必须区分：

- scoped_pass；
- scoped_pending；
- global_required；
- scope_unsupported；
- stale_snapshot；
- invalid_target。

SOP Control 不替产品判断 pending 的业务含义，但要阻止产品把与当前 target_set 无关的 pending 默认扩展成任务义务。

### 18.5 计划与产品状态的握手

产品执行入口在运行前接受：

- goal digest；
- plan digest；
- step id；
- input set ref；
- required quality；
- side-effect mode；
- correction revision。

执行后返回：

- output artifact schema；
- output quality；
- output set ref；
- predicate proofs；
- gate scope；
- actual side effect。

缺少握手字段时，observe 模式记录 unproven；block 模式下高成本或高影响步骤不得继续。

---

## 19. 自动接入和规则空间生长

### 19.1 自动发现

surface inventory 发现新入口时，可以推断：

- command 名称；
- surface；
- side effect；
- 是否批处理；
- 是否高成本；
- 已有相似 operator。

但不能自动确定：

- 业务 predicate；
- score 是否影响筛选；
- 目标集合；
- 正确业务顺序；
- 是否允许重算。

无法证明的信息生成 OperatorContract candidate。

### 19.2 Candidate

candidate 至少包含：

- surface_id；
- suggested operator_id；
- suggested role；
- observed side effect；
- suggested cost class；
- discovered input/output schema；
- 与现有 operator 的差异；
- 尚未证明的依赖；
- 需要产品确认的最少字段；
- 影响范围；
- 接入建议；
- 回归 fixture 建议。

### 19.3 确认后

确认 OperatorContract 后：

- 产生 contract revision；
- 进入产品/规则空间；
- 新 digest；
- surface 绑定 operator；
- doctor 显示 governed；
- MSE 可以使用该 operator；
- 旧 plan 必须重新编译；
- 不要求用户重复确认每次执行。

---

## 20. 中途接入已有产品

### 20.1 第一次扫描

对已有产品：

1. 发现 surface；
2. 根据命令、schema 和运行事件生成 operator 候选；
3. 将确定性高的安全属性自动映射；
4. 将业务依赖标记 unproven；
5. 运行 observe 模式；
6. 收集集合大小、调用顺序和 side effect 摘要；
7. 生成最小确认清单。

### 20.2 不要求用户做什么

不要求用户：

- 重写全部业务函数；
- 把全部数据搬进 SOP Control；
- 为每一步写专用 adapter；
- 每次运行批准计划；
- 手动维护完整 DAG；
- 把业务语义交给 SOP Control。

### 20.3 用户只需确认什么

理想情况下只确认：

- 目标集合如何定义；
- 哪些操作会缩小集合；
- 哪些操作成本高；
- 哪些谓词依赖昂贵操作结果；
- 哪些特殊目标允许扩大范围；
- 哪些步骤是 required。

### 20.4 灰度

建议：

- observe：只记录明显支配问题；
- warn：输出下一步建议；
- block：只阻断已证明的高成本/高影响支配计划；
- 未证明的低风险情况不应阻断整个产品；
- 合同稳定后再提升到 block。

---

## 21. JobsFlow 示例闭环

### 21.1 用户请求

    检索过去一周的产品经理职位，
    对尚未入表的岗位评分并展示。

### 21.2 GoalContract

    entity_type: job

    target_set:
      predicates:
        - published_within(days=7)
        - title_matches(product_manager)
        - not_in_table(jobs_main)

    required_outputs:
      - score(target_set)
      - display(target_set)

### 21.3 OperatorContract

    jobs.search:
      role: source
      cost: external
      produces: raw_jobs

    jobs.filter_date:
      role: reducer
      cost: low
      produces_predicate: published_within

    jobs.filter_title:
      role: reducer
      cost: low
      produces_predicate: title_matches

    jobs.exclude_existing:
      role: anti_join
      cost: low
      produces_predicate: not_in_table

    jobs.score:
      role: scorer
      cost: high
      produces_field: score
      dependencies:
        score_not_used_by:
          - published_within
          - title_matches
          - not_in_table

    jobs.display:
      role: sink
      cost: low

### 21.4 合法计划

    S0 = jobs.search()
    S1 = jobs.filter_date(S0)
    S2 = jobs.filter_title(S1)
    S3 = jobs.exclude_existing(S2)
    S4 = jobs.score(S3)
    jobs.display(S4)

### 21.5 非法默认计划

    S0 = jobs.search()
    S1 = jobs.score(S0)
    S2 = jobs.filter_date(S1)
    S3 = jobs.filter_title(S2)
    S4 = jobs.exclude_existing(S3)
    jobs.display(S4)

MSE 判定：

- score 不参与三个 predicate；
- 三个操作均会缩小集合；
- score 成本高；
- 计划输出等价；
- 第二个计划被第一个支配；
- 在 jobs.score 前阻断。

### 21.6 合法的反向计划

用户请求：

    检索过去一周的所有产品经理岗位，
    全部评分后只展示评分高且未入表的岗位。

此时：

- score 是 required output for all matching jobs，或者
- score_threshold predicate 依赖 score。

因此评分必须发生在部分筛选之前或针对更大集合执行。这不是 override，而是新的 GoalContract 和依赖图。

### 21.7 预览不得降级为原始清单

若 JobsFlow 声明：

    preview_same_quality_as_commit: true
    preview_disables:
      - final_table_write

则预览必须仍然产生：

- initial_score；
- lane；
- semantic_status；
- 可追溯 source snapshot。

只调用门户 CLI 返回原始 URL 清单，应在计划编译阶段返回：

    reason_code: missing_required_artifact
    missing:
      - initial_score
      - lane
      - semantic_status
    next_action: 使用正式检索管线生成 production-equivalent preview

### 21.8 缺少初评分不是可接受终态

当 GoalContract 要求 scored preview 时，“这些结果无法入表，因为没有评分”不能成为交付结论。

系统应优先检查：

- 是否走错 route；
- 是否跳过 scorer；
- 是否使用 raw-only adapter；
- 是否缺少必需输入；
- 是否仍有正确的已有管线可用。

只有正确 route 的最小复现仍失败时，才可以升级为产品缺口。

### 21.9 不得用扩大范围替代精确定位

目标为：

    last_7_days ∩ paralegal ∩ not_in_table

模型不得因为局部结果缺少评分就自动改为：

    168h 全周扫描
    -> 全部候选
    -> 全部 pending
    -> 全部语义清理

除非证明精确目标集合无法由现有 operator 产生。

在 broad scan 前，MSE 必须比较：

- 精确查询/已有工件重用；
- target-set anti-join；
- 局部评分；
- 全量扫描。

如果全量扫描被前三者支配，则在执行前阻断。

### 21.10 用户纠正后旧框架立即失效

当用户明确指出：

- “预览检索也是检索的一种”；
- “没有初评分是不正常的”；
- “应该先看哪些没入表”；

系统必须：

- 更新 correction revision；
- 将 raw-preview 和 full-run-grind 计划标为 stale；
- 禁止再次运行相同 168h 扫描；
- 重新编译 target-set-first 计划；
- 将纠正作为当前任务权威约束。

### 21.11 20 条变 10 条必须由集合差异解释

数量变化不能只靠模型事后口头解释。

应产生：

    set A:
      source: direct portals
      query_digest: ...
      snapshot_at: ...
      cardinality: 20

    set B:
      source: production scan
      query_digest: ...
      snapshot_at: ...
      cardinality: 11

    overlap:
      cardinality: 2

    removed_existing:
      cardinality: 1

    externally_added_since_snapshot:
      cardinality: 9

SOP Control 只保存集合摘要和差异计数，不保存完整岗位数据。

### 21.12 run 级 Gate 不得自动扩大 scoped task

若当前 target_set 只有 8 条，而 run 中另有 67 条无关 pending：

- scoped gate 应只检查 8 条；
- global gate 若不是当前任务的显式不变量，不得强迫清理 67 条；
- 产品只提供 global gate 时返回 scope_unsupported；
- SOP Control 报告 adapter capability gap；
- 不得绕过 Gate；
- 不得默认选择清理 67 条。

### 21.13 相同失败扫描不得重复

第一次 168h 扫描没有覆盖目标集合，且用户已经要求收窄后，再次执行近似扫描必须触发 repeated_failed_strategy。

允许重试必须至少有一项新证据：

- query 配置实质变化；
- source 增加；
- snapshot 更新；
-产品修复；
- 用户明确授权；
- 依赖图变化。

---

## 22. 错误输出必须可执行

禁止只返回：

- invalid plan；
- logic error；
- non-minimal；
- workflow failed。

正确输出应包含：

    outcome: block
    reason_code: dominated_expensive_step
    step_id: score-all
    operator_id: jobs.score
    input_cardinality: 240
    missing_reducers:
      - jobs.filter_title
      - jobs.exclude_existing
    proof:
      score_not_required_by_predicates:
        - title_matches
        - not_in_table
    estimated_minimal_cardinality: 37
    next_action:
      run jobs.filter_title and jobs.exclude_existing,
      then call jobs.score with the resulting set

模型拿到这个结果后不需要重新分析整个项目。

---

## 23. CLI 和诊断设计

建议提供以下能力。具体命令名应服从仓库现有命名。

### 23.1 Contract

    sopctl logic goal validate <file>
    sopctl logic operator validate <file>
    sopctl logic operator list
    sopctl logic operator explain <operator-id>

### 23.2 Plan

    sopctl logic plan check <file>
    sopctl logic plan explain <plan-id>
    sopctl logic plan optimize <file> --dry-run
    sopctl logic plan freeze <file>

optimize 默认只给建议，不能静默改用户目标。

### 23.3 Lineage

    sopctl logic lineage show <set-id>
    sopctl logic lineage trace <set-id>
    sopctl logic lineage verify <set-id>

### 23.4 Doctor

doctor 增加：

- 多少 surface 缺 OperatorContract；
- 多少高成本操作未声明依赖；
- 多少 GoalContract 无法编译；
- 多少动作缺 lineage；
- 是否存在明显 late filtering；
- 是否存在重复 recompute；
- 是否存在目标达成后的多余动作；
- 接入产品需要确认的最少字段。

### 23.5 Cost

    sopctl logic costs <task-id>

输出：

- expensive_items；
- external_calls；
- token estimate；
- avoided_items；
- cache_hits；
- dominated_plan_blocks；
- unnecessary_steps；
- repeated_context。

---

## 24. 安全与隐私

### 24.1 不保存正文

默认只保存：

- schema id；
- set id；
- digest；
- cardinality；
- predicate id；
- operator id/version；
- plan/task/run；
- cost；
- verdict。

不保存：

- 岗位全文；
- JD；
- 简历；
-用户私人数据；
- API token；
- ticket secret；
- cookie；
-完整数据库内容。

### 24.2 防伪

产品返回的 lineage proof 不能只靠模型自报。

证据可以来自：

- 已注册 adapter；
- 确定性产品函数；
- schema validator；
- 数据库查询摘要；
- 受控 postcondition；
- 已绑定 receipt。

高风险场景下，如果产品只提供自由文本“已经过滤”，判为 unproven。

### 24.3 并发

- source snapshot 必须有 digest/revision；
- 表状态变化后旧 not_in_table proof 失效；
- score 执行前可按策略重新验证 membership snapshot；
- 不要因为重验而重新评分；
- optimistic concurrency 失败应重新计算最小必要集合。

---

## 25. 工作包和实施顺序

### WP-0：基线

检查：

- 当前分支和工作区；
- 当前测试；
- 当前 ActionEnvelope；
- 当前 ControlProfile；
- 当前 surface inventory；
- 当前 ticket/bridge；
- 当前 JobsFlow enablement 文档；
- 是否已经存在 logic/lineage 模块。

交付：基线报告，不修改代码。

### WP-1：模型和 schema

实现：

- GoalContract；
- ArtifactRequirement；
- QualityContract；
- ExecutionModeContract；
- GateScopeContract；
- OperatorContract；
- SetLineage；
- ExecutionPlan；
- LogicEvaluation；
- 稳定 normalize/digest；
- schema version。

测试：

- 缺字段；
- 未知字段；
- digest 稳定；
- secret 不进入 digest；
- revision 变化；
- correction revision；
- quality/side-effect 正交；
- scoped/global Gate；
- absent 与 explicit default。

### WP-2：纯判定器

实现：

- 输出充分性；
- required artifact；
- quality downgrade；
- canonical route；
- Gate scope congruence；
- 依赖图；
- 目标可达性；
- 无关动作检测；
- predicate pushdown；
- anti-join/dedup 前置；
- cache 优先；
- early stop；
- scope 不扩大；
- stale plan after correction；
- repeated failed strategy；
- product gap self-check；
- unproven。

测试：只调用纯函数，不做 I/O。

### WP-3：lineage 存储和验证

实现：

- set digest；
- parent refs；
- predicate proof；
- cardinality；
- snapshot；
- stale；
- atomic write；
- no business content。

测试：

- 篡改；
- stale；
- 逃逸；
- symlink；
- 并发 revision；
- reducer/enricher cardinality。

### WP-4：ControlProfile

实现 execution_policy，完成多层只收紧合成和 plan digest。

测试所有层级和边界。

### WP-5：Action Plane 和 Bridge

实现：

- action envelope 的 MSE 字段；
- required quality 和 side-effect mode；
- route digest；
- gate scope digest；
- correction revision 和 strategy fingerprint；
- 昂贵动作前 gate；
- canonical operation 绑定；
- ticket/receipt；
- postcondition。

测试正式 API、CLI、wrapper，不只测 helper。

### WP-6：产品接入协议

实现：

- declaration loader；
- quality/preview contract；
- scoped/global gate contract；
- plan/product handshake；
- SDK 或轻量 registration；
- bridge 映射；
- schema validation；
- product/version binding；
- candidate 生成。

创建一个不依赖 JobsFlow 的通用 fixture。

### WP-7：规则空间生长

实现：

- 新 surface -> operator candidate；
- 接受 -> revision；
- 新 contract -> plan 失效；
- 拒绝去重；
- 删除/重命名；
- 不能自动发明业务依赖。

### WP-8：observe/warn/block

实现灰度模式、迁移和向后兼容。

### WP-9：性能和成本

测量：

- 纯判定耗时；
- lineage 存储；
- no-change plan；
- 每动作控制调用；
- 增量 operator discovery；
- 额外 token 必须为零或接近零。

### WP-10：最终验收

运行所有定向、全量、coverage、ruff 和 gate。

---

## 26. 必须增加的测试

建议测试名称如下。按仓库惯例放入 tests/harness 或新的 tests/logic。

### 数据模型

- test_goal_digest_changes_when_target_changes
- test_correction_revision_changes_plan_digest
- test_quality_mode_is_independent_from_side_effect_mode
- test_required_artifact_is_part_of_goal_digest
- test_gate_scope_is_part_of_plan_digest
- test_operator_digest_changes_when_dependencies_change
- test_plan_digest_binds_goal_profile_and_operator_versions
- test_unknown_contract_fields_are_rejected
- test_secret_is_not_part_of_logic_digest

### 最小充分性

- test_cheaper_but_insufficient_raw_preview_is_rejected
- test_preview_does_not_downgrade_required_quality
- test_plan_without_required_artifacts_is_insufficient
- test_noncanonical_route_requires_equivalence_proof
- test_filter_independent_of_score_is_pushed_before_score
- test_anti_join_precedes_expensive_enrichment
- test_score_first_is_allowed_when_filter_depends_on_score
- test_score_all_is_allowed_when_goal_requires_all_scores
- test_unrelated_step_is_rejected
- test_valid_cache_precedes_recompute
- test_goal_satisfied_stops_additional_work
- test_required_check_is_never_optimized_away
- test_unknown_dependency_is_unproven_not_pass
- test_scoped_goal_is_not_expanded_by_global_pending
- test_same_failed_strategy_without_new_evidence_is_blocked

### Lineage

- test_score_input_requires_target_predicates
- test_reducer_cannot_expand_cardinality
- test_anti_join_cannot_expand_left_input
- test_enricher_preserves_cardinality_by_default
- test_stale_membership_snapshot_invalidates_not_in_table
- test_changed_input_digest_invalidates_ticket
- test_model_text_cannot_forge_predicate_proof
- test_lineage_contains_no_business_content

### 动态规则

- test_execution_policy_absent_fields_inherit
- test_task_layer_cannot_relax_block_to_warn
- test_actor_layer_can_reduce_cost_budget
- test_goal_revision_invalidates_old_plan
- test_operator_revision_invalidates_old_plan
- test_scope_expansion_requires_new_goal
- test_user_correction_invalidates_old_plan_and_ticket
- test_one_time_correction_does_not_modify_base_profile

### 运行时

- test_required_output_missing_blocks_preview_delivery
- test_wrong_pipeline_route_is_blocked_before_expensive_fallback
- test_gate_scope_mismatch_returns_actionable_result
- test_scope_unsupported_reports_adapter_gap_without_bypassing_gate
- test_old_next_action_is_invalid_after_user_correction
- test_repeated_full_scan_is_blocked_after_scope_correction
- test_product_gap_requires_canonical_route_self_check
- test_expensive_action_blocked_before_pending_reducers
- test_low_cost_reducer_needs_no_extra_ticket
- test_logic_gate_uses_same_operation_as_ticket_and_receipt
- test_plan_step_binding_survives_cli_to_receipt
- test_override_requires_goal_revision_or_authorized_reference
- test_mse_adds_no_model_call

### 产品接入

- test_product_declares_preview_quality_separately_from_commit
- test_product_declares_scoped_and_global_gates
- test_product_handshake_reports_output_quality_and_set_ref
- test_product_manifest_registers_operators
- test_unknown_operator_creates_candidate
- test_candidate_does_not_invent_business_dependency
- test_candidate_accept_binds_surface_to_operator
- test_midstream_attach_preserves_product_files
- test_product_version_change_invalidates_contract
- test_missing_contract_observes_before_block_rollout

### JobsFlow 类 fixture

- test_jobs_preview_uses_production_quality_without_table_write
- test_jobs_raw_portal_list_is_not_valid_scored_preview
- test_jobs_missing_initial_score_is_plan_error_not_terminal_success
- test_jobs_default_scores_only_unlisted_matching_set
- test_jobs_score_all_then_filter_is_blocked_by_default
- test_jobs_score_threshold_allows_score_before_threshold_filter
- test_jobs_explicit_all_scores_goal_allows_broader_scope
- test_jobs_membership_change_recomputes_filter_not_scores
- test_jobs_unrelated_run_pending_does_not_expand_scoped_task
- test_jobs_user_correction_invalidates_old_full_scan_plan
- test_jobs_repeated_168h_scan_without_new_evidence_is_blocked
- test_jobs_count_change_has_lineage_diff

---

## 27. 端到端验收场景

必须创建一个独立 fixture，不依赖真实 JobsFlow。

### 场景 A：默认最小计划

初始 100 条对象：

- 过去一周 60；
- 目标类型 20；
- 未入库 5；
- score 成本高。

计划应当只对 5 条评分。

验收：

- score input cardinality = 5；
- 三个 predicate proofs 存在；
- 无额外 LLM 调用；
- receipt 记录 avoided_items = 95；
- 最终结果满足目标。

### 场景 B：被支配计划

模型提出 score 100 条后再筛选。

验收：

- 在 score 执行前 block；
- 没有真实评分副作用；
- reason_code 明确；
- next_action 指向过滤；
- 不消耗 score ticket；
- 不写成功 receipt。

### 场景 C：真实反向依赖

目标包含 score >= 80。

验收：

- 依赖图证明 threshold 需要 score；
- 允许先评分必要候选集合；
- 不错误报告 dominated；
- 最终目标正确。

### 场景 D：用户扩大目标

用户要求所有目标岗位都要评分。

验收：

- 新 GoalContract revision；
- 新 plan digest；
- 旧 ticket 失效；
- score 全部目标岗位合法；
- 不把本次要求升级成 Base 规则。

### 场景 E：缓存

部分对象已有有效 score。

验收：

- 先排除有效缓存；
- 只评分缺失或陈旧对象；
- 输入/规则变化的缓存不复用；
- 不为缓存命中创建评分 ticket。

### 场景 F：中途接入

先有产品和动作历史，再接入 SOP Control。

验收：

- 产品仍可运行；
- 新 operator 候选可解释；
- observe 模式不误阻断；
- 确认少量契约后可进入 block；
- 无需重构产品主要代码。

### 场景 G：产品生长

新增一个 expensive enricher。

验收：

- surface inventory 发现；
- 生成 OperatorContract candidate；
- 未确认依赖前 high-cost plan 为 unproven；
- 接受后 MSE 可判定；
- 旧 plan 重编译；
- 日常动作不重复确认。

### 场景 H：等质量预览

产品声明 preview 与 commit 等质量，仅禁止最终写入。

验收：

- preview 仍经过 normalization、score 和 required checks；
- required artifacts 完整；
- 最终 table write 未发生；
- raw-only 路径在编译阶段被拒绝；
- preview 和 commit 的质量契约相同；
- 二者 side-effect mode 不同。

### 场景 I：用户纠正

模型先提出 raw preview，用户纠正“预览也必须有初评分”。

验收：

- correction revision 递增；
- 旧 plan、ticket 和 next_action 失效；
- 继续旧 plan 被拒绝；
- 新计划使用正式管线；
- 一次性纠正未自动写入 Base 规则。

### 场景 J：Gate 作用域

run 中有 80 条 pending，当前任务目标集合只有 8 条。

验收：

- scoped gate 只检查 8 条；
- 其余 72 条不会自动进入任务义务；
- global gate 不是必需条件时不阻断 scoped task；
- 只有 global gate 时返回 scope_unsupported；
- 不绕过产品 Gate；
- 不自动清理无关 pending。

### 场景 K：重复失败策略

第一次广泛扫描没有推进目标，用户随后要求收窄。

验收：

- 相同 strategy fingerprint 的第二次广泛扫描被阻断；
- 没有真实网络或评分副作用；
- 提供 target-set-first 的 next_action；
- 输入、目标或产品状态实质变化后才允许重试。

### 场景 L：产品缺口归因

模型尝试报告“产品没有能力”。

验收：

- 未验证 canonical route 时返回 product_gap_unproven；
- 错误输入和错误 route 不得形成产品缺口；
- 只有最小复现、正确 route 和正确目标仍失败时，才能生成 adapter/product gap；
- gap 报告包含缺失 capability、作用域和最小修复方向。

---

## 28. 性能验收

建议最低要求：

- 纯计划判定不调用网络、不调用模型；
- 小于 100 step 的计划判定应在本地快速完成；
- no-change plan 可按 digest 复用；
- 普通 reducer 不增加 ticket roundtrip；
- 一个昂贵步骤最多增加一次纯判定；
- ticket 调用不因 MSE 成倍增长；
- lineage 只记录摘要；
- 目标未变化时不重复编译；
- product contract 未变化时不重复 discovery；
- 同一个被拒计划不进入无限自动重试。

实际数值需在当前仓库环境测量并写入报告。不要伪造时间。

---

## 29. 向后兼容和迁移

### 29.1 旧项目

没有 GoalContract/OperatorContract 的旧项目：

- 默认 observe；
- 不声称计划最小；
- 高影响动作仍受原有 admission；
- doctor 报告 logic_unproven；
- 提供最小接入候选；
- 不因为升级直接让全部旧流程瘫痪。

### 29.2 schema version

- 所有 contract 有 schema_version；
- 旧 schema 只读兼容；
- 迁移产生新 revision；
- 迁移不自动改变业务依赖；
- 不兼容升级使旧 plan 失效；
- rollback 能恢复旧 contract。

### 29.3 功能开关

功能开关用于灰度，而不是绕过：

- off：仅兼容旧项目；
- observe：记录；
- warn：提示；
- block：已证明的违规阻断。

生产 block 不能通过模型侧 env 临时关闭。模式变化必须进入 profile/plan digest。

---

## 30. 验收命令

根据仓库实际环境调整路径，但必须报告实际命令。

定向测试：

    .venv/bin/pytest -q tests/logic
    .venv/bin/pytest -q tests/harness -k "logic or lineage or minimal or plan or operator or goal"

现有关键回归：

    .venv/bin/pytest -q tests/harness/test_bridge.py
    .venv/bin/pytest -q tests/harness/test_canonical_admission.py
    .venv/bin/pytest -q tests/harness/test_effective_plan.py
    .venv/bin/pytest -q tests/harness/test_task_profile_binding.py
    .venv/bin/pytest -q tests/harness/test_growth_joint_fixture.py

全量：

    .venv/bin/pytest -q

覆盖率：

    .venv/bin/pytest -q --cov --cov-branch --cov-report=term-missing

静态与门禁：

    .venv/bin/ruff check sopcontrol plugins tests
    git diff --check
    .venv/bin/python -m sopcontrol.cli gate .
    .venv/bin/python -m sopcontrol.cli project check .
    .venv/bin/python -m sopcontrol.cli chronicle check .

要求：

- coverage 门槛以 pyproject.toml 为准；
- 不降低 fail_under；
- 被中断的命令不算通过；
- 新增分支必须有负向测试；
- gate 状态只能通过 sopctl 正式入口更新；
- 不把 mock 产品报告为真实 JobsFlow 验证。

---

## 31. 完成定义

只有以下全部满足，才能宣布 MSE 成为 SOP Control 支柱能力。

### 模型层

- GoalContract、ArtifactRequirement、QualityContract、ExecutionModeContract、
  GateScopeContract、OperatorContract、SetLineage、ExecutionPlan 模型存在；
- schema 严格；
- digest 稳定；
- 版本和 revision 完整；
- secret 和业务正文不进入控制状态。

### 编译层

- 输出充分性和 required artifacts；
- quality 与 side-effect mode 正交；
- canonical route 验证；
- Gate scope congruence；
- 目标可达性检查；
- 依赖图；
- 无关动作检测；
- filter/anti-join/dedup 前置；
- cache；
- early stop；
- scope；
- budget；
- correction revision；
- repeated strategy；
- product gap self-check；
- unproven。

### 动态规则层

- execution_policy 可配置；
- Base/Task/Run/Actor 只收紧；
- absent 正确继承；
- plan digest 包含 MSE；
- 用户临时要求只进入 Task/Goal revision。

### 运行时层

- raw preview 不能冒充 production-equivalent preview；
- 缺少必需工件不能 deliver；
- 用户纠正使旧 plan、ticket 和 next_action 失效；
- scoped task 不会被无关全局 pending 扩大；
- 重复失败的高成本策略在执行前停止；
- 宣布产品缺口前完成入口和计划自检；
- 昂贵动作前真实阻断；
- 实际 input set 与 plan 绑定；
- lineage proof 不可自由伪造；
- ticket/operation/run/receipt 一致；
- postcondition 更新；
- 目标完成后停止。

### 产品接入层

- 声明文件、SDK 或 bridge 至少有一种可用；
- 产品能分别声明输出质量和副作用模式；
- 产品能声明 scoped/global Gate；
- 产品入口完成 plan/quality/set 握手；
- 中途接入不要求大改产品；
- 新 surface 能生成 operator candidate；
- 确认后进入规则空间；
- 产品版本变化可检测；
- 没有业务 contract 时诚实报告 unproven。

### 成本层

- 不增加额外模型调用；
- 普通低成本步骤不增加 ticket；
- 高成本动作只增加一次本地判定；
- 不重复全量扫描；
- 不无限重试；
- 可输出实际节省对象数和调用数。

### 测试层

- 第 26 节测试覆盖；
- 第 27 节场景通过；
- 定向测试通过；
- 全量测试通过；
- branch coverage 达标；
- ruff、diff check、gate、project、chronicle 通过。

---

## 32. 禁止的伪实现

以下都不算完成：

- 把 preview 自动降级为 raw 输出；
- 用“预览”作为跳过评分、归一化或 required check 的理由；
- 缺少 required artifact 仍然允许 deliver；
- 使用错误 route 后把缺少结果报告为产品缺口；
- 用户纠正后继续旧计划；
- scoped task 因无关 run pending 被默认扩大；
- 在没有新证据时重复相同高成本扫描；
- 为了通过全局 Gate 自动清理目标集合之外的数据；
- 把“先过滤再评分”写死；
- 根据函数名包含 filter/score 就盲目重排；
- 让第二个 LLM 判断计划是否自然；
- 只在 prompt 中提醒模型节约；
- 只统计调用，没有执行前阻断；
- 只记录步骤顺序，不检查输入集合；
- 让模型自由文本声明 predicate 已完成；
- 让产品把全部业务数据复制到 SOP Control；
- 每一步都要求用户审批；
- 用成本理由跳过 required check；
- unknown 自动当 pass；
- 目标变化后继续复用旧 plan/ticket；
- score 全部对象后只在 receipt 中提示浪费；
- 只修 JobsFlow 专用代码，没有通用 contract；
- 只有通用抽象，没有产品接入 fixture；
- 关闭 ticket 或 enforce；
- 删除测试或降低覆盖率；
- 未经授权 commit、push 或发布。

---

## 33. 外部模型最终报告模板

### A. 结论

- MSE 状态：完成 / 部分完成 / 阻塞
- 是否已经成为运行时支柱能力：
- 是否完成产品接入协议：
- 是否增加额外模型调用：
- 是否满足第 31 节全部定义：
- 未完成项：

### B. 架构实现

逐项说明：

- GoalContract；
- OperatorContract；
- SetLineage；
- ExecutionPlan；
- LogicEvaluation；
- dynamic profile；
- action/bridge；
- ticket/receipt；
- surface growth；
- CLI/doctor。

### C. JobsFlow 类场景证据

报告：

- preview 是否保持 production-equivalent 质量；
- required artifacts 是否完整；
- raw-only 路径是否被拒绝；
- canonical route 是否实际执行；
- 初始对象数；
- 每次 reducer 后对象数；
- 实际 score 对象数；
- 被避免的 score 数；
- 被支配计划是否在执行前阻断；
- score-dependent 反向流程是否正确允许；
- 用户扩大目标后是否生成新 revision；
- 用户纠正后旧计划是否失效；
- scoped Gate 是否只检查目标集合；
- 无关 pending 是否被隔离；
- 重复失败策略是否在执行前停止；
- product gap 是否通过自检；
- 是否发生业务数据泄露。

### D. 产品接入证据

- 接入方式；
- 修改产品文件数量；
- 是否支持中途接入；
- operator candidate；
- 接受后的 revision；
- 新 surface 生长闭环；
- 产品版本变化；
- attach/detach 结果。

### E. 测试

列出命令和数字：

- 模型测试；
- 判定器测试；
- lineage 测试；
- runtime 测试；
- 产品 fixture；
- 全量 passed/skipped/failed；
- line coverage；
- branch coverage；
- ruff；
- diff check；
- gate；
- project check；
- chronicle check。

### F. 成本

- MSE 判定耗时；
- 普通动作额外调用；
- 昂贵动作额外调用；
- ticket 数；
- 模型调用数；
- 缓存命中；
- avoided work；
- 重试数。

### G. Git

- 分支；
- HEAD；
- 工作区；
- 修改文件；
- commit；
- push；
- 未执行项及原因。

### H. 剩余风险

只报告真实风险：

- operator contract 依赖产品声明准确性；
- 动态语言和运行时生成入口；
- 非确定性操作；
- 数据快照并发；
- 超大 lineage；
- 旧项目迁移；
- Windows/其他平台；
- 真实外部 harness 尚未验证。

---

## 34. 最终产品原则

MSE 的最终判断标准不是“系统替模型规划了一切”，而是：

- 模型仍然可以规划；
- 产品仍然拥有业务逻辑；
- 用户仍然可以改变目标；
- 便宜但输出不充分的路径不能被接受；
- preview 只改变副作用，不擅自降低质量；
- 正式管线和必需工件在执行前可证明；
- SOP Control 只禁止已被证明无必要的范围扩张、成本和绕路；
- Gate 的检查范围与当前任务目标一致；
- 用户纠正后旧框架不能继续；
- 没有新证据的失败策略不能反复执行；
- 产品缺口必须在正确入口和最小复现后才能成立；
- 特殊顺序由真实依赖或明确目标证明；
- 日常流程不增加人工审批；
- 判断主要由确定性契约和集合沿袭完成；
- 产品新增能力时，规则空间会生成 operator 候选并持续生长；
- 接入不要求大规模改造；
- 所有高成本动作在执行前都能回答：
  - 当前真正的目标和 correction revision 是什么；
  - 当前输出需要达到什么质量；
  - 当前 route 能否产生所有必需工件；
  - 为什么要做；
  - 对哪些对象做；
  - 为什么现在做；
  - 是否还有更便宜但结果相同的步骤应先做；
  - 当前 Gate 检查的是不是同一个目标集合；
  - 这个策略是否已经失败且没有新证据；
  - 做完后如何证明目标更接近完成。

只有这些问题能由系统结构化回答，并在错误计划真正执行前产生控制行为，MSE 才算成为 SOP Control 的支柱能力。
