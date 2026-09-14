# SOP Control 0.4.0 最终发布与运行日志闭环修复技术手册

> 版本：Final-1.0  
> 日期：2026-09-14  
> 执行对象：第一次接触 SOP Control 的外部执行模型  
> 目标：一次性关闭当前发布阻断，并补齐“运行过程可见、控制效果可证、日志可学习但不越权”的日志闭环  
> 适用仓库：/Users/xiezhijie/sopcontrol 与 /Users/xiezhijie/ai-job-search  
> 默认动作：允许修改、测试、提交；未经委托者另行明确，不执行 git push

---

## 0. 执行合同

你不是来重新设计 SOP Control，也不是来给 JobsFlow 增加业务规则。你要完成两个相互关联、但边界清晰的工作包：

1. 整理已经统一到 0.4.0 的 SOP Control 与 JobsFlow，使其达到可公开发布的状态；
2. 在 SOP Control 中增加低开销的运行日志与汇报闭环，让用户知道本次到底执行了什么、哪些环节经过控制、哪些只是模型自报、哪些没有被证明，并让结构化运行事实可以在任务边界被吸收为学习观察。

日志不是第二套规则系统。日志不能直接修改规则、不能直接放行动作、不能把模型的自报变成成功证据。权威规则仍在项目控制空间内，规则变更仍必须走现有 sopctl 命令与确认链。

本手册的完成标准不是“新增了一个 log 文件”，而是：

- 发布元数据、投影、vendor 完整性和文档全部一致；
- SOP Control 本体在干净环境中通过测试、门禁和可安装性检查；
- JobsFlow 使用准确 pin 的 vendor 版本，通过关键接入测试，不需要复杂二次改造才能产生控制日志；
- 每个有意义的运行阶段都有可读的结构化事件；
- 事件能用 run_id、operation_id、task_id 和摘要互相连接；
- 人类报告只使用真实事件，不把调用过函数冒充控制生效；
- 日志不泄露 secret、原始 prompt、完整业务材料或不必要的个人数据；
- 日志热路径不调用大模型，不额外制造 capability ticket，不把低风险只读动作变成高摩擦流程；
- 日志可以帮助学习，但学习输入只能进入观察、候选或提案，不能绕过现有确认和编译链；
- 全部验收证据可以由一个从未接触过本项目的模型复现。

---

## 1. 当前基线与已知发布阻断

以下是本手册编写时的基线。执行前必须重新核对，最终报告必须填写实际值。

### 1.1 SOP Control

| 项目 | 基线 |
|---|---|
| 仓库 | /Users/xiezhijie/sopcontrol |
| 分支 | zcode/living-project-batch1 |
| HEAD | 852150f1efc2c8138a2c64706663b9c8a93f7186 |
| 版本 | 0.4.0 |
| 已知本体测试 | 1265 passed, 1 skipped；覆盖率 85.51%（必须重跑） |
| 已知门禁 | 隔离副本中的 sopctl gate 通过 |

### 1.2 JobsFlow

| 项目 | 基线 |
|---|---|
| 仓库 | /Users/xiezhijie/ai-job-search |
| 分支 | codex/sopcontrol-0-3-0-learning |
| HEAD | 99fb4f556274012c5d20b952570756e8aba0af26 |
| vendor 版本 | 0.4.0 |
| tools/sopcontrol_pin.txt | 852150f1efc2c8138a2c64706663b9c8a93f7186 |
| vendor/sopcontrol/PIN.txt | 同上 |
| 已知关键测试 | 106 passed, 10 deselected（必须重跑） |

### 1.3 必须关闭的发布阻断

#### P1：规则投影过期

运行：

~~~bash
cd /Users/xiezhijie/sopcontrol
.venv/bin/sopctl project check .
~~~

如果提示 AGENTS.md 或 CLAUDE.md stale，必须运行：

~~~bash
.venv/bin/sopctl project all .
.venv/bin/sopctl project check .
~~~

只允许替换带标记的投影区，不能手工重写整个文件。投影更新必须提交，因为它是换模型、换会话时恢复控制状态的入口。

#### P1：JobsFlow vendor manifest 过期

必须核对以下四处：

- tools/sopcontrol_pin.txt；
- vendor/sopcontrol/PIN.txt；
- vendor/sopcontrol/sopcontrol/__init__.py；
- vendor/sopcontrol/VENDOR_MANIFEST.json。

当前已知前三处是 0.4.0 / 852150f，但 manifest 仍记录 0.3.1 / 58cfa425。不能只改几个字符串；必须从当前 vendor 树重新计算 digest 和 file count。

如果仓库没有可靠生成器，新增一个确定性的 tools/vendorize_sopcontrol.py 或等价工具，要求：

1. 输入必须是明确的 SOP Control 来源或明确 commit，不能浮动跟随 main/master；
2. 复制范围固定；
3. 排除 .git、缓存、pyc、__pycache__、旧 egg-info 和 manifest 自身；
4. 使用 POSIX 相对路径、固定编码、固定排序计算 tree digest；
5. 写入 PIN 后再计算 manifest；
6. 连续运行两次结果完全一致；
7. 生成 manifest 的版本、commit、pin、source_commit 相互一致；
8. CI 重新计算 digest，不一致就退出非零。

