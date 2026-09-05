# ROADMAP — 自主推进的权威状态源与决策规则

状态在模型上下文之外持久化——这正是本项目的第一原则，也适用于推进本身。
每次自主运行：读本文件 → 按规则选下一项 → 执行 → 自检 → 更新状态 → 提交。

## 边界（自主运行不得违反；本节不得修改）

1. 只在 `/Users/xiezhijie/sopcontrol` 内工作；不改外部仓库（含 ai-job-search）。
2. 不 push、不发布、不引入超出 pydantic / PyYAML / pytest 的新依赖。
3. 脊柱（`sopcontrol/`）零 LLM；判定器（`verdict.py`）零 I/O（宪法测试守卫）。
4. 每个新检测模式必须同步新增语料用例（优先跨领域夹具）；无语料的模式不算完成。
5. 同一问题连续两次修复失败 → 在「Blockers」登记并跳过，不得无限返工。
6. 测试不全绿不得提交；提交信息用 `[B阶段]` / `[LP阶段]` 前缀。
7. 保持克制：先闭环后带宽；拒绝防御性脚手架、feature flag 与面面俱到。
8. 对既有判决不重新诉讼：DESIGN.md 已定的决策直接执行，除非实践证明其错误。
9. Living-Project 取向（手册 2026-08-31）：消歧优先于加守卫；确定事实活在项目里；
   空间双向可变。判据：这条改动是在告诉模型别做什么，还是让那件事不再需要被决定？

## 阶段

### B0 行走骨架 — 完成（2026-08-23）
- [x] 三原子 model / registry / ledger / verdict / audit / cli
- [x] 传感器 code_scan + doc_scan；检测器 no_consumer（5 模式）
- [x] 3 领域夹具 + 10 语料用例 + 宪法测试；doctor / explain / strict 门
- 验收：`sopctl init/rule/audit/explain` 全通；26 测试全绿；账本幂等；strict 退出码正确

### B1 终点执行器 — 完成（2026-08-23）
- [x] `sopctl gate`：fail 判定与账本篡改 → 阻断（退出码 1）；gap 仅告警（L2/L3 阶梯）；审计异常 fail-closed
- [x] `sopctl hook install`：pre-push 终态门（带标记；拒绝覆盖非 sopctl 钩子；幂等重装）
- [x] `sopctl self-test`：穿透演习——通过真实命令路径注入已知违规（legacy 绕过、账本篡改），断言被阻断；清洁现场断言放行
- [x] 测试：gate 三态、hook 安装/拒覆盖、self-test 演习
- [x] doctor 报告 pre-push 门武装状态
- [x] RESIDUAL_RISKS 登记 R6（hook 可被 `--no-verify` 绕过；CI 为后盾）
- 验收：`pytest` 全绿；`sopctl self-test` 通过；临时仓库 hook 实测阻断

### B2 快回路 — 完成（2026-08-23 深夜）
- [x] TaskContract / PolicyEnvelope 最小 schema（DESIGN.md §10：不新增第四种真相）
- [x] INTAKE→…→DELIVERED 状态机 + 合法迁移表（task.py；blocked/failed_unverified 终态）
- [x] `sopctl task open/accept/submit/verify/deliver/show/list`：范围走私拒绝、完成门只信 E3 审计、修复预算由任务能力契约决定（unknown 最多 1 轮）、revision 防旧覆盖
- [x] 任务语料 `corpus/task_cases.yaml`（8 用例）：14.1 场景 2/5/8/9/11/15 + 两个正向对照；场景 6/7 归 B4（场景 1 见下）
- [x] 意图编译器 v0：`sopctl intake` 文档 MUST 句 → CandidateRule（observed，永不写注册表；强度建议区分必须/不得）
- [x] 场景1 对话意图层：`intake --conversation` + discuss_only 阻断写工具（DESIGN §12，2026-08-25）
- [x] 宪法测试补：迁移门纯度（炸 open）、拒绝可解释、路径规范化拒绝 `..`/绝对路径
- 验收：47 测试全绿；CLI 全生命周期实测（契约→执行→gap 修复轮→接线→verified→delivered）
- 实测捕获的真 bug 两枚：完成门曾按全项目口径连坐无关规则 fail；CLI open 误引用 args.changed（API 层测试测不到的接线 bug）

