# SOP Control 全域无阻塞接入实施手册

> 日期：2026-09-08  
> 性质：面向后续实现者的目标架构与分阶段实施规范，不是当前版本功能说明  
> 当前基线：`zcode/living-project-batch1`，整理后 HEAD `49408f03a703e13875b1815408007a0192748267`（差距审计起点为 `cdbb14c`）  
> 目标：用户安装 SOP Control 后，无需长期改造控制器或业务产品，即可让任意阶段的项目先完整连通，再持续获得全域可见性和逐步增强的强制控制

---

## 1. 先给结论：当前距离目标还有多远

当前 SOP Control 已经拥有较完整的规则治理上层，但还没有形成覆盖整个项目执行面的通用接入底座。

本手册中的百分比是基于源码、CLI、测试和真实 JobsFlow 接入记录作出的工程成熟度估计，**不是 pytest 覆盖率，也不是营销指标**。

| 能力维度 | 当前成熟度 | 主要依据 | 主要缺口 |
|---|---:|---|---|
| 规则、证据、判定与生命周期 | 85% | registry、audit、verdict、attest、gate | 不是本轮主缺口 |
| 项目身份、任务连续性、Worktree 隔离 | 75% | identity、task、ticket、event、ProjectScope | 身份仍以本地 Git common-dir 为主；缺全局接入登记 |
| 静态项目发现 | 55% | bootstrap、ProjectScope、side-effect 关键字扫描 | 入口和副作用发现仍偏启发式；不能证明运行时全域覆盖 |
| 无破坏、一次式项目接入 | 30% | init、project、hook、doctor 可分别工作 | 没有统一 attach；已有 Hook/配置冲突时常需人工整合 |
| Harness 运行时接入 | 40% | OpenCode live；Claude 协议；Codex wrap | 工具归一目前主要是 Bash/Write/Edit；Codex 是事后门 |
| 全执行面可见性 | 20% | harness trace、ControlEvent 基础结构 | 文件读取、网络、浏览器、凭证、数据库、后台进程没有统一捕获 |
| 控制覆盖率证明 | 15% | ScanCoverage、growth ambiguity 指标 | 现有 coverage 是源码扫描覆盖，不是执行面控制覆盖 |
| 外部副作用通用控制 | 5% | capability ticket 原语 | 尚无网络、浏览器、凭证或数据库通用 Adapter |

综合判断：**距离目标完成约还有 55%–60% 的关键工程量**。现有成果不是要推倒重来；规则治理、任务契约、证据和判定层可以直接复用。真正缺的是位于这些能力之下的：

1. 统一接入编排；
2. 通用动作模型；
3. 全执行面事件摄取；
4. 覆盖地图与可证伪探针；
5. 对无原生 Hook 平台的受控运行环境。

达到“安装后能顺畅接入、当天开始发挥作用”的 MVP，预计需要 **2–4 个工程周**。达到网络、浏览器、凭证、后台进程均可提供强覆盖的跨平台版本，预计还需 **8–16 个工程周**。具体时间取决于支持的平台数量和是否引入容器或系统级执行提供者。

---

## 2. 产品目标必须这样定义

### 2.1 核心承诺

> 一次安装、一次轻量接入，不要求用户先重构业务产品；SOP Control 当天建立端到端控制通路，未理解的部分作为明确 gap 持续发现，不得让局部不兼容拖垮整个接入。

### 2.2 “连接、覆盖、理解、强制”是四件不同的事

| 层级 | 含义 | 首次接入要求 |
|---|---|---|
| Connected | 项目身份、Harness、控制器、事件与状态通路可用 | 必须完成 |
| Observable | 动作能够被看见、归属和记录 | 对当前 Harness 的所有工具通道尽可能完成 |
| Recognized | 系统理解动作的业务含义，如 scan、push、apply | 允许逐步增长 |
| Enforced | 规则能在副作用前确定性阻断或要求确认 | 只对已确认规则启用 |