在 JobsFlow CI 和测试中增加断言：

~~~text
tools pin == vendor PIN == manifest.commit == manifest.pin
manifest.version == 实际导入的 sopcontrol.__version__
manifest digest == 当前 vendor 树重新计算的 digest
manifest file count == 当前范围重新计算的数量
~~~

#### P1：公开文档仍停留在 v0.2

至少更新：

- README.md；
- README_ZH-CN.md；
- LIMITATIONS.md；
- PUBLISH.md；
- CHANGELOG.md。

修正版本 badge、状态、限制说明、tag 命令、安装命令和测试数量。可以诚实写 Beta/early public，不得伪称 GA。

英文和中文必须保持以下内容一致：

- 产品定义；
- 0.4.0 版本和 Beta 状态；
- 日志命令与控制效果说明；
- 信任边界和限制；
- 安装和最小示例命令；
- 测试与发布口径。

不修改既有头图。

#### P2：本地虚拟环境元数据残留

曾发现本地 .venv 的 pip show sopcontrol 仍显示 0.3.0，而源码、导入模块和 wheel 是 0.4.0。最终证据必须在全新临时环境中取得：

~~~bash
release_root=$(mktemp -d /tmp/sopcontrol-release.XXXXXX)
python3 -m venv "$release_root/venv"
"$release_root/venv/bin/python" -m pip install -e "/Users/xiezhijie/sopcontrol[dev]"
"$release_root/venv/bin/python" - <<'PY'
import importlib.metadata
import sopcontrol
assert sopcontrol.__version__ == "0.4.0"
assert importlib.metadata.version("sopcontrol") == "0.4.0"
print("version=0.4.0")
PY
~~~

不要为了修这个问题删除项目文件，也不要在没有必要时覆盖用户现有 .venv。

#### P2：diff 格式问题

两个仓库都必须运行：

~~~bash
git diff --check
~~~

修复本次发布范围内的 trailing whitespace、EOF 多余空行和其他格式问题。Markdown 不要用行尾空格实现换行，改用明确结构或 HTML br 标签。

---

## 2. 日志系统的产品目标

SOP Control 没有高可视化后台，因此用户至少需要通过命令和一份短报告知道：

1. 哪个项目、worktree、task、run 在运行；
2. 模型或宿主请求了什么 action/phase；
3. 哪些规则被选择，哪些规则没有选择；
4. gate 的判定是什么，依据是什么；
5. 动作是否真的经过受控入口；
6. 是否签发、兑换 capability ticket，开销是多少；
7. 子进程或适配器是否真的执行；
8. 产物或状态是否真的改变；
9. 验证是否通过、失败、跳过或没有运行；
10. 哪些内容只是模型/产品声明，尚未被证明；
11. 本次过程是否产生了可供学习的观察；
12. 用户下一步应该做什么。

日志不能让系统回答超出证据范围的问题。看到 action_started 不能说动作成功，看到模型说“已完成”不能说文件已经写入，看到 adapter 被加载不能说真实入口一定经过 gate。

### 2.1 三种记录必须分开

#### 运行记录

记录运行时间线，服务于用户查看、排错、跨会话接手和学习观察输入。

#### 控制证据

记录规则是否加载、gate 是否判定、ticket 是否兑换、验证是否通过。继续使用已有 ledger、trace 和 receipt，不由普通日志取代。

#### 业务结果

由宿主产品负责证明，例如 JobsFlow 的岗位是否入表、材料是否生成、外部写入是否成功。SOP Control 只记录宿主提供的结构化回执和安全摘要，不复制业务状态机。

### 2.2 控制效果不能用单一百分比表示

日志报告至少输出：

| 指标 | 定义 |
|---|---|
| eligible_units | 本次应该受控的运行单元；无可靠目录时标记 estimated |
| gated_units | 有真实 runtime gate 决策的运行单元 |
| admitted_units | gate 放行且 admission/ticket 链实际完成的运行单元 |
| blocked_units | 被真实 gate 拦截且没有进入执行的运行单元 |
| executed_units | 下游返回真实执行回执的运行单元 |
| verified_units | 执行结果和需要的验证都有证据的运行单元 |
| unproven_units | 只有声明或观察、没有真实控制证据的运行单元 |
| log_degraded_units | 日志损坏、丢失或无法关联的运行单元 |

可计算：

~~~text
gate_coverage = gated_units / eligible_units
admission_coverage = admitted_units / gated_units
verified_execution_rate = verified_units / admitted_units
evidence_completeness = verified_units / eligible_units
~~~

分母不可靠时不得输出伪造百分比，应输出：

~~~text
eligible_units: unknown
gated_units: 8
verified_units: 6
coverage_status: partial_observation
~~~

JobsFlow 可以用 workflow action/phase 作为运行单元；非 workflow 产品使用真实 adapter、bridge 或 child admission 的 operation 作为运行单元，并注明 estimated 或 observed。

---

## 3. 不可违反的架构原则

### 3.1 日志不是权威规则空间

禁止：

