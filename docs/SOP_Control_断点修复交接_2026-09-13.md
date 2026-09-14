# SOP Control 断点修复交接（2026-09-13 深夜）

## 0. 给接手者的第一条指令

本文档是《SOP_Control_独立修复执行手册》《双目标闭环手册》《MSE 支柱手册》三批成果的
**运行时断点修复**交接。修复会话在完成 12/16 项后被叫停，剩余工作与全部设计决策
在本文档中交接。先读 `sopcontrol-runtime-gaps-dualgoal-mse.md` 对应的断点清单编号
（D1/D2/D3/W1/W2/W3/B1-B9——见 docs/ 下三份手册与验收报告），再动手。

**勿自证完成**：接手后第一件事是跑 `pytest -q tests/logic`（当前 87 passed
/ 3 failed）与 `pytest -q tests/harness`，确认基线与本文 §2 状态一致，再动手。

## 1. 总体进度

| 状态 | 项 |
|---|---|
| ✅ 已修完（带测试） | D2、D1、K 语义、D3、W1+W2、缓存规则真缺陷、W3 |
| ✅ 代码就位（部分验证） | B2、B1、B7、B9、B3、B5 |
| 🔴 红测试待收尾 | test_mse_runtime.py 三个（同一根因，见 §3） |
| ⬜ 未开工 | B4、B6、B8、全量+覆盖率+gate 复验 |

## 2. 已完成的修复（全部在工作区，未提交）

工作区同时包含**实现者此前的未提交修复**（R-01..R-09 / 双目标 WP-A / MSE 四模块，
约 2500 行）与**本次断点修复**（约 700 行）。两者都已过逻辑测试（87 passed）。
建议 commit 时按批次拆分。

### 2.1 离线环（52.1 的 D/W 组）

- **D2 身份归一**：`sopcontrol/surface_inventory.py` `surface_identity` 尾部新增
  「绝对路径 argv[0] → basename」——`/usr/local/bin/curl` ≡ `curl`，仓库相对路径
  保留（同仓不同目录同名脚本仍是不同业务命令）。测试：`test_growth_joint_fixture.py`
  的 `test_surface_identity_ignores_wrapper_path` 重写为真断言（原为恒真式
  `assert id2 == id1 or id2 != id1`）+ 新增
  `test_surface_identity_absolute_install_path_is_not_identity`。
- **D1 重匹配**：`refresh_inventory` 对旧记录状态 ∈
  (observed, candidate, ambiguous, gap, blocked) 时改走 `_match_surface`；
  governed/mapped/waived 继续走 `_carry_over`。计数变量拆为
  new/retired/rematch_changed（避免被循环后 `changed_count = new+retired` 覆盖——
  这是修复时踩过的坑）。测试：
  `test_unresolved_surface_rematches_when_bridge_installed_later`。
- **K 语义**：`execution_logic.py` 重复策略检查新增
  `if prior.get("new_objects") is None: continue`——运行时未测量推进量时
  不得当作零推进，否则所有昂贵动作第二次执行都会被误阻断。测试：
  `test_repeated_strategy_unknown_progress_is_not_flagged`。
- **D3 operator accept 入 Registry**：`accept_operator_candidate` 写完
  `operators.yaml` 后注册 `MSE-<hash>` 规则并走
  observed→proposed→accepted→compiled 生命周期（与 surface accept 同路径，
  编年/投影随之）。surface 的 `rule_ref` 由 `operator:*` 改为 `MSE-*`
  规则 ID。测试 `test_mse_product.py::test_candidate_accept_binds_surface_to_operator`
  已更新为新约定并断言 Registry 中规则真实存在。
- **W1+W2**：`cmd_logic` plan 分支——`--declaration` 未传时自动读
  `.sopcontrol-local/logic/operators.yaml`；LineageStore 全量自动加载。
- **W3**：实现者已自行修掉（pending 报 operator_id）。

### 2.2 缓存规则真缺陷（本轮修复中发现的判定器 bug，非断点）