一个项目可以处于：

```text
连接完整度       100%
执行面可见覆盖    85%
业务识别覆盖      30%
规则强制覆盖      10%
```

这仍然是成功接入。禁止因为业务识别或强制覆盖尚未完成，就把整个项目判定为“不可使用”。

### 2.3 “覆盖每个角落”的准确含义

SOP Control 不需要理解每一行业务代码，但必须枚举并持续追踪所有能够产生项目影响的执行面：

- 文件读取、写入、重命名和删除；
- Shell 命令和子进程；
- Git、测试、构建、发布与 CI；
- 网络请求与外部 API；
- 浏览器、profile、CDP 和页面动作；
- 数据库、缓存和业务状态文件；
- 凭证、Cookie、Token 和环境变量；
- 后台任务、定时器和队列消费者；
- 外部消息、表格、申请、部署等高影响副作用。

“尚未识别”可以存在，“悄悄看不见”不可以存在。无法覆盖的执行面必须出现在 Coverage Report 中。

---

## 3. 当前版本真实具备什么

实施者不得重做以下已有能力。

### 3.1 可直接复用的模块

| 现有模块 | 真实能力 |
|---|---|
| `sopcontrol/identity.py` | 项目身份；Git worktree 通过 common-dir 共享身份；支持 lock/export/import |
| `sopcontrol/context.py` | `ProjectScope`、Git-aware 文件枚举、Worktree/HEAD/branch、静态 `ScanCoverage` |
| `sopcontrol/task.py` | 任务契约、写入范围、MUST 字段、状态迁移、修复预算、rebind |
| `sopcontrol/registry.py` | 权威规则、生命周期和并发控制 |
| `sopcontrol/audit.py` | discovery 与 enforcement 分离；大仓 discovery 可 defer |
| `sopcontrol/verdict.py` | Evidence → Finding → Verdict；克制颁发 enforced |
| `sopcontrol/harness.py` | 纯函数工具调用判定；保护控制面、禁止 no-verify、push gate、执行者身份 |
| `sopcontrol/cli_harness.py` | Claude/OpenCode Adapter 安装；Codex wrap；harness-check |
| `sopcontrol/project.py` | AGENTS/CLAUDE 托管小节投影；幂等且不覆盖其他正文 |
| `sopcontrol/tickets.py` | 项目/Worktree/动作/输入/副作用绑定的一次性 capability ticket |
| `sopcontrol/events.py` | Worktree-local、版本化 `ControlEvent` 和回执基础结构 |
| `sopcontrol/bootstrap.py` | 绿地/半成品项目的目的、命令、敏感路径、副作用候选扫描 |
| `sopcontrol/inventory.py` | 已登记规则相关的受控入口、旧入口和平行状态清单 |
| `sopcontrol/ledger.py`、`chronicle.py` | 证据与治理事件的持久化、完整性和重建 |

当前测试基线：**663 项测试可收集**；`pyproject.toml` 要求语句与分支综合覆盖率至少 85%。

### 3.2 当前不能声称的能力

1. `sopctl init` 只初始化控制目录，不是一键完整接入。
2. 当前不存在 `sopctl attach`、`sopctl enter` 或通用 `sopctl run --action`；本手册中的这些名称均为待实现接口。
3. `check_tool_call` 主要理解 Bash、Write、Edit、MultiEdit；普通命令默认观察放行，Read 和其他工具没有通用策略。
4. OpenCode 有 live 运行时证据；Claude 为协议适配；Codex 当前没有调用前 Hook，只能投影加事后 gate。
5. `ControlEvent` 依赖调用方主动上报，尚不能证明所有动作都会经过它。
6. `ScanCoverage` 证明扫描了多少合资格源码，不证明文件、网络、浏览器等运行时通道已被控制。
7. Bootstrap 的副作用扫描是关键字代理，不是完整调用图或运行时事实。
8. Git Hook 遇到已有非 SOP Control Hook 时会拒绝覆盖并要求人工整合；这不符合无阻塞接入目标。
9. 尚无网络代理、浏览器 Adapter、凭证 broker、数据库 Adapter、后台进程捕获或系统级运行时。
10. 当前没有统一、可计算的 Control Coverage Ledger。