~~~text
读到一条日志 → 自动写成永久规则
~~~

正确链路：

~~~text
运行事件
→ 有界学习窗口
→ 去重/过滤
→ candidate/proposal
→ 用户确认
→ dynamic_sop.confirm
→ compile_rule
→ effective registry
~~~

### 3.2 日志不是放行后门

不能单独信任：

- 模型自报完成；
- adapter 自报通过；
- 手工追加 action_completed；
- 旧日志中出现 verified；
- report 中的汇总文字。

只有真实控制点才能产生高信任事件：

- gate_evaluated：来自真实 gate；
- ticket_redeemed：来自真实 redeem 成功；
- operation_finished：来自真实子进程/适配器回执；
- artifact_committed：真实写入返回成功后；
- validation_finished：验证器实际返回后；
- action_completed：所有必要的真实完成条件满足后。

自报事件可以保留，但必须标记 source=declared、confidence=declared，不能计入 verified 或控制成功率。

### 3.3 热路径零 LLM、零额外 ticket

以下路径不调用大模型：

- 每个日志事件的写入；
- 脱敏；
- 完整性检查；
- timeline 聚合；
- 控制覆盖率计算；
- log list/show/report/health；
- 普通只读状态汇总。

日志不能为了证明自己存在而额外签发 ticket。学习提炼只能在任务/阶段边界，对有限证据包进行，并且只能产出 proposal。

### 3.4 复用现有机制，禁止重复造账本

当前已有：

- sopcontrol/events.py：worktree-local control event；扩展它作为活动日志基础；
- trace.py：harness 真实拦截证据，有 freshness 语义；不要改成普通活动日志；
- ledger.py：正式 evidence/finding 账本；继续作为控制判定依据；
- bridge.py 的 logic receipts：动作、成本和沿袭专用回执；
- learning.py：学习事件、窗口、proposal 和决策链。

新增能力必须使用同一组边界，不能再建互不认识的 run.log、audit.log、activity.jsonl。

### 3.5 日志失败不能伪造成功

普通活动日志是可降级的：写入失败不能使一个本来可执行的只读动作崩溃，但必须在结果和 report 中标记：

~~~text
logging_status: degraded
evidence_completeness: unknown
~~~

gate、ledger、receipt 所需的强控制证据保留现有 fail-closed 语义；不要因新增日志失败而改成假通过。

---

## 4. 工作包 A：发布阻断收口

### A1. 刷新投影

~~~bash
cd /Users/xiezhijie/sopcontrol
.venv/bin/sopctl project all .
.venv/bin/sopctl project check .
~~~

验收：

- project check 退出码为 0；
- AGENTS.md/CLAUDE.md 的非标记内容不被破坏；
- 投影摘要包含当前 0.4.0 的最新规则/日志使用说明；
- 运行后 git diff --check 不失败。

### A2. 统一 vendor 并生成 manifest

先查看 JobsFlow 当前约定：

~~~bash
cd /Users/xiezhijie/ai-job-search
cat tools/sopcontrol_pin.txt
cat vendor/sopcontrol/PIN.txt
cat vendor/sopcontrol/VENDOR_MANIFEST.json
sed -n '1,130p' .github/workflows/ci.yml
~~~

如果没有可靠生成器，实现一个小型、确定性的同步工具。它必须固定复制范围、排除缓存和 manifest 自身、用固定排序计算 digest，并保证连续运行两次完全相同。

不要只修改 manifest 的版本字符串。必须由当前 vendor 树重新计算 file count 和 tree digest，并由测试验证。

### A3. 更新公开文档

更新 README、README_ZH-CN、LIMITATIONS、PUBLISH、CHANGELOG：

- 版本 badge/status 为 0.4.0；
- 状态写 Beta/early public；
- 测试数字与最新实际结果一致，或使用不易过期的 full suite 表述；
- LIMITATIONS 说明平台和沙箱边界；
- PUBLISH 使用 0.4.0 tag 和当前分支；
- CHANGELOG 记录统一版本、运行日志、控制效果报告、学习边界；
- README 增加 log list/show/report/health 用法；
- 英文和中文表达一致；
- 头图不变。

### A4. 更新 CI

增加或确认：

- ruff；
- pytest 和 branch coverage；
- project check；
- sopctl gate；
- clean install/import version check；
- git diff --check；
- wheel build；
- logging schema、脱敏、完整性和 CLI smoke tests；
- JobsFlow vendor pin/manifest consistency test。

CI 不执行需要真实 API key 的 live harness。live 证据和 fixture 回归分开标记，不把 mock 说成 live verified。

---

## 5. 工作包 B：活动日志架构

### B1. 三层存储

| 层 | 位置 | 用途 | 权威性 |
|---|---|---|---|
| Activity log | .sopcontrol-local/worktrees/<worktree_id>/events.jsonl | 时间线、汇报、学习观察 | 非权威 |
| Control evidence | .sopcontrol/evidence/ledger.jsonl、trace、receipt | gate、规则、ticket、验证证明 | 按现有机制 |
| Human report | .sopcontrol-local/reports/run-<run_id>.md/json | 汇总展示和导出 | 非权威 |

