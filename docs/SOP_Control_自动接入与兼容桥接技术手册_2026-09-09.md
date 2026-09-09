# SOP Control 自动接入与兼容桥接技术手册

## 0. 目标

本手册解决一个核心产品问题：

> 用户安装一次 SOP Control 后，无论项目是新建还是已经开发到中途，都能低成本接入；SOP Control 可以覆盖项目中可识别的执行入口；两边不会因为缺少参数、Hook 或 Ticket 传递而在真正执行时互相阻断。

目标用户是使用 Claude Code、OpenCode、Codex、Cursor 等 Coding Agent 的个人开发者和小团队。目标不是把 SOP Control 变成企业策略中心、业务系统或操作系统沙箱。

本文档只描述产品和技术实现方案，不要求用户理解 SOP Control 内部的 registry、ledger 或 Capability Ticket 细节。

说明：文中的 `sopctl bridge ...`、`sopctl attach --verify` 和相关 JSON 接口是本方案的目标接口，当前 CLI 尚未全部提供；外部实施者应先实现接口，再按本文的验收标准验证，不得把目标命令当成现有能力对外宣传。

---

## 1. 先确立三个边界

### 1.1 “零改造”应定义为零业务逻辑改造

SOP Control 可以承诺：

- 默认不改业务算法、业务状态机和业务数据；
- 不要求用户把整个产品重写成 SOP Control 插件；
- 标准入口可以通过 wrapper、plugin、配置合并或 adapter 接入；
- 用户最多确认一个正式入口或一个外部副作用范围。

不能承诺任意产品完全没有接入点。如果业务程序没有 CLI、配置、Hook、wrapper 或可代理的外部边界，外部控制器无法凭空把 Ticket 注入其内部函数。

因此产品承诺应是：

> 零业务逻辑改造，最少一个可自动生成或自动安装的控制接入点。

### 1.2 SOP Control 负责连接体验，业务产品负责业务语义

SOP Control 负责：

- 发现入口；
- 统一调用协议；
- Hook、Plugin、Wrapper 和 Bridge；
- Capability Ticket 的传递和兑换；
- 穿透验证、降级、回滚和报告。

业务产品只需要声明：

- 哪个命令是正式入口；
- 哪些动作属于只读、网络、凭证、浏览器或外部写入；
- 哪些业务规则需要由产品自己解释。

SOP Control 不应猜测业务含义，也不应把业务状态机复制进控制面。

### 1.3 未接入不能等于整个项目不可用

每个执行面必须有明确状态：

```text
detected       发现了入口
connected      已安装连接器
observable     能记录动作
enforceable    能在副作用前作出决策
verified       通过真实无害穿透测试
gap            已知但尚未可观察或强制
unsupported    当前平台明确不支持
```

低风险只读动作遇到 `gap` 时应继续工作并报告；只有已经声明为高影响且应当强制的动作才阻断。不能让一个 Claude settings 或一个外部工具的接入失败拖垮整个项目。

---

## 2. 总体架构

自动接入由六个层次组成：

```text
Install
  ↓
Discovery / Integration Manifest
  ↓
Connection Planner
  ↓
Bridge + Harness Adapters
  ↓
Capability Broker / Action Plane
  ↓
Probe / Coverage / Doctor Report
```

### 2.1 Discovery：发现项目执行面

发现阶段只读项目，不要求模型参与。至少检查：

- Git root、worktree 和已有 hook；
- `pyproject.toml`、`package.json`、Makefile、Dockerfile 和脚本入口；
- 可执行 CLI 和常用测试/扫描命令；
- Claude/OpenCode/Codex/Cursor 配置；
- 网络请求、浏览器、凭证、数据库和后台进程的潜在入口；
- 既有 `.sopcontrol/`、规则投影和历史接入状态；
- 已有第三方 Hook、Plugin 和配置文件。

发现结果应形成一个机器可读的 Integration Manifest。它记录入口和证据，不直接把发现结果升级成权威规则。

建议的入口记录：

```yaml
id: scan.cli
kind: cli
command: "product scan"
source: "pyproject.toml"
side_effects: [network]
ticket_required: true
adapter_candidates: [cli_bridge, subprocess_wrapper]
confidence: structural
```

### 2.2 Connection Planner：生成接入计划

Planner 根据 Manifest 为每个入口选择最轻的连接方式：

1. 已有标准 Plugin/Hook：直接安装或合并；
2. 有稳定 CLI：生成 wrapper/bridge，不改业务源码；
3. 有配置入口：生成最小配置片段；
4. 只有 Python/Node 入口：生成 adapter scaffold，并只要求确认正式入口；
5. 没有可用边界：标记 `gap`，不伪造 `verified`，给出最小人工接入点。