`execution_logic.py` 第 12 步原实现把「输入沿袭覆盖 consumes/preconditions」
当作缓存命中——但 `preconditions` 被证明恰恰是执行的**放行条件**。原语义下
任何前置已证明的昂贵步都被误判 cache hit（`unnecessary_steps`），场景 E 的
正常执行反而被阻断；运行时测试
`test_runtime_pass_with_lineage_executes_and_writes_output_lineage` 首跑就暴露。
已改为输出语义：缓存命中 = 同 goal digest + 同 operator 版本 + 输入集合
相交 + 产出字段/谓词被沿袭覆盖。测试
`test_valid_cache_precedes_recompute` 重写为新语义 + 新增目标变化失效分支。
另修 `op.digest()` → `op.digest`（property 非方法）。

### 2.3 运行时环（B 组，代码全部就位）

新函数/类（均在 `bridge.py`，run_bridge 之前）：

- `load_frozen_plan(root, plan_id)` — 读
  `.sopcontrol-local/logic/plans/<id>.json`（B9 冻结快照：plan/evaluation/
  **policy/goal/operators**）。
- `MseBlocked(Exception)` — challenge 路径的阻断信号。
- `_load_strategy_history(root, goal_digest)` — 从 receipts.jsonl 过滤
  type=="strategy" 的记录（B5 的数据源）。
- `mse_runtime_precheck(root, mse, plan_id)` → (refusal|None, logic_summary|None)：
  加载冻结计划 → 解析步骤（显式 step_id > operator 匹配 > 唯一昂贵步）→
  `check_expensive_step_admission` + 完整判定器补 repeated_failed_strategy →
  policy.mode=="block" 且 outcome ∈ (block, unproven) 时返回拒绝字典。
  **无冻结计划 → (None, None)：旧项目原路径，兼容不受影响。**
- `_persist_receipt(root, receipt)` — 追加到
  `.sopcontrol-local/logic/receipts.jsonl`（strategy 记录含
  fingerprint/goal_digest/new_objects/outcome）。
- `_write_output_lineage(root, mse)` — mse 提供输出元数据时经
  verify_lineage 落沿袭（B3）。

接线点：

- `run_bridge`：签名加 `plan_id=""`；classification 后、envelope 前调
  precheck（拒绝 → 落账并返回）；receipt 增加 `task_id`/`logic` 字段；
  三个执行段出口（timeout/OSError/正常）都调 `_persist_receipt`；
  executed 成功且有输出元数据时调 `_write_output_lineage`。
- `challenge_admission`：签名加 `plan_id`；precheck 阻断时抛 `MseBlocked`
  （不签发票据）。
- CLI `bridge run/challenge`：新增 `--plan-id`/`--mse-json`/
  `--mse-new-objects`；`cmd_bridge_challenge` 捕获 MseBlocked 输出
  `{"blocked": true, "logic": {...}}` 并 rc=1。
- `cmd_logic` freeze：快照增加 policy/goal/operators（B9）。
- `logic costs`：从 receipts.jsonl 聚合（B7），无记录如实报零。

测试状态：`pytest -q tests/logic` → **87 passed, 3 failed**（3 个失败
全部是 §3 的同一根因，见下）。阻断路径已实测通过：
`test_runtime_block_mode_refuses_unproven_expensive_step`——无沿袭时
`executed=False`、`policy_decision="mse:unproven"`、sentinel 未写。

## 3. 🔴 立即要收尾的三个红测试（同一根因，诊断链已推进到最后一步）

三个失败全在 `tests/logic/test_mse_runtime.py`（本轮新增）：
`test_runtime_pass_with_lineage_executes_and_writes_output_lineage`、
`test_runtime_strategy_history_blocks_second_failed_identical_strategy`、
`test_runtime_costs_aggregates_from_receipts`。

**失败签名（三处完全相同）**：
`assert receipt["executed"] is True, receipt.get("error")`
→ `"admission 未兑换：子进程未在真实入口兑换票据"`——MSE 判定已经放行
（这是既有 admission 语义正常工作），是**协作子进程没完成 admit**。

诊断链（已走完的部分）：

1. ✅ 已排除：fingerprint 失配——`canonical_invocation` 对单元素 child argv
   不剥壳，challenge fingerprint == 子进程内 argv fingerprint（实测相等）。