活动日志和报告默认在 .sopcontrol-local，不进 Git。不要把业务材料或完整日志提交到仓库。

### B2. 扩展现有 events.py

现有 events.py 已具备 ControlEvent、worktree-local 路径、JSONL、append/load 和 event CLI。将它升级为可报告的活动事件协议，禁止创建第二套互不兼容的日志。

旧 schema 必须可读；新字段有默认值或明确转换；读取旧日志不偷偷重写文件。

### B3. 信任等级

每个事件包含：

~~~text
source: runtime | adapter | cli | declared | system
confidence: verified | observed | declared | unknown
~~~

- runtime + verified：真实 gate、ticket redeem、子进程回执或验证器产生，可计入控制证据；
- adapter + observed：产品适配器观察到调用或回执，可计入 observed；
- cli/declared + declared：用户或模型声明，只作上下文和学习过滤；
- system + unknown：损坏、降级、缺上下文，不能计入成功。

### B4. Event envelope

目标字段如下；如现有字段名不同，保留兼容并保持语义：

~~~json
{
  "schema_version": "2",
  "event_id": "cev-<stable-digest>",
  "record_digest": "sha256:<digest>",
  "project_id": "proj-...",
  "worktree_id": "wt-...",
  "task_id": "TASK-...",
  "run_id": "run-...",
  "operation_id": "op-...",
  "parent_event_id": "cev-...",
  "sequence": 12,
  "event_type": "gate_evaluated",
  "source": "runtime",
  "confidence": "verified",
  "actor": "agent",
  "harness": "opencode",
  "action": "materials.apply",
  "phase": "apply",
  "observed_at": "2026-09-14T12:00:00+08:00",
  "duration_ms": 18,
  "state_before": "prepared",
  "state_after": "admitted",
  "decision": "allow",
  "outcome": "passed",
  "rule_ids": ["JF-MAT-001"],
  "evidence_ids": ["ev-..."],
  "input_fingerprint": "sha256:<digest>",
  "plan_digest": "sha256:<digest>",
  "artifact_digests": ["sha256:<digest>"],
  "side_effect_class": "database",
  "blocker": "",
  "next_action": "execute_child",
  "cost": {
    "llm_calls": 0,
    "challenge_count": 1,
    "admit_count": 1,
    "execute_count": 0,
    "retry_count": 0,
    "repeated_context_count": 0
  },
  "learning": {
    "eligible": false,
    "kind": "",
    "fingerprint": ""
  },
  "detail": {
    "selected_rule_count": 1
  }
}
~~~

字段要求：

- event_id 稳定可去重；
- record_digest 对规范化安全字段计算；
- run_id 是用户可理解的一次运行；
- operation_id 是可计量的一次动作；
- parent_event_id 或 correlation 字段连接时间线；
- detail 只允许白名单；
- 不存 ticket secret、完整命令、完整环境、完整 prompt 或业务正文；
- 时间使用带时区 ISO 8601；
- duration_ms 不得为负；
- cost 缺失时填 0 或 unknown，不猜测。

### B5. 稳定事件类型

| 事件 | 产生位置 | 说明 |
|---|---|---|
| run_started | CLI/adapter 入口 | run 开始 |
| request_received | action plane | 收到待判定动作 |
| surface_discovered | attach/manifest | 发现入口或适配器 |
| rules_selected | selector/effective plan | 本次选择的规则摘要 |
| plan_compiled | profile/logic | plan/profile 冻结 |
| gate_evaluated | 真实 gate | allow/warn/block/not_run/unknown |
| ticket_challenged | bridge/capability | 已签发挑战，不含 secret |
| ticket_redeemed | child admission | 真实兑换成功 |
| operation_started | bridge/adapter | 真实执行开始 |
| operation_finished | bridge/adapter | 子进程/适配器回执 |
| artifact_observed | task/adapter | 产物摘要或 digest 变化 |
| validation_started | validator | 验证开始 |
| validation_finished | validator | pass/fail/not_run/unknown |
| action_blocked | gate/bridge | 被拦截 |
| action_completed | 真实完成点 | 必要真实条件满足后 |
| run_finished | run boundary | 运行结束摘要 |
| learning_observed | learning adapter | 学习观察 |
| proposal_created | learning review | 形成提案 |
| user_confirmation_requested | learning CLI/UI | 等待用户决定 |
| rule_promoted | confirm+compile | 正式进入 effective registry |
| upgrade_started | upgrade | 升级开始 |
| upgrade_finished | upgrade | 切换/回滚结果 |
| log_degraded | logger | 日志自身异常 |

不为每个文件读取、每个候选、每个 token 或每个模型思考步骤写事件。默认一个逻辑运行单元一个生命周期；批处理用 summary event。

---

## 6. 工作包 C：日志实现

### C1. 唯一写入器

建议新增 sopcontrol/activity_log.py；如果已有同等模块则扩展它。职责：

1. 构造安全事件；
2. 注入 project/worktree identity；
3. 生成 event id 和 record digest；
4. 脱敏并校验 allowlist；
5. 原子追加 JSONL；
6. 处理并发写入；
7. 统计坏行、重复、digest mismatch、写入降级；
8. 按 run/task/operation/time 读取；
9. 为 report 和 learning 提供同一读取 API。