---

## 4. 目标架构：上层不重做，向下补齐覆盖底座

```text
Codex / Claude / OpenCode / Cursor / CLI / CI
                       │
                       ▼
              Attachment Module
        识别、计划、合并、安装、探针、回滚
                       │
                       ▼
                 Action Plane
       标准动作信封 → 规则判定 → 决策与回执
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   Harness Adapter  Runtime Adapter  Effect Adapter
   工具调用归一     进程/文件/网络   浏览器/凭证/DB
          └────────────┼────────────┘
                       ▼
                  原有业务产品
                       │
                       ▼
                Coverage Ledger
       已发现 / 可观察 / 可强制 / 已实测 / gap
                       │
                       ▼
        现有 Rule / Evidence / Verdict / Task
```

### 4.1 不可违反的所有权规则

| 事实 | 唯一所有者 |
|---|---|
| 业务对象和业务状态 | 业务产品 |
| 业务动作如何执行 | 业务产品 |
| 项目规则和授权 | SOP Control |
| 当前任务与允许范围 | SOP Control |
| 控制事件与完成证据 | SOP Control |
| 业务状态到通用动作的映射 | Adapter |

SOP Control 不复制业务数据库，不另建一套业务状态机。它只读取业务事实摘要并判断“该动作现在是否允许”。

---

## 5. 要新增的四个深模块

这里使用“深模块”原则：调用者学习很小的 Interface，复杂的发现、兼容、合并、回滚和证据逻辑都留在 Implementation 内。不要让每个 Harness 或业务项目分别实现一遍接入流程。

### 5.1 Attachment Module

建议文件：

```text
sopcontrol/attachment.py
sopcontrol/attachment_model.py
sopcontrol/cli_attach.py
```

外部 Interface 只保留四个动作：

```python
plan = plan_attachment(root, requested_mode="auto")
report = apply_attachment(plan)
status = attachment_status(root)
preview = plan_detachment(root)
```

Interface 必须隐藏：Git/worktree 识别、Harness 检测、Hook 合并、投影、配置迁移、原子写入、回滚和探针执行。

建议 CLI：

```bash
sopctl attach .                 # plan + 安全项自动应用 + 报告 gap
sopctl attach . --plan          # 纯只读预览
sopctl attach . --mode observe  # 只观察，不新建强制规则
sopctl attach-status .
sopctl detach . --plan          # 只预览；真正解除需人工确认
```

注意：命令尚不存在。实现前不要写入 README 的现有功能区。

### 5.2 Action Plane

建议文件：

```text
sopcontrol/action_model.py
sopcontrol/action_plane.py
sopcontrol/action_classifier.py
```

外部 Interface：

```python
decision = evaluate_action(root, envelope)
receipt = commit_action_result(root, result)
```

现有 `harness.check_tool_call` 应成为兼容 Wrapper，内部转调 `evaluate_action`；不得同时保留两套独立判定逻辑。

最低动作信封：

```yaml
schema_version: "1"
action_id: act-...
project_id: proj-...
worktree_id: wt-...
task_id: TASK-...
run_id: run-...
actor:
  harness: codex
  model: model-id-or-unknown
surface: filesystem_write
operation: write
target: src/example.py
raw_event_digest: sha256:...
input_fingerprint: ...
state_digest: ...
expected_revision: ...
requested_side_effects: [write_project_file]
capability_ticket_id: ...
idempotency_key: ...
observed_at: ...
```

动作信封由 Adapter 生成、控制器补全和验证；不得信任模型自行漏报副作用后的信封。