Planner 输出计划后，`attach` 只自动执行安全、可回滚的动作。业务代码、规则权威源和第三方配置不得被静默覆盖。

### 2.3 Bridge：统一调用边界

Bridge 是业务 CLI 和 SOP Control 之间的兼容层。它的职责是：

- 创建稳定的逻辑操作 ID；
- 构造统一 Control Envelope；
- 处理 Ticket challenge/response；
- 调用原始命令或业务 adapter；
- 记录脱敏 receipt；
- 将控制结果映射回业务 CLI 的退出码和输出。

推荐提供统一入口：

```bash
sopctl bridge run --action scan -- <原始扫描命令和参数>
```

或者为已发现命令生成透明 launcher，使用户继续执行原来的命令名。

Bridge 不能只包装进程外壳而不理解业务协议。如果原始 CLI 必须接收 Ticket 字段，则 Bridge 必须通过标准参数、JSON stdin、临时安全文件描述符或 adapter callback 将字段送到真正的 admission point。

---

## 3. 统一 Control Envelope

所有 Harness 和业务 adapter 统一使用一个版本化 envelope。建议最小字段如下：

```json
{
  "schema_version": "1",
  "project_id": "proj-...",
  "worktree_id": "wt-...",
  "integration_id": "scan.cli",
  "operation_id": "op-scan-20260909-001",
  "attempt_id": "attempt-02",
  "task_id": "TASK-...",
  "action": "network.request",
  "input_fingerprint": "sha256:...",
  "side_effect": "network_request",
  "capability_ticket_id": "tkt-...",
  "capability_ticket_secret": "<ephemeral>"
}
```

### 3.1 `operation_id` 和 `attempt_id` 必须分离

- `operation_id` 代表一次逻辑操作，挑战和重试必须保持不变；
- `attempt_id` 代表某一次进程尝试，可以变化；
- Ticket fingerprint 不得绑定每次重试都会变化的随机 attempt ID；
- 不要把 Ticket ID 本身作为生成其 fingerprint 的输入，避免鸡生蛋问题。

这条规则直接解决“第一次签发绑定 scan-A，重试变成 scan-B”的死循环。

### 3.2 Fingerprint 必须可重建

签发和兑换必须使用同一个 canonical payload。指纹可以包含：

- action；
- HTTP method、scheme、host、路径前缀；
- credential scope；
- 目标对象和业务 job ID；
- 稳定 operation ID。

不应包含：

- 当前时间；
- 每次尝试随机生成的 ID；
- 日志顺序；
- secret；
- 仅用于显示的格式化文本。

---

## 4. Capability Ticket 的自动挑战—响应流程

### 4.1 正常流程

```text
Bridge 创建 operation_id
  ↓
提交 envelope（无 ticket）
  ↓
SOP Control 返回 challenge + Ticket
  ↓
Bridge 保留 operation_id、fingerprint 和 ticket
  ↓
使用相同 envelope 重试一次
  ↓
Admission point 兑换 Ticket
  ↓
执行真正副作用
  ↓
记录 receipt
```

用户不应手工复制 Ticket。Ticket 应由 Bridge 在内存、受限临时文件或安全文件描述符中短暂持有。

### 4.2 Challenge 响应格式

建议 challenge 返回：

```json
{
  "decision": "ask",
  "reason": "capability_ticket_required",
  "operation_id": "op-scan-20260909-001",
  "input_fingerprint": "sha256:...",
  "ticket": {
    "ticket_id": "tkt-...",
    "secret": "<ephemeral>",
    "expires_at": "..."
  },
  "retry": {
    "allowed": true,
    "max_attempts": 1
  }
}
```

### 4.3 必须防止的行为

- 没有 ticket 参数却无限重新签发；
- Ticket 无效时无限重试；
- 重试时重新生成 operation ID；
- 重试时偷偷改变 action 或 input；
- 将 secret 打进普通日志、receipt 或模型上下文；
- 预先兑换 Ticket 后再执行动作，导致真正 admission 时票据已被消费；
- 用全局环境变量关闭所有 Ticket 作为正常流程。

### 4.4 只读动作的规则

本地只读扫描、报告生成和静态发现默认不要求 Ticket。

只有以下场景才默认进入 Ticket 流程：

- 外部网络访问；
- 凭证或 Cookie 使用；
- 浏览器/CDP 动作；
- 数据库写入；
- 外部系统写入；
- 费用、配额或不可逆副作用。