业务模块不能各自直接 open/write 日志文件。

### C2. Schema 兼容

- 保留 ControlEvent 已有字段；
- 新字段有默认值；
- 用 schema_version 区分 v1/v2；
- v1 读取时保守补 source/confidence；
- 旧事件没有 event id 时生成只读推导 id，不能提升为 verified；
- 读取旧日志不自动重写；
- 可提供显式 log migrate --dry-run，但不要进入热路径。

### C3. 脱敏

在序列化前脱敏，至少处理：

- ticket secret；
- API key、OAuth token、cookie、Authorization；
- --secret、--token、--password、--api-key 参数值；
- SOPCTL_TICKET_FILE 指向的内容；
- 完整环境变量值；
- 完整 prompt、JD、候选人材料和文档正文；
- 用户目录绝对路径；
- 不必要的 email、电话和个人信息。

允许保留：

- 相对路径；
- 长度、数量、状态码、退出码；
- digest；
- action、phase、rule id；
- ticket id，不含 secret；
- 脱敏错误分类；
- 极短且再次脱敏的 stdout/stderr 尾部。

负向测试必须把 fake secret 放入 argv、env、stdout、stderr 和 detail，断言日志及 report 都没有原值。

### C4. 完整性、并发与轮转

至少实现：

- 每行 record_digest；
- event id 去重；
- JSON schema 校验；
- 无效行计数；
- digest mismatch 计数；
- 读取上限；
- 超限轮转/裁剪；
- log health 返回 healthy/degraded/unknown。

并发写入必须保证每行完整，不要每次追加都读取全文件、整体覆写。轮转不得影响 rule/evidence/receipt；旧日志被裁剪时要记录数量，不能静默造成“看起来没有发生过”。

### C5. 成本和降级

目标：

- 不调用 LLM；
- 不新增 ticket；
- 不重复读取大文件；
- 不保存完整 stdout/stderr；
- 普通 operation 事件数量有限；
- report 只读取指定 run 或最近窗口；
- 读失败时明确 degraded，不无限重试。

建议预算：

- 单事件 append p95 ≤ 5ms；
- 普通 action 额外墙钟开销 ≤ 2%；
- 只读动作 LLM calls = 0；
- 只读动作 ticket 数保持原有 0；
- 一次 operation 默认 ≤ 32 个事件；
- report 无副作用。

必须实测，不能把“应该很快”写成通过。

---

## 7. 工作包 D：真实控制点接线

### D1. Attach 和自动发现

在真实 attach/manifest/doctor 路径产生：

~~~text
run_started
surface_discovered（可聚合）
attach/verify outcome
gap 或 blocked
run_finished
~~~

报告发现了多少入口、哪些是静态发现、哪些经过真实 probe、哪些因 harness 缺失没有接通。静态发现不能写成 runtime verified。

### D2. Action plane 和 gate

在 action_plane.py 或实际等价调用层接线：

1. 收到请求写 request_received；
2. profile/plan 冻结写 plan_compiled；
3. selector 返回写 rules_selected；
4. 真实 gate 返回写 gate_evaluated；
5. block 写 action_blocked，不写 completed；
6. 真实完成后写 operation_finished/action_completed；
7. 写入 verdict、rule ids、evidence ids、next action 和 cost。

gate 纯函数保持纯函数，事件 I/O 放在调用层。

### D3. Bridge、ticket、子进程

同一 operation_id 下形成：

~~~text
request_received
→ gate_evaluated
→ ticket_challenged（需要时）
→ ticket_redeemed（真实兑换后）
→ operation_started
→ operation_finished
→ validation_finished（若有）
→ action_completed / action_blocked
~~~

要求：

- challenge/redeem 共享正确 run/operation；
- 只记录 ticket id；
- 子进程没有兑换不能写 verified completed；
- 超时、启动失败、非零退出写失败；
- handoff 清理不影响 receipt 关联；
- bridge receipt 和活动日志通过 run_id、operation_id、attempt_id 连接；
- retry 使用新的 attempt，不覆盖旧事件。

### D4. Task 生命周期

在 task open、submit、verify、deliver 的真实边界记录：

- task contract/required rules 摘要；
- 状态转换前后；
- 完成门判定；
- fail、gap、unknown 原因；
- deliver 是否真实完成。

日志不能直接改任务 YAML 状态。

### D5. Logic/MSE

记录一次计划级摘要：

- goal digest；
- plan/strategy digest；
- 操作数量；
- 支配浪费步骤数量；
- 反逻辑例外；
- 判定结果；
- 成本估计。

不为每个业务候选写完整事件，不保存业务正文。逻辑正确性仍由 MSE 测试和产品结果证明。

### D6. Learning 和动态 SOP

事件链：

~~~text
learning_observed
→ review window
→ proposal_created
→ user_confirmation_requested
→ rule_promoted（仅确认后）
~~~

要求：

