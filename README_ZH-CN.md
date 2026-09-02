# SOP Control

**[English](README.md)** · **[中文](README_ZH-CN.md)**

<p align="center">
  <img src="docs/assets/sopcontrol-living-boundary.gif" alt="活的项目边界——有限圆环，边缘持续变化" width="960" />
</p>

<p align="center">
  <a href="https://github.com/mixxmax/sopcontrol"><img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/Version-v0.2.0-blue.svg" alt="Version"></a>
</p>

**不要用越来越长的 Prompt 约束 Agent，把架构纪律写进 Git 仓库。**

> **SOP Control** 是一个面向 Coding Agent（Claude Code / OpenCode / Codex / Cursor）的**模型中立本地控制平面**。它不消耗 Token 充当二道贩子，而是通过本地确定性门禁（Git Hooks / 工具拦截）与客观代码证据，防止模型在换会话、换模型、遗留代码诱导下绕过架构规范。

**状态：** v0.2.0 · 活在项目里的闭环 · [LIMITATIONS](LIMITATIONS.md) · [CHANGELOG](CHANGELOG.md) · [PLAYBOOK](PLAYBOOK.md)

---

## ⚡ 痛点对比：失控 vs 接管（Before / After）

当强模型在缺乏物理约束的仓库中工作时，最大的风险不是“写错代码”，而是**在无边界的歧义空间里自由绕行**：

### 真实场景：数据变更必须经过 `AuditLog` 统一写入

* ❌ **传统模式（纯 Prompt 约束）**：
  * **做法**：在 System Prompt 中写满“*修改数据必须调用 safe_update()，严禁直接写表*”。
  * **失控**：当模型遇到复杂任务或遗留的 `raw_update()` 接口时，为了迅速让测试通过，它会绕过拦截直接调用底层接口，甚至顺手删掉校验逻辑。
  * **后果**：任务表面上“交付成功”，但核心业务不变量已在暗中腐烂；新开一个对话或换一个模型，之前的 Prompt 约定彻底蒸发。

* ✅ **SOP Control 模式（本地控制平面接管）**：
  1. **规则落地在仓库**：规则 `RULE-001` 保存在 `.sopcontrol/`，声明调用方标记；
  2. **静态吸收审计**：`sopctl audit` 扫描 AST 发现遗留的 `raw_update()` 未受控，发出 gap 告警；
  3. **确定性物理阻断**：`sopctl gate` 在 Pre-push / CI 与 Harness 运行时直接掐断未授权提交（零 Token 消耗）；
  4. **消歧重构（Enact）**：引导模型执行 `sopctl candidate enact` 生成有界重构任务，**直接物理删除 `raw_update()`**，从根本上收窄模型的犯错空间。

---

## 🛠️ 核心架构与工程闭环

```text
[ 开发者 / CI ]           [ 生产代码 & 遗留代码 ]
       │                            │
       ▼                            ▼
.sopcontrol/ (本地权威)  ◄───  sopctl audit (发现平行状态与旁路)
       │                            │
       ├─► 编译投影 ──► 精简注入 AGENTS.md / CLAUDE.md (<1500 Tokens)
       │
       └─► 确定性拦截 ──► Git Hooks / Harness 拦截 (零 Token 消耗)
                            │
                            ▼
                     阻止未授权动作 / 强迫模型物理删入口
```

### 1. 任务契约与防越权 (Task Contract)
Agent 编码必须在有界契约内执行：显式声明 `allowed_writes`（允许修改的文件白名单）与 `require_rules`。超出范围的修改或缺失必要规则验证，将被直接拒收。

### 2. 真实吸收审计 (Absorption Audit)
规则绝不只停留在文档里。系统通过 AST 语法树解析（支持 TS / Go / Rust / Python），独立检查规则是否真有生产代码消费者（`consumer_markers`）与配套测试（`documented` → `wired` → `wired_and_tested`）。

### 3. 换模型权限对齐 (`task rebind`)
中途换模型常导致权限被意外放宽。SOP Control 强制执行 `task rebind`：新模型的权限旋钮**只收紧、不放宽**（取最严格交集），防止低能力模型继承高权限。

### 4. 空间度量 (Ambiguity Index)
通过 `sopctl growth measure` 捕捉当前仓库的歧义指数（存活旁路 + 平行状态）。重构后通过 `sopctl growth diff` 检验可犯错空间是否真正**变窄**。

---

## 📖 核心术语对照表

为了降低认知门槛，以下是 SOP Control 核心概念与常规工程术语的映射：