### B3 有界修复 — 完成（2026-08-23 深夜，框架层）
- [x] gap contract：`sopctl repair open <finding_id>` → 指纹绑定的修复任务（经 B2 任务机执行，完成门复用）
- [x] 同指纹熔断：同断口重复开单拒绝；历史修复失败（failed_unverified/blocked）→ 拒绝再开、转人工
- [x] 已达标拒绝：规则当前 pass 时不开修复（防无意义返工）
- [x] 测试 5 项（契约生成/重复拒绝/熔断/已达标/未知 finding 可行动报错）；CLI 实测全链路
- [x] git worktree 隔离 + `sopctl repair apply`（自动修复者 v0：隔离改、契约外丢弃、合并回主树；2026-08-26）

### B4 校准与投影 — 完成（2026-08-25，含 capability handshake）
- [x] harness 决策核心：`sopctl harness-check`（stdin/--payload，工具名跨 harness 归一，决策纯函数）
- [x] Claude Code 适配（PreToolUse JSON，协议对照官方文档核实；本机无 key，live_verified=false 如实记录）
- [x] **OpenCode 适配并实测**：`.opencode/plugins` 运行时插件；真实模型 Edit 控制器文件被拒演习通过
- [x] **Codex 适配并实测**：AGENTS.md 投影（模型主动遵守）+ `sopctl wrap codex` 事后门（真实会话后 gate 阻断）
- [x] 拦截组件自保护：卸插件/改钩子配置 = 提权，拒绝（人工动作）
- [x] 能力画像 `.sopcontrol/harness-profile.yaml`（live_verified + live_evidence 归档）
- [x] 接管包：`sopctl task takeover`（手册 8.3，只读）
- [x] **capability handshake（模型维度）**：三维探针 json/boundary/instruction → tier →
  调节 `max_repairs`/`allowed_writes` 粒度；fixture/responses 只做离线校准，真实 `--live` 结果
  必须由人工 `capability-approve` 绑定该次评测摘要后才可授权；`task open --model <当前模型>`
  仅使用身份匹配、探针自洽且批准未失效的 live 画像，其余按 `unknown`。显式
  `--max-repairs` 只能在能力上限内进一步收紧；热路径不新增扫描、子进程或 LLM；DESIGN §11
- 剩余：codex 出现运行时钩子后升级其画像；真实模型探针（可选，本切片不强制烧 token）
- claude 适配保留：用户环境无 key（不修），有 key 环境可直接实测
- [x] **第二批：被动能力事件采集（2026-08-31）**：复用 task open/迁移、runtime guard、gate
  已产生的客观结果，追加可校验、可重放、有上界的事件日志；发生 ID 与语义指纹分离，普通写入
  真追加、阈值压缩，写入失败不阻断原动作，不新增仓库扫描、子进程或 LLM。
- [x] **第三批：行为画像保守消费（2026-08-31）**：按任务固化的模型身份隔离事件；拒绝写入
  独立、带校验和且不可被普通遥测驱逐的 30 天 `weak` 安全上限；成功只建议升级，不自动授权或
  清除上限；批准与行为证据过期均回到保守边界。事件/状态损坏时 fail-closed。
- [x] **二三批联合复核修复**：封闭 FIFO 驱逐恢复 strong 与伪造 event_id 路径；补 gate 审计异常
  留证和 `capability-events` 只读查看入口。
- [x] **第四批：重复行为候选聚合（2026-08-31）**：统一运行时 Candidate schema 与稳定语义指纹；
  guard 拒绝、Finding 指纹和结构化纠正达到 3 个不同 occurrence 后，仅在显式 `candidate refresh`
  冷路径物化候选。`list/show/triage` 只供审查，不写 registry、不自动晋升、不改变任务或 harness 权限。
- [x] **第五批：批量候选裁决与信任根收口（2026-08-31）**：`candidate batch-triage` 对全部 ID
  预校验后一次保存，未知 ID 时零变更；复合 shell 命令不能用 `sopctl` 子串绕过控制面保护；
  已批准画像锚定行为状态存在性，同一拒绝重放不再滑动续期。
- [x] **第六批：规则永久退出（2026-08-31）**：`rule deprecate/supersede` 以绑定 registry 快照的
  preview ID 做人工两阶段确认；旧规则退休、replacement 接管与平台投影全成或全回滚。统一
  `active_rules` 供冲突、审计、成熟度、任务、repair 与投影消费；历史记录保留但不再产生新义务。