2. ✅ 已排除：child 无法 import sopcontrol——venv 以 editable 安装指向仓库
   （`sopcontrol-0.3.0.dist-info` 可证），child 在任何目录都能 import。
3. ⬜ **下一步（第一优先）**：打印 `receipt["stderr_tail"]`。run_bridge
   已捕获子进程 stderr（`stderr_tail` 字段，脱敏后 400 字符），child 里
   `admit_ticket` 的异常会原样出现在那里。用：
   ```python
   print(receipt["stderr_tail"])
   ```
4. 已知候选原因（按可能性排序）：
   a. **child 的 admit_ticket 调用抛出但脚本 traceback 被吞**——child 模板
      （`_freeze_full_loop` 内）的 admit 调用是
      `admit_ticket(root, ticket_file=tf, integration_id='fx.int', ...)`
      ——注意 `_write_output_lineage` 或 `_persist_receipt` 若在 challenge
      阶段之前抛错不会到 child；child 侧最可能是 **admit_ticket 内部校验
      失败**（对照 `bridge.py:771 admit_ticket` 签名：它可能要求
      `expected_*` 系列或与 challenge 的 mse 绑定一致性——run_bridge 的
      challenge 调用带 mse；child 的 admit 没带 mse → 若 admit 校验
      mse 一致性会失败；对照 `test_growth_joint_fixture.py::_admitting_child`
      （该 helper 在同套件通过）与我的模板逐行 diff——**关键差异：那个
      helper 把 child 写进 product 目录内，我的写在 tmp_path 外**；另外
      它传 `task_id=%r` 的值来自参数而我硬编码 'T1'——需要确认
      challenge_admission 用的 task_id 是否也是 'T1'（run_bridge 传的
      task_id='T1' ✓）。
   b. admit 与 challenge 的 `operation_id` 失配——challenge 现在带
      `mse_runtime_precheck` 之后的行为是否改变了 operation payload？
      （precheck 只读不写；但 challenge_admission 内部的 mse 传递我的
      接线未改动——对照 git diff。）
5. 收尾做法：修好 child 后，三个测试应全绿；若 strategy 测试仍红，
   检查 `_persist_receipt` 的 strategy 记录是否带 `new_objects=0`
   （测试传了 0，outcome=failed——judge 需要 goal_digest 匹配，
   `_load_strategy_history` 按 goal_digest 过滤；确认 mse 里
   `goal_digest` 与 frozen goal 的 digest 一致，测试用
   `_goal_digest_of(frozen)` 计算，应一致）。

## 4. 剩余工作清单（按优先序）

### B4：task.py 绑定 goal/plan digest（~30 分钟）

- `Contract` 增加字段 `goal_digest: str = ""`、`execution_plan_digest: str = ""`。
- `task open` CLI 增加同名旗标，写入合同。
- `takeover_pack` 输出二者（换会话可续接）。
- 验收测试：open 带旗标 → task show 可见；不带 → 行为不变（空=未绑定，
  不引入新门槛）。
- 手册依据：MSE 手册 §8.5「task.py 绑定 GoalContract digest；绑定初始
  ExecutionPlan digest；状态转换中校验计划更新」。

### B6：control_result 门控后置条件（~30 分钟）

- `ControlResult` 增加字段 `postconditions: list[str] = []`
  （结果证据中已满足的后置条件 id）。
- `GateState` 增加 `expected_required_postconditions: list[str] = []`。
- `decide_control_result`：仅当 `state.expected_required_postconditions`
  非空时对比——缺项 → outcome unknown（不得 pass）；
  **空=不绑定，不对旧结果生效**（否则所有存量结果全部变 unknown，会
  摧毁兼容性——这是 B6 的安全设计底线）。
- 接线：`run_task_verify` 从 task 合同的 `execution_plan_digest`
  （B4 落地后）加载冻结计划的 `required_postconditions` 传入 state；
  未绑定时 state 字段为空。

### B8：doctor MSE 诊断节（~20 分钟）

`cmd_doctor` 增加 MSE 段（横切只读，不改判定）：
- 多少 surface 缺 OperatorContract（inventory 中 unresolved 且 kind∈cli/script/adapter）；
- 高成本未声明依赖的 operator 数（contract.cardinality.effect=="unknown"）；
- GoalContract 编译失败数（`sopctl logic goal` 曾失败——本地无法静态枚举，从
  `logic/goal-*.yaml` glob 逐个 validate）；
