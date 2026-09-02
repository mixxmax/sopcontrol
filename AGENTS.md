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

## 任务状态（当前可执行切片；全量历史在项目内：`sopctl task list` / `task show` / `task takeover`）
- TASK-0002 [blocked] 骨架收口两件：1) 判定输出带证据强度自曝（structural/lexical/mixed）——跨语言 pass 必须
  完成定义: SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: （终态）人工裁决后另开任务
  ⚠ 已阻断（other）；另开决议任务：`sopctl task open --resolves TASK-0002 ...`
- TASK-0044 [verified] 第七批 7A：建立可逆生命周期数据模型、固定时点有效性与仓库相对路径 scope 纯函数，保持旧 registry 兼容
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: deliver
- TASK-0045 [verified] 第七批 7B：实现 suspend、reinstate、narrow 的内容寻址预览确认、并发安全写入、幂等与普通写入口
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: deliver
- TASK-0046 [verified] 第七批 7C：新增 suspend、reinstate、narrow CLI 和统一 Registry+AGENTS+C
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: deliver
- TASK-0047 [verified] 第七批 7D：统一固定时点 effective rules 与路径 scope 消费，接入 audit、verdict、
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: deliver
- TASK-0048 [verified] 第七批 7E：生命周期 revision 绑定 attestation 与 trace 新鲜度，同步公开文档、残余风险和
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: deliver
- TASK-0049 [verification_pending] 第七批 7E 测试迁移：确认书正例使用 Registry 权威 revision，并补 attestation/trac
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: verify
- TASK-0050 [verification_pending] 第七批 7D 测试补充：验证 task open/accept 与 repair open/apply 对 effect
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: verify
- TASK-0051 [verification_pending] 第七批审查修复：封闭 Registry 普通写旁路、attestation 伪造与越界、自签提级、trace 交叉续命、
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: verify
- TASK-0052 [verification_pending] 第七批审查加固：静态保证生产传感器路径 Evidence kind 与 PATH_SCOPED_EVIDENCE_KIN
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: verify
- TASK-0053 [verification_pending] 第七批审查兼容迁移：将退休测试从已封闭的普通 save 旁路迁移到 transition 与 record_attest
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: verify
- TASK-0054 [verification_pending] 第七批第二轮审查修复：保护 retirement facts，拒绝 attestation 路径任意 symlink，原
  完成定义: CTRL-001, SELF-001, SELF-002 全部 pass；修复预算: 0/1；合法动作: verify

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