- [x] **第六批验收加固 6R（2026-08-31）**：普通 `Registry.transition/add` 不得进入或直建
  `deprecated/superseded`，永久退出只留内容寻址确认入口；补第三方冲突零写入、退休确认书不计
  当前成熟度、任务迁移只认当前有效规则、冲突检测忽略退休规则四项行为回归。
- [x] **第七批 7E：规则可逆生命周期（2026-08-31）**：以内容寻址两阶段确认实现 `suspend --until`、
  `reinstate` 与 `narrow --scope`；截止时刻 inclusive，生命周期 revision 使旧 attestation/trace 失效，
  各投影与消费者统一使用固定时点 effective rules，普通入口不得绕过 lifecycle。scope v1 仅覆盖项目级/
  仓库相对路径前缀；任务、平台、时间级 scope 与非路径 Evidence subject 后置；静态 invariant guards 不随暂停关闭。
  审查加固进一步封闭 Registry 治理事实旁路、task/repair 竞态和 attestation/repair symlink TOCTOU。

### B5 模式库扩展 — 完成（2026-08-24 凌晨，经任务机自应用交付）
- [x] `write_only_state`（只写不读代理，info；shop + jobflow 双域）
- [x] `state_in_parallel_files`（双处维护，gap；shop + ci 双域）
- [x] `state_marker_absent`（声明状态不存在，info）
- [x] Rule.state_markers 字段；verdict 对状态类规则显式"不适用吸收等级"（不猜）
- [x] TASK-0001 全流程：契约→范围检查→完成门独立审计 SELF-001/002→delivered（自应用首次真实闭环）

### LP1 消歧批 — 完成（2026-09-02）
对应手册阶段 D 切片起步 + E 取向纠偏起步。哲学：少让模型猜；权威留在项目。
- [x] 最小任务投影：`tasks_for_projection`（活跃 + 未接替 blocked/failed；delivered 不进投影）
- [x] blocked 裁决链：`resolution_of` / `superseded_by_task` / `blocked_reason_code`；`task open --resolves`
- [x] `delete_entry` 一等候选（legacy 达阈值）；repair 目标偏删入口；`metrics.structure_signals`
- 验收：521 测试全绿；本仓投影约 178→53 行；`project check` 通过

### LP2 删除优先做实 — 完成（2026-09-02，手册阶段 E 主切片）
目标：控制成熟度上升伴随**入口减少**，而不是规则/守卫变多。
非目标：全宇宙入口图谱；自动删代码（仍须任务契约 + 人确认）；自动 deprecate。

- [x] **`redundant_entry_point`**：受控入口已接线 + 声明旧入口仍在生产路径 → 发此 Finding（不再用笼统 legacy）；jobflow + ci-deploy 双域；CASE-009/010；MUT-005 证伪靶改为 redundant
- [x] **候选/修复导向删除**：`redundant_entry_point` 与 `legacy_entry_alive` → `delete_entry`；repair 目标偏删旁路
- [x] **薄清单**：`sopctl inventory` + doctor 一行摘要（受控 / 冗余 / 平行状态 / 应删旁路）
- [x] **结构信号**：`metrics.structure_signals` 计入 redundant / parallel_state / bypass
- [x] 后置（2026-09-06）：legacy 清零后自动物化 `retire_rule` 候选（6 轮阈值；人确认两阶段 deprecate，不自动退场）
- 验收：相关语料+变异+inventory 测试绿；出口「入口是否变少」可被 inventory/metrics 回答

### LP2 余量（不阻塞 LP3）
- 当结构保证足够时，批量建议移除冗余 guard / deprecate 禁止型重复规则（人工确认）

### LP3 投影再削薄 + 恢复协议 — 完成（2026-09-02，手册阶段 D 余量）
- [x] 常驻核（成熟度/硬规则/硬约束）与「当前链头」分离；`select_projection_tasks` 上限 5；verified 折叠为计数
- [x] 新会话恢复协议（投影头部 4 步）；`task takeover` note 与切片同源表述对齐
- [x] 切片摘要哈希 + 「为何在切片」；写入与 `project check` 同一 `render_projection`
- [x] 长历史测试：≥20 delivered + executing + blocked → 投影仍短且可决策
- 验收：529+ 测试全绿；本仓 AGENTS 含恢复协议与链头上限，verified 折叠、超出上限有提示