这样既保留高影响动作的控制，又不会让普通 scan 成为低效的授权仪式。

---

## 5. `attach` 必须升级为完整编排器

### 5.1 用户入口

```bash
sopctl attach .
```

内部应执行以下阶段：

```text
preflight → discover → plan → apply → probe → report
```

### 5.2 Preflight

检查：

- 是否为 Git 项目；
- 当前用户是否有必要写权限；
- 是否已经安装 SOP Control；
- 是否存在旧版 hook/plugin；
- 是否存在第三方 Hook；
- 控制面是否完整、账本是否损坏；
- 目标 Harness 是否可识别。

Preflight 失败只阻止相应子能力，不应无条件阻断整个项目接入。

### 5.3 Apply

允许自动执行：

- 初始化或升级 SOP Control 自有目录；
- 写入项目身份和投影；
- 安装可识别的自有 Hook；
- 合并 Claude/OpenCode 自有配置段；
- 生成 wrapper、adapter scaffold 和本地 integration manifest；
- 设置可回滚的桥接配置。

禁止自动执行：

- 修改业务算法或业务状态机；
- 删除第三方 Hook；
- 自动接受新权威规则；
- 自动扩大 allowed writes；
- 把未知入口标记为 verified；
- 把整个业务项目复制进 SOP Control 的状态机。

### 5.4 Probe

Probe 必须是真实的无害调用，不接受“文件存在”作为证明：

- Claude：执行真实配置中的 hook command；
- OpenCode：加载并执行实际 plugin callback；
- CLI Bridge：执行 dry-run/fixture callback；
- Ticket：完成一次 challenge → retry → redeem → consume；
- Hook：在无 PATH 但有项目 venv 的情况下执行；
- 失败适配器：应降级为 gap，而不是 verified。

### 5.5 Report

用户报告只需要回答四件事：

1. 哪些入口已经接入；
2. 哪些入口可以强制；
3. 哪些入口还存在 gap；
4. 用户下一步最多需要执行哪一条命令。

报告示例：

```text
SOP Control connected

OpenCode tool calls       verified
Claude PreToolUse         connected / needs live probe
Git pre-push              verified
local scan                observable, no ticket required
external network scan     ticket verified through bridge
unknown browser surface   gap

Next step:
  sopctl bridge install --integration browser
```

---

## 6. 三种接入等级

### Level 1：Zero-touch

适用于已有标准入口：

- OpenCode plugin；
- Claude settings hook；
- Git hook；
- 明确的 CLI wrapper；
- 已有 `ControlEnvelope` adapter。

用户不需要修改业务源码。

### Level 2：One-decision bridge

适用于有命令入口但没有 SOP Control 参数的产品：

1. 自动发现候选命令；
2. 用户确认哪个是正式入口；
3. 自动生成 bridge；
4. bridge 负责 Ticket 和 receipt；
5. 业务命令继续保持原样。

用户只需要确认入口，不需要理解内部协议。

### Level 3：Generated adapter

适用于没有标准边界但可以插入一层调用的产品：

- 自动生成 adapter scaffold；
- 给出一处明确插入位置；
- 自动生成测试样例；
- 可选生成 PR，而不是直接改业务源码；
- 在 adapter 未通过 probe 前显示 gap。

Level 3 不应被包装成零改造，但它仍然比要求用户全面重构产品轻得多。

---

## 7. 自动自检设计

建议提供：

```bash
sopctl attach . --verify
sopctl doctor . --full
sopctl coverage . --probe
```

机器可读模式：

```bash
sopctl attach . --verify --json
```

### 7.1 自检必须覆盖的失败路径

1. CLI 没有 ticket 参数；
2. CLI 有参数但没有把参数写入 payload；
3. challenge 和 retry 的 operation ID 不同；
4. retry 的 fingerprint 不同；
5. ticket secret 错误；
6. ticket 过期；
7. ticket 被重复消费；
8. Adapter 存在但 callback 未触发；
9. Hook 不在 PATH；
10. 第三方 Hook 被错误覆盖；
11. 一个 Harness 失败时其他 Harness 仍可用；
12. 未知工具被标记为 gap，而非虚假满覆盖。

### 7.2 自检输出不能只给错误文本

每个失败项都要包含：

```text
surface
current_state
why
safe_next_action
whether_user_input_is_required
```

例如：

```text
surface: scan.cli
state: gap
why: CLI cannot carry capability ticket
safe_next_action: install generated bridge
user_input_required: confirm canonical scan command
```

---

## 8. 用户交互控制在三次以内

自动接入过程中，最多向用户询问三个问题：