决策固定为：

```text
allow | deny | ask | observe
```

结果状态与控制决策分离：

```text
success | partial_success | waiting_user |
recoverable_failure | fatal_failure
```

### 5.3 Coverage Module

建议文件：

```text
sopcontrol/coverage.py
sopcontrol/coverage_model.py
sopcontrol/coverage_probe.py
```

外部 Interface：

```python
record_surface_event(root, event)
report = control_coverage(root)
probe = verify_surface(root, surface)
```

每个执行面记录以下状态之一：

```text
undiscovered   尚未发现，不能进入分母冒充完整
detected       已发现入口或资源
observable     真实动作能留下事件
enforceable    可以在副作用前作出决策
verified       通过无害穿透探针证明 Adapter 真在调用链上
gap            已知存在但当前不可观察或不可强制
unsupported    当前平台明确不支持
```

必须把当前静态 `ScanCoverage` 保留为 `scan_coverage`，新增指标叫 `control_coverage`，禁止二者混用。

### 5.4 Adapter Module

建议目录：

```text
sopcontrol/adapters/
  harness/
    claude.py
    opencode.py
    codex.py
  runtime/
    cooperative.py
    supervised.py
  effects/
    filesystem.py
    process.py
    git.py
    network.py
    browser.py
    credential.py
```

Adapter 只负责协议翻译，不持有规则权威。只有在至少存在生产 Adapter 和测试 Adapter，或两个真实平台实现时才建立新 seam；不要为一个实现制造空接口。

---

## 6. `sopctl attach` 的无阻塞算法

### 6.1 阶段一：只读发现

首次运行不得立即修改业务代码。需要识别：

- Git 根、common-dir、Worktree 和项目身份；
- 语言、包管理器、测试与构建命令；
- AGENTS/CLAUDE/Cursor 等 Harness 配置；
- 已有 Git Hook 和 CI；
- 入口、后台任务、浏览器、数据库和网络信号；
- 已有 `.sopcontrol/` 的 schema 与状态；
- 冲突、无权限目录、损坏配置和不支持通道。

发现必须有预算。超预算时返回 `connected_with_gaps`，不得因为大型 Markdown 或数据目录让整体接入失败。

### 6.2 阶段二：生成 Attachment Plan

计划至少包含：

```yaml
project:
  root: ...
  project_id: ...
  lifecycle: greenfield | existing | mature
detected_harnesses: [...]
safe_changes: [...]
conflicts: [...]
deferred_surfaces: [...]
required_human_choices: [...]
rollback_plan: [...]
estimated_control_coverage: ...
```

### 6.3 阶段三：原子、安全、可组合应用

应用策略按以下优先级处理：

1. **merge**：只更新 SOP Control 托管小节；
2. **chain**：串联已有 Hook，不覆盖；
3. **isolate**：用独立文件或目录安装 Adapter；
4. **defer**：局部无法安全合并时记 gap；
5. **abort**：只有项目根不可用、控制状态无法建立或计划自身损坏才整体失败。

现有行为需要改进：

- Git Hook 不应因为已有 Hook 就要求长期人工整合；应生成 chain runner，并保存原 Hook 摘要与顺序。
- Worktree 中 `.git` 可能是文件；Hook 路径必须通过 `git rev-parse --git-path hooks/<name>` 解析，不能只使用 `root/.git/hooks`。
- Claude 配置损坏时，只将 Claude Adapter 标为 gap，其他接入继续完成。
- OpenCode 的目标插件文件被占用时，使用唯一命名的 SOP Control 插件并检查平台加载规则，不覆盖他人插件。
- 非 Git 项目仍应完成身份、事件和 Harness 接入；只把 Git/CI 标为 unavailable。

### 6.4 阶段四：端到端握手

安装文件存在不等于接入成功。必须运行无害探针：

