# SOP Control 自动学习双入口实施报告（PROMPT-A §12）

## A. 结论

- 状态：**Complete**（PROMPT-A 范围内；真模型与真宿主诚实标 UNPROVEN）
- 自动观察：PASS（零 LLM/零 ticket/零弹窗/不写 Registry）
- 窗口级汇总：PASS（归并，非复制；冲突拆分；同义去重）
- LLM Distiller：PARTIAL（fake 确定性 PASS；真模型 UNPROVEN，无接入通道）
- 提案确认：PASS（六路由；control 经候选箱；defer 可复决）
- /learn 入口：PASS（同一管道；review/list/show/decide/ingest/diagnose/notify）
- 控制层生命周期：PASS（confirm→accepted→compile→select；无 TTL）
- 文档/控制分流：PASS（独立 digest/生命周期；投影禁回灌）
- Notification Seam：PARTIAL（结构化卡片 + CLI outbox PASS；真弹窗 UNPROVEN）

## B. 修改清单

- `sopcontrol/learning.py`（新建，P0-B～P2-C/P3b/P4）：
  Event/Window/Bundle/Proposal/Decision 严格模型；转换函数；
  聚合器（脱敏/归并/去重/冲突/关联旧规则）；触发器（TriggerConfig 集中阈值）；
  Distiller 接口 + fake + UNPROVEN stub + 超时/schema 回退 + §7.6 校验；
  提案 store + 六路由决定（control 经 CandidateStore）；通知接口 + CLI outbox；
  /learn 回顾 + 外部导入（禁回灌）；文档区读写；预算/度量/诊断；单窗口提炼幂等。
  测试：`tests/dynamic/test_learning.py` 40 项。
- `sopcontrol/cli_learn.py`（新建，P3）+ `cli.py`（learn 七子命令注册）：
  review/list/show/decide/ingest/diagnose/notify，通知卡片 JSON 形态按手册 §6。
  测试：`tests/dynamic/test_learn_cli.py` 3 项。
- 未建第二套候选/确认/Registry：control 路由复用 `CandidateStore.upsert` +
  `dynamic_sop.confirm/compile`；文档路由只给 payload。

## C. 真实演示（/tmp/prompta-demo，命令见 §B，可重跑）

自动路线：`dynamic observe`（“以后纠正都必须先台账后评分”，candidate_high，
CAND-3718f736182a86b）→ `learn review --session demo-s1`
（window lwin-8023034e208eeb59，events 1，proposals 1，adapter fake）。
/learn 路线：`learn list`（lprop-94ab1287e74e00ec，proposed，evidence lev-…）→
`learn notify --json`（interrupt false，“尚未生效”，五决定）→
`learn decide --route document` → confirmed，doc_payload 保留 exceptions/non_goals。

## D. 成本

- 正常路径 LLM=0（无模型导入；默认 fake；Metrics token 恒零）。
- 每窗口 Distiller 最多一次：同窗口同证据幂等命中（distill_calls 0），证据变才可再调。
- 延迟：纯函数毫秒级；提炼超时默认 10s 回退 fake。
- 弹窗率：UNPROVEN（无真实宿主；outbox 深度可查 `learn diagnose`）。
- 接受率：`learning_diagnose` decision_rate（如实计数）。

## E. 负向证据（均为实跑测试）

- 无证据/坏 schema/引用越界/scope 扩大/must↔must_not 冲突 → 拒（§7.6）。
- once_only 证据路由 control → 拒；终态复决 → 拒。
- 外部投影内容/空 statement 导入 → 拒。
- 未点击≠接受（proposed 保持，通知不改状态）；defer 不过期、可复决。
- 不同目标不合并；单句不自冲突（复查 F1 修过真误报）。
- Registry 写操作：源码级断言禁 `registry.add/save/transition`。
- secret 脱敏：email/sk-/secret= 落包前替换（测试锁定）。
- 常驻监督：源码级断言无后台线程/定时/死循环。

## F. 发布信息

```
SOPCONTROL_VERSION=0.3.0
SOPCONTROL_COMMIT=2eab4a2（代码冻结；本报告提交为其子提交，禁 push 遵守未推送）
PACKAGE_DIGEST=69ffaf46902d3fab589c9ecb21b40e7e12dd77385ed2d287c43f7550f41cae71
PACKAGE_FILE=/tmp/sopcontrol-wheel-prompta/sopcontrol-0.3.0-py3-none-any.whl
```

- 全量：1254 passed + 1 skipped；ruff 全绿；diff-check 全绿；gate 通过。
- 干净环境冒烟：WP-I 链（py3.12 venv + wheel + init/attach/observe/confirm/sync/rollback/doctor）此前已证；本轮 wheel 同源码树构建。

## G. 未完成

1. 真 LLM Distiller：无仓库内模型通道，`UnprovenLLMAdapter` 显式抛 UNPROVEN。
   关闭条件：项目获准模型接入方式后实现 adapter 并跑 §7.6 全项。
2. 真宿主弹窗送达：`HostUiAdapter` 抛 UNPROVEN；CLI outbox 为降级。
   关闭条件：宿主联调后送达回执入账。
3. PROMPT_B（JobsFlow 侧更新 vendor 并接入）：本任务禁动 JobsFlow，
   docs 下已见 `PROMPT_B_JobsFlow侧_更新Vendor并接入自动学习.md`，属后续任务。
4. Win/Linux runner：只能标 unproven（WP-J 口径）。