- 用户纠正、明确偏好、重复受控边界可以成为观察；
- traceback、依赖缺失、网络抖动、一次失败默认不是规则；
- once_only 只产生会话 evidence，不进永久 registry；
- 模型 summary 只是 proposal；
- learn decide control/both 继续要求用户确认凭据并走 confirm+compile；
- 记录 proposal/rule id 和 digest，不记录私密上下文；
- 同 fingerprint 在同窗口不重复弹窗；
- review 在任务/阶段边界执行；
- 无 LLM 时仍能报告观察计数和待复核入口，不伪造语义提炼成功。

### D7. Upgrade 和 rollback

记录：

- old/new runtime version 和 digest；
- rule registry digest；
- event schema version；
- shadow validation；
- atomic switch；
- rollback；
- 是否丢失动态 SOP 或放宽约束。

旧事件必须可读；日志 schema 变化不能导致永久规则丢失。

---

## 8. 工作包 E：用户 CLI 与报告

### E1. log 命令族

至少提供：

~~~bash
sopctl log list [path] [--run-id RUN] [--task-id TASK] [--operation-id OP] [--limit N]
sopctl log show [path] --run-id RUN
sopctl log report [path] --run-id RUN [--format text|json|markdown]
sopctl log health [path]
sopctl log benchmark [path]
~~~

如果已有 event list/receipt 等同等命令，复用它们并补齐，不要建两个平行入口。

### E2. list

默认只输出短表：

~~~text
时间                run       operation  event               confidence  outcome
2026-09-14 12:00    run-123   op-001     gate_evaluated      verified    allow
2026-09-14 12:00    run-123   op-001     ticket_redeemed     verified    passed
2026-09-14 12:01    run-123   op-001     operation_finished  observed    passed
~~~

默认不输出 detail、原始命令、prompt 或业务材料。json 输出仍然脱敏。

### E3. show

按 run_id 输出时间线，包含：

- run/task/project/worktree；
- 起止时间和耗时；
- action/phase；
- selected rules；
- gate verdict；
- ticket challenge/redeem；
- operation/validation outcome；
- artifact digest 数；
- cost；
- learning links；
- blockers/next action；
- logging health。

### E4. report

Markdown 报告至少包含：

~~~text
SOP Control Run Report

Run:
Action:
Status: completed / blocked / failed / unknown

控制覆盖
- eligible:
- gated:
- admitted:
- blocked:
- executed:
- verified:
- unproven:

实际发生
1. ...

没有被证明
- ...

成本
- LLM calls:
- ticket challenge/admit:
- retries:
- log status:

学习入口
- observations:
- proposals:
- permanent rule changes:

下一步
- ...
~~~

报告必须把“没有发生”“发生但失败”“发生但没有被证明”分开，unknown 不能变成 pass。

### E5. 低打扰自动提示

动作结束时只增加一行：

~~~text
run=run-... status=blocked gated=3/4 verified=2 report=.sopcontrol-local/reports/run-....md
~~~

不要每个事件弹框，不要把日志系统变成常驻聊天机器人。学习候选按现有窗口机制一次提示。

---

## 9. 工作包 F：日志驱动的学习和自我进化

### F1. 可以无感积累

- event type、action、phase、rule id、状态转换；
- 稳定 blocker code；
- 重复 operation 顺序；
- 用户明确纠正的事件引用；
- rule 被选择/未选择的上下文 fingerprint；
- retry、重复验证、旁路、未接通入口计数；
- coverage 变化；
- log degraded/evidence missing 事实。

### F2. 不允许自动晋升

不能因为日志重复就自动：

- 修改 constitution；
- 放宽 gate；
- 增大 tolerance；
- 改写用户基线；
- 把 once_only 变永久 dynamic SOP；
- 修改 JobsFlow 业务语义；
- 把自然逻辑例外变普遍规则。

这些只能成为 candidate/proposal，仍需用户确认。

### F3. 确定性前置过滤

在可选 LLM distiller 前：

1. 丢弃空文本、traceback、依赖安装噪声和重复低价值事件；
2. 按 task/session/phase/action 分组；
3. 用 fingerprint 去重；
4. 识别明确 correction/decision，不从任意日志猜意图；
5. 标记冲突；
6. 限制 evidence refs 和安全摘要；
7. 到任务/阶段边界再生成 proposal。

LLM 只能对有界事件包提炼候选规则、触发条件、例外和非目标；不能写 registry、伪造 user confirmed、伪造 verified 或放行当前 action。

---

## 10. JobsFlow 最小接入和验收

### 10.1 适配边界

JobsFlow 正式 workflow 入口只提供薄上下文：

- action；
- phase；
- task/run/operation id；
- input/plan digest；
- side-effect class；
- 业务结果安全摘要；
- 必要时调用标准事件 helper 或 CLI。

JobsFlow 不复制 registry、gate、ticket、动态 SOP 生命周期、日志脱敏或 report 聚合。

### 10.2 必测路径

