<!-- sopcontrol:v1 -->
# SOP Control 规则投影（自动生成，勿手改）

权威源: `.sopcontrol/rules/registry.yaml`；规则变更后运行 `sopctl project all` 刷新本节。
本节只是有损切片——真正的拦截在 git pre-push 钩子、CI gate、运行时 hook 与 `sopctl gate`。

## 新会话恢复（先读这里）
1. 权威在项目 `.sopcontrol/`；模型上下文不是记忆本体。
2. 只推进「当前链头」里的合法动作；不要重做已交付副作用。
3. 全量历史与接手包：`sopctl task list` / `task show <id>` / `task takeover <id>`。
4. 本切片摘要: `9ed432ba4ee99358`（漂移时 `sopctl project check` 会报 stale）。
5. 项目何以至此：见下节；全量编年 `sopctl chronicle`。

## 何以至此（换模型/换会话）
- 编年 554 条（完整性 OK）；下列为最近 5 条治理动作：
- [2026-09-14T05:42] TASK-0146 开任务
- [2026-09-14T05:42] TASK-0146 contract_proposed→executing（accept）
- [2026-09-14T05:49] TASK-0146 executing→verification_pending（submit）
- [2026-09-14T05:54] TASK-0146 verification_pending→verified（verify）
- [2026-09-14T05:55] TASK-0146 verified→delivered（deliver）
- 全量：`sopctl chronicle`；核对：`sopctl chronicle check`。

## 空间生长（无感观察；定型需人）
- 空间生长（无感）：观察 0；待人定型候选 0（删入口 0 / 改善入口 0 / 登记规则 0）
- 发现已自动；写入权威或删代码仍需人确认——不是要你「推进发现」。
- 最近空间快照：ambiguity_index=0 （旁路开 0 / 平行状态 0）
- 相对上一帧：歧义指数未变：ambiguity_index=0（`sopctl growth diff`）
- 明细：`sopctl growth status|measure|diff`；全量候选：`sopctl candidate list`；中途接入看 `sopctl doctor`（默认轻量，全量加 `--full`）。

## 控制成熟度：L4 Govern：规则变更、发布和高影响操作需双阶段确认
- 五项基本秩序全部有机制。
- 明细与依据: `sopctl bootstrap`。低于 L3 时门以建议为主，沉默不等于许可。

## 必须遵守的规则
- [SELF-001][MUST] 检测模式 write_only_state 必须在生产代码接线并具备回归测试 （生产消费者标记: finding_write_only_state）
- [SELF-002][MUST] 检测模式 state_in_parallel_files 必须在生产代码接线并具备回归测试 （生产消费者标记: finding_state_in_parallel_files）
- [CTRL-001][MUST] 控制器状态目录 .sopcontrol/ 内任何文件不得直接读写或修改，一切写入必须经 sopctl 子命令 （生产消费者标记: touches_protected_path, check_tool_call）

## 当前链头（可执行切片）
- 上限 5 条明细；verified 折叠；摘要 `9ed432ba4ee99358`
- TASK-0077 [blocked] 细分市场发布准备：关闭 REL-001（cli_product 缺 sys 导入+超预算分支测试）、REL-002（co
  执行者: （未绑定）；完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）人工裁决后另开任务
  为何在切片: 未接替阻断（other）；需 --resolves 另开决议
  ⚠ 已阻断（other）；另开决议任务：`sopctl task open --resolves TASK-0077 ...`
- TASK-0002 [blocked] 骨架收口两件：1) 判定输出带证据强度自曝（structural/lexical/mixed）——跨语言 pass 必须
  执行者: （未绑定）；完成定义: SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）人工裁决后另开任务
  为何在切片: 未接替阻断（other）；需 --resolves 另开决议
  ⚠ 已阻断（other）；另开决议任务：`sopctl task open --resolves TASK-0002 ...`

## 硬约束
- 不得直接读写或修改 `.sopcontrol/` 内任何文件；一切经 `sopctl` 子命令。
- 完成任务前运行 `sopctl gate`（若不在 PATH：`python -m sopcontrol.cli gate`）；fail 判定或账本篡改会阻断推送。
- 用户若说「只讨论不修改」，不得改任何文件（会话意图 discuss_only）。

## 与控制器配合（SKILL 要点）
- 先读「新会话恢复」与「当前链头」；规则/账本/任务变更只经 `sopctl`。
- `task submit` 若契约有 MUST 字段，必须带齐 `--field key=value`（漏字段会被拒）。
- 不要用自报「已完成」代替 `task verify` / `gate`；已 `delivered` 的任务勿重做副作用。
- 不要卸 hook/插件（提权，需人工）。日用全序见仓库 `PLAYBOOK.md` / `SKILL.md`。
<!-- /sopcontrol:v1 -->