1. Harness 发出一个不会产生业务副作用的测试动作；
2. Adapter 生成标准 Action Envelope；
3. Action Plane 返回 `observe` 或 `allow`；
4. 事件进入当前项目和 Worktree；
5. Coverage Ledger 将对应通道标为 `verified`；
6. 业务源码和原有配置语义保持不变。

### 6.5 阶段五：产生 Attachment Report

示例：

```text
连接状态：connected_with_gaps

✓ 项目身份
✓ 当前 Worktree
✓ 规则与任务投影
✓ OpenCode 工具调用
✓ Git pre-push chain
△ Codex：投影与事后门可用，缺调用前拦截
△ 浏览器：已发现 CDP 使用，尚无 Adapter
✗ 外部 scheduler：不在当前执行环境

业务源码改动：0
模型调用：0
可回滚安装项：6
下一步：补浏览器 Adapter；不影响当前项目继续工作
```

---

## 7. 新项目与中途项目必须共用同一条接入主链

### 7.1 新项目

新项目的区别只是发现结果更少，不应维护另一套接入实现。

```text
attach
→ 建立身份和事件空间
→ 安装 Harness Adapter
→ 默认 observe
→ 后续运行自然积累入口和副作用
→ 用户确认后逐步 enforce
```

不得要求新项目先设计完整状态机、目录和 SOP。

### 7.2 中途项目

```text
attach
→ 读取现有入口和状态，不迁移业务数据
→ 合并现有 Hook/CI/Harness 配置
→ 全部通道先进入 observe
→ 已知冲突局部 defer
→ 项目立即可继续工作
→ 运行事件逐步补全识别和规则
```

不得把“旧入口尚未关闭”解释为“接入失败”。旧入口应成为 Coverage Gap 和治理候选；只有它违反已经生效的硬规则时才阻断对应动作。

---

## 8. 分阶段实施计划

外部模型必须按顺序推进。每一阶段独立提交、独立测试；不得一次性重写 CLI、Harness 和控制状态。

### Phase A：统一无阻塞接入 MVP

目标：一条命令完成已有能力编排，接入不再依赖用户理解多个子命令。

实施：

1. 新增 Attachment Plan/Report 数据模型；
2. 新增 `attach --plan` 纯只读模式；
3. 编排现有 init、identity、project、hook/profile、doctor；
4. 支持 greenfield、existing、non-git；
5. 写本机 rollback receipt 到 `.sopcontrol-local/`；
6. 对已有配置使用 merge/chain/isolate/defer；
7. 不自动登记 accepted 规则；
8. 不调用模型。

建议测试：

```text
tests/attachment/test_plan.py
tests/attachment/test_apply.py
tests/attachment/test_idempotency.py
tests/attachment/test_existing_hooks.py
tests/attachment/test_non_git.py
tests/attachment/test_partial_failure.py
tests/attachment/test_rollback.py
```

验收：

- 绿地和存量夹具都能在一次命令后达到 Connected；
- 默认不修改业务源码；
- 第二次运行零语义变化；
- 一个 Adapter 冲突不会拖垮其余接入；
- 所有修改均可从 receipt 解释和预览撤销。

### Phase B：统一动作模型与 Harness 全工具摄取

目标：所有 Harness 工具事件先进入同一个 Action Plane；未知工具也必须留下事件。

实施：

1. 增加 Action Envelope、Decision、Action Result；
2. 将 `check_tool_call` 改成兼容 Wrapper；
3. Claude/OpenCode Adapter 归一全部可见工具，不只 Bash/Write/Edit；
4. Read、search、browser、MCP、unknown tool 先进入 observe；
5. 保持现有 GUARD ID 和 trace 兼容；
6. 解析失败 fail-closed 仅适用于本应受控的高影响动作，普通未知只报告 gap；
7. 事件默认只保存摘要和哈希，不保存文件正文、Cookie 或凭证。

验收：