| 本项目术语 | 业界通俗工程概念 | 实际解决的问题 |
| :--- | :--- | :--- |
| **消歧 (Eliminate Ambiguity)** | 物理删除未废弃的遗留旁路代码 | 不给模型留下走捷径的物理可能 |
| **吸收审计 (Absorption Audit)** | 静态检查规则是否在代码中被真正消费 | 防止架构规则沦为纸上空文 |
| **执行者身份 (Task Rebind)** | 切换模型时的最小权限交集对齐 | 防止中途换模型导致安全防护降级 |
| **任务契约 (Task Contract)** | 具有文件修改白名单与规则要求的沙盒工单 | 防止 Agent 越权乱改无关文件与基础设施 |
| **编年 (Chronicle)** | 存放在 Git 里的架构决策与演进日志 | 给下一个会话 / 下一个模型看「何以至此」 |

---

## 🚀 快速开始

### 方式 A：2 分钟体验最小沙盒（Minimal Demo）

无需在现有项目中配置，直接查看一次拦截效果：

```bash
git clone https://github.com/mixxmax/sopcontrol.git && cd sopcontrol
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
sopctl gate examples/minimal
```

---

### 方式 B：渐进式接入你的项目（3 步走）

#### Step 1. 零侵入体检（只当体检工具）

```bash
pip install sopcontrol   # 或: pip install "git+https://github.com/mixxmax/sopcontrol.git"
cd /path/to/your-app

sopctl init .
sopctl doctor .          # 诊断当前仓库中的平行状态与潜在旁路，给出下一步建议
```

#### Step 2. 固化第一条核心架构规则

```bash
sopctl rule add --id RULE-001 \
  --statement "数据修改必须经过统一入口 preview_gate" \
  --modality MUST --status proposed \
  --source-ref README.md --consumer-marker preview_gate

sopctl rule accept RULE-001 .
```

#### Step 3. 挂载 Git 门禁与开启任务契约

```bash
# 1. 挂载 pre-push 拦截门
sopctl hook install .

# 2. 为 Agent 派发有界任务（限定只能修改 service.py）
sopctl task open . --model claude-3-7-sonnet --objective "优化结算逻辑" \
  --allow src/service.py --require-rule RULE-001

# 3. Agent 修改完成后提交与验证
sopctl task submit <TASK-ID> . --changed src/service.py --model claude-3-7-sonnet
sopctl task verify <TASK-ID> .
sopctl task deliver <TASK-ID> .

# 4. 终点门禁（本地与 CI 统一拦截卡口）
sopctl gate .
```

---

## 🔌 多 Agent 运行时（Harness）支持

| Harness | 拦截方式 | 支持状态 |
| :--- | :--- | :--- |
| **OpenCode** | 运行时 Plugin 实时拦截 | ✅ 实测可用 (Live-verified) |
| **Codex / Cursor** | 瘦投影注入 + `sopctl wrap` 门禁 | ✅ 实测可用 (Live-verified) |
| **Claude Code** | PreToolUse 钩子协议适配 | ✅ 已适配 (Tool 级拦截) |

---

## 📌 常用命令速查

| 命令 | 场景与作用 |
| :--- | :--- |
| `sopctl doctor .` | **自诊与下一步建议**（轻量模式，快速给出下一步推荐动作） |
| `sopctl audit .` | **规则吸收审计**（静态扫描 MUST 规则是否被代码消费与测试） |
| `sopctl gate .` | **终点门禁**（本地 Git Hook 与 CI 统一阻断入口） |
| `sopctl rule ...` | 规则生命周期管理（`add` / `accept` / `suspend` / `narrow` / `deprecate`） |
| `sopctl task ...` | 任务契约流转（`open` / `submit` / `verify` / `deliver` / `rebind`） |
| `sopctl growth measure / diff` | 空间快照记录与歧义度对比（验证空间是否变窄） |
| `sopctl candidate enact ...` | 一键生成物理删除遗留旁路代码的有界重构任务 |
| `sopctl chronicle` | 查看架构与规则演进编年史 |

---

## 📖 深入文档索引

* 🏛️ [架构设计记录 (DESIGN.md)](DESIGN.md) — 为什么系统长成这样？三原子与纯函数宪法
* 📘 [日常操作手册 (PLAYBOOK.md)](PLAYBOOK.md) — 团队与个人开发的完整操作流与高级编排
* ⚠️ [已知残留风险 (RESIDUAL_RISKS.md)](RESIDUAL_RISKS.md) — 诚实披露已知的绕过场景与防线边界
* 🗺️ [开发路线图 (ROADMAP.md)](ROADMAP.md) — 演进路线与推进日志
* 🤖 [Agent Skill 规范 (SKILL.md)](SKILL.md) — 注入给 Agent 的协作规范说明卡
* 🚫 [能力边界与局限 (LIMITATIONS.md)](LIMITATIONS.md) — 明确声明当前版本不解决什么

---

## 💻 本地开发与测试

```bash
git clone https://github.com/mixxmax/sopcontrol.git && cd sopcontrol
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 运行全量测试与自检
pytest -q
./scripts/vertical-check.sh
```

## 📄 许可证

本项目采用 [MIT License](LICENSE)。
