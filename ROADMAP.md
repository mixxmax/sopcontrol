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

### B1 终点执行器 — 进行中
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
- [x] 任务语料 `corpus/task_cases.yaml`（8 用例）：14.1 场景 2/5/8/9/11/15 + 两个正向对照；场景 1/6/7 依赖 harness/模型层，归 B4
- [x] 意图编译器 v0：`sopctl intake` 文档 MUST 句 → CandidateRule（observed，永不写注册表；强度建议区分必须/不得）
- [x] 宪法测试补：迁移门纯度（炸 open）、拒绝可解释、路径规范化拒绝 `..`/绝对路径
- 验收：47 测试全绿；CLI 全生命周期实测（契约→执行→gap 修复轮→接线→verified→delivered）
- 实测捕获的真 bug 两枚：完成门曾按全项目口径连坐无关规则 fail；CLI open 误引用 args.changed（API 层测试测不到的接线 bug）

### B3 有界修复
- [ ] gap contract → 最小影响范围 → 隔离 worktree → 独立验证
- [ ] 重复指纹熔断（Finding.fingerprint 已就位）：同指纹两轮 → 转人工（Blockers 机制同款）

### B4 校准与投影
- [ ] capability handshake（JSON/边界遵循/hook 可用性的合成评测）
- [ ] 模型切换接管包；Rulesync 式平台投影

## 状态（每次运行后更新）

- 2026-08-23 深夜（会话内连续自驱，定时任务已按用户要求删除）：B2 完成。47 测试全绿，三笔里程碑提交。下一步：B3 有界修复首项（gap contract → 重复指纹熔断已就位，Finding.fingerprint 可直接用）。

## Blockers

- （无）