- 同一语义在 Claude/OpenCode 中生成等价 Envelope；
- 未识别工具不会静默消失；
- 当前控制器保护、no-verify、push gate 和 executor identity 测试全部继续通过；
- 快速路径不发生模型调用。

### Phase C：Control Coverage Ledger

目标：第一次能够诚实回答“项目哪些角落已连接、哪些可观察、哪些可强制”。

实施：

1. 建立执行面枚举和版本化 schema；
2. 合并静态发现、Adapter 声明、运行事件和穿透探针；
3. 新增 `sopctl coverage .` 与 JSON 输出；
4. 分开 scan coverage、connection coverage、control coverage；
5. 对每个 surface 保存来源、freshness、Adapter、证据摘要和 gap 原因；
6. 100% 只允许由穿透探针证明，不允许由 Adapter 自报；
7. 新执行面被发现后自动扩大分母，不能维持虚假的历史 100%。

验收：

- 空白项目不会被报告为 100%；
- 新增未知工具或网络入口后 coverage 必须下降或出现 gap；
- 删除 Adapter 后 verified 状态因证据过期而撤销；
- Worktree 事件不互相污染；
- 报告可以指出具体下一步，而不要求重跑全仓。

### Phase D：受控运行环境

目标：为没有原生 PreToolUse 的平台提供真正的执行前覆盖，而不是只靠事后 gate。

建议新增未来接口：

```bash
sopctl enter . -- <agent-or-command>
```

必须先定义 Runtime Provider Interface，再至少提供一个生产 Adapter 和一个可验证的测试 Adapter：

```python
session = runtime.enter(root, command, policy)
capabilities = runtime.capabilities()
receipt = session.wait()
```

分级实现：

1. cooperative：Harness 主动上报工具调用；
2. supervised：记录主命令和子进程树；
3. isolated：使用容器或平台沙箱控制文件和网络能力；
4. system：未来系统级代理，单独评估权限与安全成本。

不得把仅设置环境变量或 HTTP_PROXY 称为不可绕过控制。若子进程仍可直接访问文件或网络，Coverage Report 必须如实标 gap。

验收：

- Codex 或普通 CLI 可在 supervised session 中获得进程级事件；
- 子进程继承项目和 run identity；
- 会话退出后产生结构化 receipt；
- 未支持的文件/网络强制能力明确显示，而不是假装 verified；
- 受控运行环境故障不会损坏业务工作树。

### Phase E：网络、浏览器、凭证和后台任务

目标：把最容易逃离仓库的副作用纳入通用覆盖。

按风险顺序实施：

1. 网络域名、方法和目标分类；
2. 浏览器实例、profile、CDP session 和页面动作；
3. 凭证 broker，只发作用域和有效期受限的 capability；
4. 数据库写入与事务摘要；
5. scheduler、队列和后台进程登记；
6. 外部写入的幂等键和结果回执。

JobsDB 应成为浏览器 Adapter 的验收用例，而不是写进 Core：

- 能识别是否复用批准的主 Chrome；
- 能把 Cloudflare 人工验证变成有期限的 capability；
- 能记录 WAF 失败和门户级 breaker；
- breaker 语义仍由 JobsFlow Policy Pack 决定；
- SOP Control Core 只提供 ticket、预算、事件和决策原语。

### Phase F：产品化与跨平台验收

目标：把“在开发机能跑”提升为“用户安装后可预测”。

实施：

- macOS/Linux/Windows 安装矩阵；
- Python 3.10–3.12；
- Claude/OpenCode/Codex 当前稳定版本；
- 升级、降级、迁移和 detach；
- P95 接入时间和运行开销；
- 大仓、损坏配置、离线环境和权限不足；
- 文档只展示真实存在的命令。

---

## 9. 强制反例与验收场景

实施者至少增加以下端到端场景。只写正向测试不算完成。

