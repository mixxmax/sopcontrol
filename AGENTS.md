<!-- sopcontrol:v1 -->
# SOP Control 规则投影（自动生成，勿手改）

权威源: `.sopcontrol/rules/registry.yaml`；规则变更后运行 `sopctl project all` 刷新本节。
本节只是指导——真正的拦截在 git pre-push 钩子、CI gate、运行时 hook 与 `sopctl gate`。

## 控制成熟度：L2 Validate：schema/test 不通过则不宣称完成
- 未达下一级 L3：补齐 ORDER-2：装了运行时拦截或 git 钩子，且至少一条生效规则声明了 guard_ids
- 明细与依据: `sopctl bootstrap`。低于 L3 时门以建议为主，沉默不等于许可。

## 必须遵守的规则
- [SELF-001][MUST] 检测模式 write_only_state 必须在生产代码接线并具备回归测试 （生产消费者标记: finding_write_only_state）
- [SELF-002][MUST] 检测模式 state_in_parallel_files 必须在生产代码接线并具备回归测试 （生产消费者标记: finding_state_in_parallel_files）

## 任务状态（换会话/换模型先看这里；以下即全量信息，无需再用命令查询任务）
- TASK-0001 [delivered] 扩展检测模式库：两个状态健康模式（接线+跨域语料+回归测试）
  完成定义: SELF-001, SELF-002 全部 pass；修复预算: 0/2；合法动作: （终态）无
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
