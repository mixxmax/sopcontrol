<!-- sopcontrol:v1 -->
# SOP Control 规则投影（自动生成，勿手改）

权威源: `.sopcontrol/rules/registry.yaml`；规则变更后运行 `sopctl project all` 刷新本节。
本节只是指导——真正的拦截在 git pre-push 钩子、CI gate、运行时 hook 与 `sopctl gate`。

## 控制成熟度：L4 Govern：规则变更、发布和高影响操作需双阶段确认
- 五项基本秩序全部有机制。
- 明细与依据: `sopctl bootstrap`。低于 L3 时门以建议为主，沉默不等于许可。

## 必须遵守的规则
- [SELF-001][MUST] 检测模式 write_only_state 必须在生产代码接线并具备回归测试 （生产消费者标记: finding_write_only_state）
- [SELF-002][MUST] 检测模式 state_in_parallel_files 必须在生产代码接线并具备回归测试 （生产消费者标记: finding_state_in_parallel_files）
- [CTRL-001][MUST] 控制器状态目录 .sopcontrol/ 内任何文件不得直接读写或修改，一切写入必须经 sopctl 子命令 （生产消费者标记: touches_protected_path, check_tool_call）

## 任务状态（换会话/换模型先看这里；以下即全量信息，无需再用命令查询任务）
- TASK-0001 [delivered] 扩展检测模式库：两个状态健康模式（接线+跨域语料+回归测试）
  完成定义: SELF-001, SELF-002 全部 pass；修复预算: 0/2；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件
- TASK-0002 [blocked] 骨架收口两件：1) 判定输出带证据强度自曝（structural/lexical/mixed）——跨语言 pass 必须
  完成定义: SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）人工裁决后另开任务
- TASK-0003 [delivered] 对 TASK-0002 已提交基线（commit 6192d05：证据强度自曝+语料基线快照）运行完成门独立复核：本任务
  完成定义: SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件
- TASK-0004 [delivered] Go 深度化（用户 2026-08-30 授权越过依赖边界引入解析器）：go_ast_scan 传感器（tree-sit
  完成定义: SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件
- TASK-0005 [delivered] 首个 enforced（垂直最后一步）：把 AGENTS.md 硬约束「不得直接写 .sopcontrol，一切经 so
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件
- TASK-0006 [delivered] 首个 enforced（垂直最后一步）：CTRL-001（.sopcontrol 写保护，guard: GUARD-CO
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件
- TASK-0007 [delivered] 修复首次 enforced 走查发现的真 bug：is_input_stale 对 harness.trace 证据落进
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件
- TASK-0008 [delivered] Phase 6 第一批·TS 深度化（照 Go 模板复制）：ts_ast_scan 传感器（tree-sitter-ty
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件
- TASK-0009 [delivered] Phase 6 件5 收尾·Rust 深度化（Go/TS 模板复制）：rust_ast_scan 传感器（tree-si
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件
- TASK-0010 [delivered] 件5收尾·Rust 深度化（Go/TS 模板复制）：rust_ast_scan 传感器（tree-sitter-rust
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件
- TASK-0011 [delivered] 编写“活在项目里”的可进化确定性空间技术手册：阐明构想、双向生命周期、现有代码改造路线、未来演进规则与项目持久化实现
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）无
  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件

## 硬约束
- 不得直接读写或修改 `.sopcontrol/` 内任何文件；一切经 `sopctl` 子命令。
- 完成任务前运行 `sopctl gate`（若不在 PATH：`python -m sopcontrol.cli gate`）；fail 判定或账本篡改会阻断推送。
- 用户若说「只讨论不修改」，不得改任何文件（会话意图 discuss_only）。

## 与控制器配合（SKILL 要点）
- 先读本投影；规则/账本/任务变更只经 `sopctl`，禁止手改 `.sopcontrol/`。
- `task submit` 若契约有 MUST 字段，必须带齐 `--field key=value`（漏字段会被拒）。
- 不要用自报「已完成」代替 `task verify` / `gate`；已 `delivered` 的任务勿重做副作用。
- 不要卸 hook/插件（提权，需人工）。日用全序见仓库 `PLAYBOOK.md` / `SKILL.md`。
<!-- /sopcontrol:v1 -->
