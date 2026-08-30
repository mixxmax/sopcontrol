# ROADMAP — 自主推进的权威状态源与决策规则

状态在模型上下文之外持久化——这正是本项目的第一原则，也适用于推进本身。
每次自主运行：读本文件 → 按规则选下一项 → 执行 → 自检 → 更新状态 → 提交。

## 边界（自主运行不得违反；本节不得修改）

1. 只在 `/Users/xiezhijie/sopcontrol` 内工作；不改外部仓库（含 ai-job-search）。
2. 不 push、不发布、不引入超出 pydantic / PyYAML / pytest 的新依赖。
3. 脊柱（`sopcontrol/`）零 LLM；判定器（`verdict.py`）零 I/O（宪法测试守卫）。
4. 每个新检测模式必须同步新增语料用例（优先跨领域夹具）；无语料的模式不算完成。
5. 同一问题连续两次修复失败 → 在「Blockers」登记并跳过，不得无限返工。
6. 测试不全绿不得提交；提交信息用 `[B阶段]` 前缀。
7. 保持克制：先闭环后带宽；拒绝防御性脚手架、feature flag 与面面俱到。
8. 对既有判决不重新诉讼：DESIGN.md 已定的决策直接执行，除非实践证明其错误。

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
- [x] `sopctl task open/accept/submit/verify/deliver/show/list`：范围走私拒绝、完成门只信 E3 审计、修复熔断（默认两轮）、revision 防旧覆盖
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
  调节 `max_repairs`/`allowed_writes` 粒度；`sopctl capability-eval --fixture` 离线闭环；
  `task open` 读 `.sopcontrol/model-profile.yaml`（显式 `--max-repairs` 优先）；DESIGN §11
- 剩余：codex 出现运行时钩子后升级其画像；真实模型探针（可选，本切片不强制烧 token）
- claude 适配保留：用户环境无 key（不修），有 key 环境可直接实测

### B5 模式库扩展 — 完成（2026-08-24 凌晨，经任务机自应用交付）
- [x] `write_only_state`（只写不读代理，info；shop + jobflow 双域）
- [x] `state_in_parallel_files`（双处维护，gap；shop + ci 双域）
- [x] `state_marker_absent`（声明状态不存在，info）
- [x] Rule.state_markers 字段；verdict 对状态类规则显式"不适用吸收等级"（不猜）
- [x] TASK-0001 全流程：契约→范围检查→完成门独立审计 SELF-001/002→delivered（自应用首次真实闭环）

## 状态（每次运行后更新）

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