1. 哪个命令是正式产品入口；
2. 哪些外部副作用允许进入控制流程；
3. 是否启用当前发现的 Harness。

以下内容不应询问用户：

- ticket 如何传输；
- fingerprint 如何生成；
- 哪个内部函数调用 `redeem_ticket`；
- ledger 如何写入；
- Hook 如何寻找 venv；
- receipt 如何脱敏。

这些属于 SOP Control 的兼容层职责。

---

## 9. 必须补的核心实现任务

### P0：打通最小闭环

- 定义版本化 `ControlEnvelope`；
- 引入稳定 `operation_id`，把 `attempt_id` 分离；
- 增加 Bridge/launcher 的统一入口；
- 支持 Ticket challenge 自动重试一次；
- 对本地只读 scan 取消不必要的 Ticket 要求；
- `attach --verify` 能报告真实接入状态；
- 缺少接入点时输出 gap 和一条可执行下一步。

### P1：消除接入摩擦

- Hook 安装始终使用 resolver，不依赖当前 shell PATH；
- 升级时自动识别旧版裸 hook；
- 保留第三方 Hook 和配置；
- 生成 wrapper/adapter 时提供回滚；
- 所有 Harness 使用相同的 action 和 fingerprint 规范；
- Ticket secret 不进入日志和模型上下文；
- Ticket 兑换加入跨进程原子锁，防止并发双消费。

### P2：扩大可覆盖范围

- Python、Node、Shell 的通用入口模板；
- Windows/macOS/Linux 的安装和 Hook 矩阵；
- 真实浏览器、数据库和后台进程 adapter；
- 业务产品 Policy Pack，但保持在产品外部，不污染 Core；
- adapter marketplace 或版本化连接器包。

---

## 10. 验收标准

### 10.1 新项目

- 一次 `attach` 完成身份、投影、Hook 和 Bridge 计划；
- 默认不修改业务源码；
- 重复 attach 无语义变化；
- 普通只读 scan 不被 Ticket 阻断；
- 外部网络 scan 能自动完成 Ticket challenge/response；
- `doctor` 给出清晰的连接状态。

### 10.2 中途项目

- 原有 Git Hook 仍执行；
- 原有 Claude/OpenCode 配置不被覆盖；
- 旧入口会被发现并显示为 gap 或 candidate；
- 单个 Harness 配置损坏不会让整个项目无法工作；
- 不需要先重写业务状态机。

### 10.3 Ticket

- 无 ticket 第一次调用只产生一次 challenge；
- 带正确 ticket 且 operation ID 不变时成功；
- 改变输入或动作时拒绝；
- 过期和重复使用时拒绝；
- 失败不会无限签发新 Ticket；
- 并发兑换只有一个成功；
- secret 不出现在普通事件和 receipt。

### 10.4 Harness

- OpenCode：真实 callback verified；
- Claude：真实 settings command verified 或明确 conditional；
- Codex/Cursor：只声明 projection/wrap/Git/CI 终态控制；
- 任意未知工具都不能让覆盖率虚高；
- 适配器文件存在但没有真实触发时只能是 detected/connected。

---

## 11. 发布前命令序列

实现完成后，外部模型按以下顺序执行：

```bash
# 1. 接入计划与自检
.venv/bin/sopctl attach . --verify
.venv/bin/sopctl doctor . --full
.venv/bin/sopctl compat . --measure

# 2. 覆盖与穿透
.venv/bin/sopctl coverage . --probe
.venv/bin/sopctl self-test

# 3. 工程门
.venv/bin/ruff check sopcontrol plugins tests
.venv/bin/pytest -q --cov --cov-report=term-missing
.venv/bin/sopctl project check .
.venv/bin/sopctl gate .
```

每个命令的结果都应记录到发布报告，但不要把用户项目的完整源码、secret、浏览器正文或完整对话写进报告。

---

## 12. 最终设计原则

自动接入的正确形态不是：

```text
安装 → 报错 → 要求用户研究业务源码 → 手工复制 Ticket → 反复调试
```

而是：

```text
安装
  ↓
自动发现
  ↓
自动选择最轻连接方式
  ↓
自动安装 Bridge / Hook / Plugin
  ↓
自动完成无害穿透验证
  ↓
只向用户询问不可推断的业务选择
  ↓
对剩余 gap 给出一条可执行下一步
```

最终目标不是让 SOP Control 接管业务产品的内部逻辑，而是让业务产品的每个重要执行面都拥有一个清晰的控制接入点：已经控制的真实标记为 verified，尚未控制的真实标记为 gap，普通工作不因接入缺口而死循环，高影响动作不会在没有授权的情况下静默执行。