### LP4 事件历史与可重建视图 — 完成（2026-09-02，手册阶段 F 主切片）
面向换会话/换模型的「何以至此」，不是终端用户操作台。
- [x] `project-events.jsonl` 只追加：rule.add/transition/lifecycle/retire、task.open/transition
- [x] 与 ledger.`replace_snapshot` 分离；压缩保留区间哈希（view.snapshot）
- [x] `sopctl chronicle show|check|snapshot`；check 重放规则状态 vs registry
- [x] 投影「何以至此」小节 + doctor 一行；`view-snapshot.yaml` 物化摘要
- [x] 后置（2026-09-06）：lifecycle/retirement 预览带 dry-run 影响（将退出有效集合的规则、失去最后治理记录的 guard）
- 验收：编年往返完整；ledger compact 不抹编年；投影含旅程切片

出口判据：换模型只读投影/chronicle 能说出项目怎么走到现在；核对可发现 registry 与编年漂移。

### Living-Project 明确不做（直到上述出口碰壁）
- 用更多 MUST_NOT / 提示词填充歧义
- LLM 自动晋升规则或自动扩大权限
- 阶段 F 未到就引入全局 daemon / 跨机器身份
- 把 `deprecate` 降到与 `add` 同成本（永久退出保持两阶段；对称性靠 suspend↔reinstate 与删除入口）

## 状态（每次运行后更新）

- 2026-09-06（三笔收尾）：① TASK-0058 delivered——分支覆盖率 85.24%（fail_under=85），
  质量线落地；② LP 余量 TASK-0062 delivered——legacy 清零候选 + 撤销 dry-run 影响；
  ③ TASK-0063 delivered——`task withdraw`：未接受契约合法退出为 withdrawn 终态
  （投影排除、修复任务拒用、reason 留痕），并真实 withdraw 悬空的 TASK-0059 收账。
  教训：实现会话漏 accept 即 submit/verify 被拒——悬空契约的成因与出口在同一批现身。

- 2026-09-05（第七批收口补账）：补跑 TASK-0049–0052 完成门（E4 实测全量 608 passed），
  交付 0044–0052 共九任务，第七批全部 delivered。治理顺序欠账如实记录：质量/LP 批
  （0056–0061 及 LP1–LP4）曾在第七批外部复核节点未正式关闭时开工。TASK-0059 悬空契约
  处置完毕：accept 被 strict_schema 门合法拒绝（开任务未声明 MUST 字段），无删除通道，
  连同拒绝信封永久留档——「悬空 contract_proposed 无出口」边界再次实例化，候选改进：
  为 contract_proposed 增设人工 withdraw 出口。在途：TASK-0058（覆盖率 ≥85%，
  pyproject fail_under 改动未提交）。
- 2026-09-02（节能）：doctor 默认轻量（不重跑 audit）；投影 ≤~1500 tokens/80 行；
  候选展示消歧优先并在 >32 条时告警。
- 2026-09-02（产品加固 1–3）：doctor「下一刀」；`task deliver`→空间帧+变窄叙事；
  缺消费者→`improve_entry`，久悬→`retire_rule` 候选（人确认 suspend/deprecate）。
- 2026-09-02（harness 执行者校验）：`GUARD-EXECUTOR-IDENTITY`——进行中任务已绑定 model_identity
  且载荷声明当前模型时，写/bash 不一致即 deny 并提示 `task rebind`；无 model 字段保持兼容。
- 2026-09-02（生长可度量）：`SpaceSnapshot` + `sopctl growth measure|diff`；ambiguity_index=
  旁路开+平行状态，下降=空间变窄；audit ambient 轻量入帧，enact 打全量帧；投影展示最近对照。
- 2026-09-02（消歧 enact）：`sopctl candidate enact` 将 delete_entry 候选收成有界删旁路任务
  （人圈 --allow）；候选 triaged；不写 registry；编年 growth.enact_delete。
- 2026-09-02（无感生长·拒绝即记账）：harness `deny` 与 gate 阻断调用 `ambient_grow_on_control_deny`，
  不跑全仓 audit；三次拦即可推进 improve_entry/调查类候选。与 audit 生长并列。
- 2026-09-02（无感生长回路）：persist audit 自动 `ambient_grow`——每轮 finding 记独立观察
  （打破 ledger 去重）、聚合 Candidate、写 growth-state；投影「空间生长」节；`sopctl growth status|refresh`。
  发现无感；`rule add`/删代码仍人控。三轮 audit 即可物化 delete_entry，无需手工 candidate refresh。