- 冻结计划数 / 回执数 / strategy 记录数；
- 每一项给出下一动作（如 `sopctl logic operator candidates`）。

### 全量复验（~20 分钟，勿跳过）

```
.venv/bin/pytest -q                       # 全量（~1116+新增，注意缓存规则改动可能波及）
.venv/bin/pytest -q --cov --cov-branch    # ≥85（当前工作区 85.76%）
.venv/bin/ruff check sopcontrol plugins tests
git diff --check
.venv/bin/python -m sopcontrol.cli gate .
.venv/bin/python -m sopcontrol.cli project check .
.venv/bin/python -m sopcontrol.cli chronicle check .
```

注意：本次修复改了 `execution_logic.py` 缓存规则与 12 步判定聚合，
全量如果有其他套件断言了旧的（错误的）缓存语义，修断言 **前先确认新语义
才是手册 §5.4 的本意**（输出缓存，不是输入覆盖），不要为了绿灯回退修复。

## 5. 修复中确立的设计决策（不要回退）

1. **缓存判定对象=本步输出**（same goal/operator/输入集合），不是输入覆盖。
2. `new_objects=None`（未测量）≠ 零推进——运行时未测量时不得触发
   repeated_failed_strategy，否则任何昂贵动作第二次执行必被误断。
3. 无冻结计划 = 旧项目路径（§29.1），`mse_runtime_precheck` 直接放行——
   兼容是设计约束，不是偷工。
4. enforcement 档位来自冻结时的 `--mode`（存进 frozen 文件的 policy）；
   默认 observe 只记录不阻断。
5. `logic operator accept` 必须（经 D3）写 Registry；operators.yaml 只是
   机器可读缓存（与 bridge-rollback manifest 同层）。
6. plan check 的 lineage/operators 自动加载默认开（arg `--with-lineage`
   的默认值是 True）；显式传 `--declaration` 时以用户文件为准。

## 6. 风险与注意事项

- **工作区堆叠未提交**：三批手册修复（前会话）+ 本次断点修复同树未提交，
  共约 3724 行。commit 前先 `git diff --stat` 分块核对；建议先落前会话
  成果，再单独 commit 断点修复（文件级重叠主要在 `bridge.py`/
  `execution_logic.py`/`cli_logic.py`/`surface_inventory.py`——如需拆分
  按 hunk 而非文件）。
- **并发写入波**：修复期间另一会话仍在叠加（dynamic_sop/cli_dynamic/
  upgrade 模块，最后活动 22:08）。开工先 `git status` + mtime 检查；
  `cli.py` 顶部 `from .cli_dynamic import *` 与本次修复无冲突但会一起进 diff。
- `bridge.py` 的 `_persist_receipt`/`_write_output_lineage` 内嵌了
  `datetime` 模块级导入（`from datetime import datetime, timezone`）
  ——若与后续改动冲突，保住这个导入。
- `logic costs` 的 `task_id` 匹配键：回执落账用
  `receipt["task_id"] or receipt["integration_id"]`——CLI 调 `bridge run`
  时省略 `--task-id` 的记录会归到 integration_id 下；costs 查询按
  显式 task_id 过滤，两侧行为对称即可。
- fcntl/Rock 锁语义未改；本次修复不触碰 `.sopcontrol/`（全部落
  `.sopcontrol-local/` 或生产代码），gate 应保持绿色。

## 7. 完成定义

三个红测试绿 + B4/B6/B8 落地带测试 + 全量/覆盖率(≥85)/ruff/diff-check/
gate/project check/chronicle check 全绿 → 按 MSE 手册 §31 口径，运行时层
四断点（B1/B2/B3/B5/B7/B9）闭合，MSE 可升格为「支柱能力运行时已接线」；
B4/B6 完成后 §8.5 的六接点全部落地（action_model/action_plane 保持原状——
接点职责已由 bridge/tickets 承接，手册原文允许「按最小范围修改」）。
修完按三批手册的验收报告格式回报证据（命令+数字），不接受「已修完」三字。