1. 只读 scan/preview：有 run summary、gate 事件、零 LLM、零 ticket；
2. 缺前置条件：blocked、零副作用、零空 ticket；
3. 受控 push/apply：challenge → redeem → operation → receipt 完整关联；
4. 错 secret、旧 ticket、跨 task ticket：真实拒绝且无 secret；
5. learning event → review → proposal：未确认时 registry 不增长；
6. 用户确认后 proposal → confirmation → compile → effective rule；
7. once_only 有会话记录但不进永久规则；
8. log degraded 显示 unknown/degraded；
9. vendor 更新后 import、PIN、manifest、event schema 一致；
10. 旧 event schema 可读且安全降级。

### 10.3 测试环境

~~~bash
jobsflow_release_root=$(mktemp -d /tmp/jobsflow-release.XXXXXX)
python3 -m venv "$jobsflow_release_root/venv"
"$jobsflow_release_root/venv/bin/python" -m pip install -r requirements-dev.txt
"$jobsflow_release_root/venv/bin/python" -m pip install -e vendor/sopcontrol
~~~

如果缺少 python-docx、pydantic 等依赖，先报告 collection/environment failure，不能把 import unavailable 当成产品失败，也不能降低依赖版本掩盖问题。

---

## 11. 测试清单

### 11.1 日志 schema 和存储

- v1/v2 event 都能读取；
- 未知危险字段被拒或丢弃；
- event id/digest 稳定；
- 无效行被计数；
- duplicate 不重复计数；
- 追加原子；
- 并发写入不出现半行；
- worktree 分隔正确；
- 轮转有界且可解释；
- 不直接写 .sopcontrol 权威目录。

### 11.2 脱敏和信任

- argv/env/stdout/stderr/detail 中的 secret 不出现在日志；
- prompt/JD/material 正文不出现在日志；
- declared completed 不计入 verified；
- runtime gate block 产生 verified block；
- child admission 后才产生 verified redeemed；
- 进程失败不能产生 verified completed；
- degraded 不显示完整证据。

### 11.3 真实运行链

- action plane；
- bridge/ticket；
- task lifecycle；
- attach/coverage；
- logic/MSE；
- learning；
- upgrade/rollback。

### 11.4 CLI/report

- log list；
- log show；
- log report；
- log health；
- log benchmark；
- run/task/operation/time 过滤；
- 空日志；
- 损坏日志；
- report 无 secret；
- report 无副作用；
- 报告数字和原始事件抽样一致。

### 11.5 SOP Control 全量

在干净环境中：

~~~bash
export COVERAGE_FILE=/tmp/sopcontrol-0.4.0-release.coverage
/path/to/clean-venv/bin/ruff check sopcontrol plugins tests
/path/to/clean-venv/bin/python -m pytest -q -p no:cacheprovider \
  --cov --cov-branch --cov-report=term-missing
/path/to/clean-venv/bin/python -m pip wheel . --no-deps \
  --wheel-dir /tmp/sopcontrol-wheels
~~~

要求：无 collection error；全部测试通过，允许明确标注的 skip；branch coverage 达到当前 85% 门槛；wheel 可构建；clean install 后版本为 0.4.0；ruff、git diff --check 通过。

### 11.6 门禁

在临时 worktree 中执行：

~~~bash
sopctl project check .
sopctl gate .
sopctl log health .
sopctl log report . --run-id <actual-run-id> --format markdown
~~~

要求：

- project check 退出 0；
- gate 退出 0；
- ledger integrity OK；
- log health 为 healthy，或清楚说明 degraded；
- report 数字与事件一致。

### 11.7 JobsFlow

~~~bash
cd /Users/xiezhijie/ai-job-search
python -m pytest -q
~~~

再定向运行：

~~~bash
python -m pytest -q \
  tests/test_beta_acceptance_paths.py \
  tests/test_sopcontrol_final_integration.py \
  tests/test_sopcontrol_adapter.py \
  tests/test_workflow_cli_capability_ticket.py \
  tests/test_learning_adapter.py \
  tests/test_manual_intake.py \
  tests/test_materials_compiled_sop.py \
  tests/test_materials_workflow_contract.py \
  tests/quality_control/test_integration.py \
  tests/quality_control/test_security_boundary.py \
  tests/test_workflow_orchestrator.py \
  tests/test_workflow_phase2.py \
  tests/test_workflow_portal_policy.py \
  tests/test_workflow_workspace_boundary.py
~~~

要求：

- 无 collection error；
- vendor import 是 0.4.0；
- pin/PIN/manifest/import 一致；
- scan、push/apply、ticket、learning、log 关键用例通过；
- deselected 不计入 passed；
- 没有运行的真实网络/真实 LLM 只写 UNPROVEN。

### 11.8 性能

测量：

- 单事件 append p50/p95；
- 100/1000/10000 事件 report p50/p95；
- 并发追加完整性；
- 普通只读 action 总耗时对照；
- LLM 调用数；
- ticket 数；
- report 是否有副作用。

写明机器、Python、事件数量、文件大小和结果。没有数据就写 UNPROVEN。

---

## 12. 最终执行顺序

### 第 1 步：SOP Control 收口

~~~bash
cd /Users/xiezhijie/sopcontrol
.venv/bin/sopctl project all .
.venv/bin/sopctl project check .
~~~

### 第 2 步：JobsFlow vendor 收口

同步准确的 0.4.0 vendor，重新生成 manifest，添加一致性测试和 CI 检查。