- 2026-09-02（中途换模型适配）：`sopctl task rebind --model` 重绑执行者，旋钮与旧契约取更保守交集
  （只收紧）；编年 `task.rebind`；投影链头显示执行者；`task submit --model` 与契约不一致则拒绝。
  覆盖手册「中途换模型不得扩大可达集合」。
- 2026-09-02（Living-Project Batch 4·编年）：`project-events.jsonl` 记录规则/任务治理；
  `sopctl chronicle` 展示何以至此、check 核对重放、snapshot 写视图摘要；投影与 doctor
  暴露最小旅程。ledger compact 不触及编年。撤销 dry-run 扩展留余量。
- 2026-09-02（Living-Project Batch 3·投影削薄）：`select_projection_tasks` 链头上限 5、
  verified 折叠、省略计数；投影头部「新会话恢复」四步 + 切片摘要哈希 + 为何在切片；
  takeover note 对齐；长历史夹具测试。写入与 project check 同源。
- 2026-09-02（Living-Project Batch 2·删除优先）：受控+旧入口并存时发 `redundant_entry_point`
  （CASE-009/010 双域）；候选/repair 统一导向 `delete_entry`；`sopctl inventory` 薄清单 +
  doctor/metrics 结构信号。MUT-005 负向对照误报形态改为 redundant。判定 next_action
  改为「删旁路，不要再加禁止」。未做：自动建议 deprecate（余量）。
- 2026-09-02（Living-Project Batch 1·消歧批）：按「消除歧义空间 / 双向修剪 / 活在项目里」落地三刀。
  ① 最小任务投影：`tasks_for_projection` 只保留活跃任务与未被接替的 blocked/failed；
  delivered 与已 superseded 终态留在项目内（`sopctl task list`）。本仓 AGENTS 任务节
  从 ~54 条降至当前可执行切片（约 178→53 行）。② blocked 裁决链：`resolution_of` /
  `superseded_by_task` / `blocked_reason_code`；`task open --resolves` 双边写指针，
  旧契约仍终态。③ `delete_entry` 一等候选：`legacy_entry_alive` 达阈值 → deprecation
  候选；repair 目标偏向删/并入口；`metrics` 增加 structure_signals。顺手修生命周期测试
  在日历越过冻结日后、preview 前未打补丁即红的既有问题。521 测试全绿。
- 2026-08-30（Phase 6 件5 收尾·Rust 深度化）：rust_ast_scan（tree-sitter-rust，
  结构化引用 + use/mod 模块边）。rust-gate 的同名替身（tests/gate_test.rs 零 use）
  被 test_cannot_reach_consumer 识破转 gap/wired（CASE-027 翻转），经 use 闭合的
  真回归通过（新增 CASE-049）；MUT-012 守过报方向。词法判定归零至 .js 对照 1 条
  （基线：cases 49、structural 25、lexical 1、变异 12）。协作记录：本任务由 2h
  自动化会话开工（rust-gate 注册表/替身夹具/CASE-027 翻转/传感器与接线），主会话
  接手补完——修正 module_edges 的 mod_item 节点类型 bug（mod 边从未被提取）+
  补单元测试 + 基线/文档/提交收尾。
- 2026-08-30（Phase 6 开批·TS 深度化）：go_ast 模板复制到 TS——ts_ast_scan
  （tree-sitter-typescript，.ts/.tsx 结构化 + import 归一顶层名复用 Python 闭包
  机器），MUT-011 守过报方向；web-gate grounding lexical→structural（基线：
  cases 47→48、structural 21→23、lexical 3→2 = rust 1 + 新增 .js 词法对照
  CASE-048——.js 家族按设计永留词法层，语料永远看守词法自曝）。试跑抓到真 bug：
  export_statement 的函数体字符串曾被当模块说明符（改取 source 字段）。
- 2026-08-30（首个 enforced，垂直最后一步）：CTRL-001（.sopcontrol 写保护，
  AGENTS.md 硬约束规则化）走完手册 6.5 七条件——真实 opencode 会话（deepseek-v4-pro）
  经插件咨询 GUARD-CONTROLLER-WRITE 落盘 trace.jsonl（条件6/E4）、docs/ctrl-001.md
  确认书 + bypass 分析（条件5/7）、完成门 E4 实测（条件4），`explain CTRL-001` 可观测
  `absorption: enforced`。走查抓到真 bug：is_input_stale 对 harness.trace 落文件哈希
  兜底分支，每条 trace 行一落盘即 stale、账本视图永远丢失条件6——与 MATURITY/TEST_RUN
  同构修复 + 回归测试（TASK-0007）。TASK-0005/0006 双程 verified+delivered。
  注：TASK-0005 的契约曾因 CTRL-001 未登记而被 open 拒绝，重开后产生悬空
  contract_proposed 任务，后以 TASK-0006 完成闭环吸收。审计吸收分布随 E4 时效波动：
  普通 audit（无 E4）下 CTRL-001 显示 wired_and_tested，完成门 verify 后为 enforced。