1. 已有非 SOP Control pre-push Hook：接入后原 Hook 仍执行，SOP Control 也执行。
2. `.git` 是 worktree 指针文件：Hook 安装到真实 git-path。
3. Claude settings 是合法 JSON 且有其他 Hook：幂等合并，不改变顺序语义。
4. Claude settings 损坏：Claude 标 gap，项目其他部分仍 Connected。
5. OpenCode 插件目录已有同名他人文件：不覆盖，使用隔离策略或报告局部 gap。
6. 非 Git 项目：身份、事件和 Harness 可用；Git 项显示 unavailable。
7. 大型 Markdown/数据目录：发现 defer，但接入成功。
8. 未知 Harness 工具：产生 unknown surface event，coverage 不得保持满分。
9. 普通 Read 动作：能够记录但不默认阻断。
10. 模型尝试直接写 `.sopcontrol/`：继续由现有 guard 拒绝。
11. 模型尝试 `--no-verify`：继续拒绝。
12. Codex 无调用前 Hook：不得报告 runtime enforceable。
13. Adapter 文件存在但从未触发：只能 detected，不能 verified。
14. 删除 Adapter 后旧证据过期：coverage 降级。
15. 新增网络调用：自动产生新 surface 或 gap。
16. 子进程启动后再启动孙进程：身份和 run_id 可追踪；无法追踪时明确 gap。
17. 同一 idempotency key 重复提交外部副作用：第二次拒绝或返回原 receipt。
18. 接入过程中断：业务配置要么保持旧状态，要么可由 journal/receipt 恢复。
19. 第二次 attach：零重复 Hook、零重复投影、零重复事件消费者。
20. detach 预览：只删除 SOP Control 拥有的安装项，不删除他人配置。

---

## 10. 性能、隐私与可靠性预算

### 10.1 性能

- 默认 attach 不调用模型，Token 成本为 0；
- 首次接入目标 P95 小于 60 秒，超时的发现项 defer；
- warm status 目标 P95 小于 2 秒；
- 每次工具调用只进行本地、增量、缓存化判定；
- 语义分类只在无法由确定性分类器处理且风险值得时升级；
- 已验证且输入 digest 未变化的事实不得重复审理；
- 运行时事件批量落盘，避免逐条全量审计。

### 10.2 隐私

控制事件默认禁止保存：

- 文件完整正文；
- Cookie；
- Token、API Key 和密码；
- 完整 JD、简历和私人材料；
- Shell 环境变量完整快照；
- 浏览器页面完整内容。

只保存：类别、作用域、目标摘要、哈希、计数、决策、错误类型、blocker 和 next action。

### 10.3 可靠性

- observe 路径故障应 fail-open 并高声报告 gap；
- 已确认的高影响 enforce 路径故障应 fail-closed；
- 局部 Adapter 故障不能让整个项目断联；
- 所有安装 mutation 必须有预览、原子应用和回滚 receipt；
- schema 升级必须向后读取，禁止静默丢弃旧事件；
- 不得直接修改 `.sopcontrol/`；所有控制状态变更继续经 `sopctl` 子命令。

---

## 11. 与现有代码的兼容迁移要求

1. 保留现有 CLI 和行为；新增 attach 是编排层，不是重命名 init。
2. 保留现有 Guard ID，避免已有 trace 和规则失去引用。
3. `ControlEvent` 若升级 schema，新增字段优先可选；提供 v1 → v2 解析兼容。
4. `harness.check_tool_call` 保持调用兼容，内部逐步转向 Action Plane。
5. 保留现有 `.sopcontrol/` 权威布局；机器本地安装 receipt、cache、ticket 和事件继续放 `.sopcontrol-local/`。
6. 不在业务项目内复制 SOP Control Python 源码。
7. 不要求 JobsFlow 或其他产品先迁移业务状态机。
8. 不把静态扫描发现自动升级成 accepted/enforced 规则。
9. 不以新增大量 Wrapper 代替通用 Adapter；同类复杂性必须收敛到深模块。
10. 每一阶段先补 Interface 级测试，再替换旧路径；新旧判定逻辑不得长期双写。