### 第 3 步：日志实现和接线

优先扩展 events.py 或现有等价模块，然后接入 action plane、bridge、task、attach、learning、upgrade。不要让测试 helper 伪造生产事件。

### 第 4 步：日志实测

执行一个只读 fixture 和一个受控写入 fixture，验证：

- timeline；
- report；
- coverage 数字；
- ticket/receipt 关联；
- secret 脱敏；
- learning observation；
- log health；
- 成本和延迟。

### 第 5 步：全量测试和质量

~~~bash
ruff check ...
pytest ...
git diff --check
pip check
wheel build
~~~

两个仓库都要跑，不能只测 SOP Control。

### 第 6 步：公开内容审阅

确认：

- README 中英文平行；
- 版本均为 0.4.0；
- 限制边界诚实；
- 没有本地绝对路径泄露；
- 没有 secret；
- 没有业务数据、运行日志或用户材料；
- 头图未改；
- .sopcontrol-local 未被错误提交；
- 公开的 task/evidence 历史是有意的。

### 第 7 步：提交

建议分成可审阅 commits：

1. fix: refresh projections and release metadata
2. fix: align JobsFlow vendor manifest with sopcontrol 0.4.0
3. feat: add bounded runtime activity log and reports
4. test: verify logging, redaction, coverage and learning links
5. docs: document 0.4.0 release and activity log

如果项目任务机制要求每批绑定 task，使用 sopctl task，不直接修改受保护状态文件。

### 第 8 步：tag/push

未经明确授权不要 push。若已获得发布授权，两个仓库都 clean 后，再创建 v0.4.0 并按当前 PUBLISH.md 推送。最终报告必须说明 tag 是否已推送，不能把本地 tag 说成 GitHub 已发布。

---

## 13. 最终报告模板

外部执行模型必须交付实际证据，不能只说“已完成”：

~~~text
# SOP Control 0.4.0 最终发布与日志闭环报告

## A. 版本
- SOP Control branch / HEAD:
- SOP Control version:
- JobsFlow branch / HEAD:
- JobsFlow vendor version:
- vendor PIN:
- vendor manifest commit/version/digest:
- tag:
- pushed: yes/no

## B. 发布阻断
- project check:
- gate:
- README EN/ZH consistency:
- PUBLISH/LIMITATIONS/CHANGELOG:
- git diff --check:
- clean install:
- wheel build:

## C. 测试
- SOP Control full:
- SOP Control coverage:
- JobsFlow full:
- JobsFlow key integration:
- logging tests:
- redaction tests:
- learning-link tests:
- performance p50/p95:

## D. 日志实测
- sample run_id:
- event count:
- operation count:
- eligible/gated/admitted/executed/verified/blocked/unproven:
- LLM calls:
- ticket challenge/admit:
- report path:
- log health:

## E. 学习边界
- observations:
- proposals:
- rules promoted:
- once_only behavior:
- user confirmation required: yes/no

## F. 未证明事项
- real LLM:
- L3 live network:
- non-macOS:
- external business semantic correctness:

## G. 变更文件与 commits
- ...
~~~

所有 UNPROVEN 必须写原因和下一步。不能用“理论上支持”替代证据。

---

## 14. 完成与停止判定

### 14.1 可以判定完成

同时满足：

- SOP Control 和 JobsFlow version、pin、manifest 一致；
- project check、gate、ruff、diff check、clean install、wheel build 通过；
- 两边测试无 collection error；
- JobsFlow 正式入口在只读和至少一个受控写入路径产生真实关联日志；
- report 区分 verified、observed、declared、unknown；
- 日志无 secret、无完整业务正文；
- 热路径零 LLM、无额外只读 ticket；
- dynamic learning 仍经过 proposal/confirmation/compile；
- once_only 不进入永久 registry；
- 损坏、降级和缺证据显示 unknown/degraded；
- 所有发布文档和版本号一致；
- 最终报告按第 13 节交付。

### 14.2 必须停止并报告

以下情况不能自行绕过：

- 无法确定 vendor 来源或 manifest digest；
- 活动日志能够伪造 verified/control success；
- secret/API key/业务正文进入日志；
- project check、gate 或 ledger integrity 失败；
- 受保护 .sopcontrol 被直接编辑；
- JobsFlow 只能靠复杂手工改造才能接入；
- 测试依赖缺失导致无法判断代码结果；
- 旧事件无法安全读取；
- 需要关闭 enforce、降低门槛或跳过失败测试。

### 14.3 当前目标不要求的事情

不要把以下事项擅自扩大成发布阻断：

- 真实 L3 网络证明；
- 所有平台的 live harness 证明；
- 真实大模型语义质量证明；
- 把 JobsFlow 业务语义判断搬进 SOP Control；
- 企业级后台或云端日志平台；
- 为每个低价值函数添加日志；
- 用多重 agent 审计替代确定性事件和 gate。

最终产品应保持小而精：本地、低开销、模型中立、可解释的控制平面。它让用户看见控制事实，让模型换会话/换版本后仍能恢复，让动态规则拥有安全学习入口，同时不把日志系统变成新的高耗时工作流。