- 2026-08-26（横向扩展前收口，d44b387）：六件评估工作 + R8 全部闭环，302 测试全绿，
  gate / project check 通过。件5 把变异验证从手工习惯变成机制（`corpus/mutations.yaml`
  + `tests/corpus/test_mutations.py`：每个负向对照必须在还原修复后变红，否则语料本身
  不算证据）；件6 把检测深度从标识符代理推到可达性（`plugins/detectors/reachability.py`
  接 import_graph，MUT-009 守住 R1 重命名绕过）。R8 实测出三个洞不是一个：本机文件系统
  大小写不敏感，`.SOPCONTROL/` 写的就是信任根而字面比对的守卫直接放行（harness 写入门、
  bash 门、repair 过滤三处 fail-open）；allowed_writes 目录里的 symlink 能把写落到树外，
  且 copy2 跟链接所以末节点自己是软链接也算逃逸。按纯函数宪法分三层修：`task.py`
  按分量 casefold（allow-list 刻意保持大小写敏感——归一化在 Linux 上会把 `SRC/` 放进
  `src` 范围，那才是 fail-open）、`worktree.resolves_inside` 碰文件系统、接在
  `repair.apply_repair` 的合并边界。
  用本产品的变异纪律验自己的修复，抓到两次假绿：`resolves_inside` 原先从 parent 起走，
  漏了「末节点自己是 symlink」（真 bug，还原后测试仍绿才暴露）；删掉 repair.py 里的
  接线后全套仍绿——守卫单测通过不等于守卫装上了，正是本产品要抓的 compiled_unwired
  出现在自己身上。补 `test_apply_repair_rejects_symlink_escaping_worktree` 后该变异转红。
- 2026-08-26（独立复查）：换会话独立复查 cdca464→e1ad148 共 22 笔提交。147 测试全绿、
  gate/doctor/self-test 通过、边界 1–8 未见违反（外仓仅投影 AGENTS/CLAUDE 两文件与
  `.sopcontrol/`，业务代码未动）。查出并修正两处文档漂移（README 声称 8 模式实为 10；
  R9 仍写"暂未实现 worktree 隔离"而 repair apply 已实现）——即本产品要抓的 docs-code
  drift 家族，出现在自己身上。
- 2026-08-26（立等 6–8）：JobsFlow 真仓控制面狗粮（用户授权）；Claude live 仍 401；
  worktree + repair apply 自动修复者 v0。
- 2026-08-26（立等续 1–5）：schema verdict；import_graph；cli_rules；project check；打包预习。
- 2026-08-26（立等 1–8）：场景3/lex_strip/cli 拆分/intake/CI/狗粮/Claude/对比。
- 2026-08-25（横向 C）：rust_scan；CI doctor；capability-compare；identity export/import。
- 2026-08-25（质量收口 B）：audit --compact；投影 SKILL 要点。
- 2026-08-25（质量收口 A）：B1 标题；14.1 分层；vertical-check 差异；场景2。
- 2026-08-25（第十轮）：小步 1–7。第九轮：垂直骨干役用闭环。14.1 有对应证据（含代理层）。

## Blockers

- （无）

## 运维记录（诚实登记）

- 2026-08-30（Go 深度化）：用户授权越过「仅 pydantic/PyYAML/pytest」依赖边界，
  引入 tree-sitter/tree-sitter-go；go_ast_scan 结构化证据 + reachability Go 分支 +
  MUT-010，go-gateway pass grounding lexical→structural（基线快照 6192d05→本次：
  structural 18→21 / lexical 5→3 / 用例 46→47 / 变异 9→10）。
- 2026-08-24：清理 eval 挂起时用宽泛 pkill 模式误杀了用户 OpenChamber.app 的两个
  opencode serve 常驻服务（8月10日启动）。此类守护通常按需重启，但属用户运行中应用——
  教训：杀进程前先 ps 确认归属，宁可重启自己的演习进程。