---

## 12. 外部模型执行纪律

把本手册交给外部模型时，同时附上以下要求：

1. 开工前读取 `AGENTS.md`、`DESIGN.md`、`LIMITATIONS.md`、`RESIDUAL_RISKS.md` 和本手册。
2. 先运行 `git status --short --branch`；现有未提交内容属于用户，不得 reset、checkout 或覆盖。
3. `.sopcontrol/` 的读取和写入只经 `sopctl`；禁止直接编辑。
4. 每个 Phase 独立创建 SOP Control 任务契约，使用文件级 `allowed_writes`。
5. 不要一次性实现 A–F；完成一个 Phase 的反例、测试和文档后再进入下一阶段。
6. 不得新增尚不可运行的命令到 README 的“当前功能”区。
7. 不得用 Adapter 自报代替穿透证据；存在文件不等于位于调用链。
8. 不得为获得“100%”而排除未知执行面；新发现应扩大分母。
9. 不得默认调用第二个模型做监督；快速路径必须本地确定性运行。
10. 不得让 SOP Control 复制或接管业务状态机。
11. 不得因一个 Harness 配置冲突让整个 attach 失败。
12. 修改后运行相关测试、完整测试、`sopctl gate`，并记录时间与结果。

---

## 13. 总体验收定义

只有同时满足以下条件，才能宣布“全域无阻塞接入”完成：

### 接入体验

- 用户全局安装一次；
- 每个项目执行一次 attach；
- 新项目和中途项目共用同一主链；
- 默认不修改业务源码；
- 冲突局部化，不阻断其他模块工作；
- 接入可重复、可解释、可回滚；
- 默认零模型 Token。

### 全域覆盖

- 每种已发现执行面都出现在 Coverage Report；
- 当前 Harness 的全部可见工具调用进入 Action Plane；
- 未知工具和新副作用会降低覆盖或产生 gap；
- observable、enforceable、verified 有不同证据要求；
- 不支持的系统级能力明确标注；
- 100% 必须经过穿透探针，不接受文字声明。

### 不与业务产品打架

- 业务产品继续拥有业务状态和执行逻辑；
- SOP Control 只拥有规则、权限、任务和证据；
- Adapter 只做翻译；
- 已有 Hook、CI、Harness 配置和文档通过 merge/chain/isolate 接入；
- 任一 Adapter 故障不会损坏业务状态或让全项目不可工作。

### 工程质量

- 原 663 项测试及后续新增测试全绿；
- 综合覆盖率继续满足 `fail_under = 85`；
- 关键逃逸方向有 mutation/反例测试；
- 文档中的命令与真实 parser 一致；
- `sopctl gate` 通过；
- 已知残余风险进入 `RESIDUAL_RISKS.md`，不能用模糊措辞隐藏。

---

## 14. 最终交付路线

最短有效路线不是先做网络沙箱，而是：

```text
Phase A：一次 attach，任何项目先连通
    ↓
Phase B：所有 Harness 工具进入统一 Action Plane
    ↓
Phase C：第一次能证明覆盖到了哪里
    ↓
Phase D：无原生 Hook 平台进入受控运行环境
    ↓
Phase E：网络、浏览器、凭证、数据库与后台任务
    ↓
Phase F：跨平台安装、升级、回滚和性能收口
```

到 Phase C，SOP Control 就已经能够兑现“无需漫长改造即可完整接入，并覆盖当前可观察的每个角落”的核心承诺。Phase D–F 解决的是更强的不可绕过保证和跨平台生产化。

产品最终应坚持这一句话：

> 安装后先让整个项目进入控制视野，而不是先逼用户改造项目；尚未理解的地方继续观察，尚未强制的地方明确标记，但任何已知角落都不能被静默遗漏。
