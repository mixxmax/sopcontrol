# SOP Control 剩余工作快速收尾 Prompt

你接手的是一个已经完成大部分实现、但尚未完成最终接线和发布整理的仓库。目标不是重构或重做手册，而是以最少改动将当前批次收口。

仓库：`/Users/xiezhijie/sopcontrol`

当前基线：

- 分支：`zcode/living-project-batch1`
- HEAD：`4f864a4`
- 当前分支相对远端约 ahead 20；未经用户明确授权不得 push、打 tag 或发布。
- 工作区已有用户/前序模型改动，必须保留，不得 reset、checkout 或覆盖。
- `.sopcontrol/` 是受保护状态；不得直接读写，其中任何变更只能经 `sopctl` 子命令完成。

## 一、已经完成，禁止重做

以下内容已有实现、提交和定向测试证据，只做回归，不再重新设计：

1. A1 平台证据分级、诚实支持矩阵和 README badge 清理；旧 TASK-0148 已由已交付的 TASK-0154 接替。
2. A2 `init` 残缺布局修复、幂等和 CLI 位置参数回归；旧 TASK-0149 已由已交付的 TASK-0156 接替。
3. 统一规则选择器、选择证据标识、规则冲突说明的内部实现。
4. 动态 SOP：观察、候选、可信用户确认、编译、永久保存、重载、显式退役。
5. 可信确认凭据：绑定、过期、重放、跨项目、secret 权限与不泄露。
6. 未知/畸形写动作 fail-closed；只读未知动作保持可观察。
7. CandidateStore 文件锁和原子保存；账本措辞不再夸大为防篡改。
8. 自然逻辑/MSE：昂贵步骤前置、先缩小集合再评分、票据绑定、运行时阻断。
9. 两个本地 reference host fixture 已存在；定向复核共 `126 passed`。

不要为了“统一风格”重写上述模块，不要再逐工作包跑全量测试，也不要新增替代性框架。

## 二、唯一必须修复的功能缺口：选择器进入真实运行入口

静态检查显示：

- `sopcontrol/rule_select.py::decide_action_with_rules` 已实现；
- 但 `sopcontrol/cli_harness.py` 和 `sopcontrol/harness.py` 仍直接调用 `evaluate_payload`；
- 因而永久规则能被保存、能被独立选择，却未被证明会在真实 harness admission 中自动参与判定。

请完成以下最小接线：

1. 在真实 harness/admission 入口加载当前项目的有效规则，构造稳定的选择上下文，至少包含可得的 `product/project`、`action/operation`、`phase`、`target/path`、`task_id`。
2. 将入口判定统一经过 `decide_action_with_rules`；不得在 adapter 中复制第二套选择逻辑。
3. 保持现有无规则场景行为不变；加载失败或上下文不足时按现有风险语义处理，不得伪造“规则已执行”。
4. `selected rule ids → decision → selection_evidence → activity log/receipt` 必须使用同一标识链。
5. 冲突规则必须返回 `ask/needs_user`，不得自行裁决；未接线规则必须明确为 observe/unwired，不得冒充 enforce。
6. 不得让普通只读热路径新增 LLM 调用、ticket 或显著 I/O。

至少增加三个生产入口测试：

- 已确认并编译的动态 SOP，在 selector 匹配时通过正式 harness 入口被选中并影响判定/证据；
- selector 不匹配时规则存在但不激活，并给出可解释原因；
- 相同范围的 MUST/MUST_NOT 冲突经正式入口返回 `ask`。

测试不得只调用 `select_rules_for_action` 或 `decide_action_with_rules` 纯函数来冒充生产接线。

## 三、把已经写完的工作正式结案

1. 用 `sopctl task show` 确认 TASK-0158、TASK-0159 的提交内容。
2. 在上述真实接线完成并通过定向测试后，分别通过合法 `sopctl task verify` / `deliver` 流程结案；若当前任务写入范围不覆盖新接线文件，只为真实接线另开一个收尾任务，不得篡改旧任务范围。
3. TASK-0148、TASK-0149 已有接替任务，不要再次修复或复活。
4. 不要为每个测试、文档或小修复另开任务；最多新增一个“运行入口接线与发布收口”任务。

## 四、一次性整理未跟踪成果

检查并合理纳入同一收尾提交：

- `corpus/fixtures/reference-host-cli/`
- `corpus/fixtures/reference-host-worker/`
- `tests/harness/test_perf_baseline.py`
- `docs/SOP_Control_平台支持矩阵_2026-09-18.md`
- 当前手册及本 prompt（若项目决定保留）

要求：

- 删除两个 fixture 下生成的 `__pycache__`/`.pyc`，不得提交生成物；
- reference host 文档继续明确“不是 JobsFlow 或真实商业宿主证据”；
- 性能测试只使用宽松、抗噪声上限，不把单机数字宣传成跨平台承诺；
- 平台矩阵继续将 Linux、Windows、Cursor 等无真实 runner 的项目标为 `UNPROVEN`。

## 五、只运行一轮分层验收

先跑定向测试，失败才修：

```bash
.venv/bin/python -m pytest -q \
  tests/harness/test_rule_select.py \
  tests/harness/test_entry_boundary.py \
  tests/harness/test_confirmation.py \
  tests/harness/test_evidence_semantics.py \
  tests/dynamic/test_dynamic_sop.py \
  tests/logic/test_mse_runtime.py \
  tests/logic/test_mse_judge.py \
  tests/harness/test_perf_baseline.py
```

然后只在所有代码与文档都已稳定后运行一次最终门：

```bash
.venv/bin/python -m ruff check sopcontrol tests
.venv/bin/python -m pytest -q
git diff --check
.venv/bin/sopctl project check .
.venv/bin/sopctl chronicle check .
.venv/bin/sopctl gate .
```

不得在每个小步骤后重复全量 pytest 或 gate。若全量测试因机器负载超时，先记录资源/退出码，再在负载恢复后只重跑一次；不得把超时伪报成代码失败或成功。

## 六、JobsFlow 与远端边界

本次快速收尾不重做 JobsFlow 业务功能。若本机存在 JobsFlow，可在隔离副本仅做一次最小 smoke：确认其实际导入/固定的 SOP Control 版本、一个只读动作、一个受控写动作、一个动态 SOP 激活证据。没有条件则明确标为 `UNPROVEN`，不得因此阻塞本仓库代码收口。

未经用户明确授权：

- 不更新 JobsFlow vendor/pin；
- 不 push；
- 不打 tag；
- 不发布 PyPI/GitHub Release。

## 七、最终交付格式

只输出一份简短报告，包含：

1. 新增/修改文件与 commit；
2. 生产入口接线证据（入口名称、选中规则 ID、`selection_evidence`、最终 decision）；
3. TASK-0158/0159 的最终状态；
4. 定向测试、全量测试、ruff、project/chronicle/gate 的准确结果；
5. 未提交生成物为零，工作区状态；
6. 仍为 `UNPROVEN` 的外部项；
7. 明确说明是否已 push/tag/release。

完成标准不是“所有设想都实现”，而是：永久规则真正进入实际运行门、现有两个待验任务合法结案、未跟踪成果整理干净、最终门只跑一次且结果真实。
