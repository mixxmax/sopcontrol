# SOP Control

**[English](README.md)** · **[中文](README_ZH-CN.md)**

**实验性但可用** — **模型中立的控制平面**，活在**项目里**，不活在聊天记录里。

> 让产品意图在换会话、换模型之后仍然**可执行、可验证、可恢复**——靠长出一块**有限、可编辑的已决事实空间**，而不是堆更多「请你不要……」的提示词。

**状态：** v0.2.0 · 活在项目里的闭环 · [LIMITATIONS](LIMITATIONS.md) · [CHANGELOG](CHANGELOG.md) · [PLAYBOOK](PLAYBOOK.md)

---

## 设计哲学（为什么做这个）

常见的「AI 编码管控」容易掉进两种坑：

1. **提示词剧场** — 系统提示和 Skill 越写越长，一换对话、换模型、换机器就蒸发。  
2. **守卫通胀** — MUST_NOT / 拦截越加越多，**旧入口和平行状态却还活着**。模型照样有旁路可走，你只是多教了它几句可以无视的话。

SOP Control 押的是另一条路：

| 原则 | 落地含义 |
|------|----------|
| **消歧优先** | 宁可**删掉**多余入口，也不要再加一条禁止。成熟度看旁路是否变少，不看规则条数。 |
| **权威活在项目里** | 真相在 `.sopcontrol/`（规则、任务、证据、编年），不在模型记忆里。 |
| **无感发现，人授权** | audit / 拒绝可以*观察*并生成 Candidate；**只有你**能接受规则、enact 删除、deprecate。 |
| **空间可度量、双向** | `ambiguity_index`（旁路开 + 平行状态）消歧后应变**窄**，混乱堆积会变**宽**。 |
| **脊柱零 LLM** | 判定与 harness 决策是确定性的。控制面不该靠再烧一轮 token 来「管」自己。 |
| **合作操作者** | 默认信任：你在自己的机器上。已知绕过诚实写在 [RESIDUAL_RISKS](RESIDUAL_RISKS.md)，不假装已防死。 |

**一句话逻辑：** 收窄模型可游荡的*决策空间*——让下一会话、下一个模型继承的是**同一个世界**。

---

## 它是什么 / 不是什么

| 是 | 不是 |
|----|------|
| 项目内的 Rule / Evidence / Verdict 总线 | 「保证模型永不犯错」 |
| 无感发现缺口与旁路 | 不经你手自动写永久规则 |
| 跨会话 / 跨模型可恢复 | 云端策略 SaaS / SSO 管理台 |
| 人门控的授权与修剪 | 又一个替你「记住」的提示词 Skill |
| 适合中途挂上（doctor 下一刀） | 只服务从零新建的仓库 |

---

## 特色控制能力

| 能力 | 你得到什么 |
|------|------------|
| **规则生命周期** | add → accept → suspend / narrow / deprecate（永久退出两阶段确认） |
| **吸收审计** | MUST 是否真有**生产消费者**（和测试）？gap / pass 可见 |
| **Gate + pre-push** | fail 阻断、gap 告警——本地钩子与 CI 同一扇门 |
| **任务契约** | 有界写入、必填字段/规则、verify/deliver；修复预算随能力档收紧 |
| **无感生长** | finding 与 harness 拒绝自动堆 Candidate，不必你「推进发现」 |
| **消歧 enact** | `candidate enact … --allow …` → 有界**删旁路**任务（不是再加守卫） |
| **空间度量** | `growth measure` / `diff` — 空间有没有**变窄**？ |
| **编年 chronicle** | 给下一模型 / 下一会话看「何以至此」 |
| **瘦投影** | AGENTS.md / CLAUDE.md 切片带 token/行数预算（节能） |
| **轻量 doctor** | 默认三步「下一刀」**不**重扫全仓；需要时再 `--full` |
| **执行者身份** | 任务中途模型不一致写/bash → deny，并提示 `task rebind` |

---

## 换模型为何仍然有效

中途换模型通常会**放宽**可达动作（新模型 + 旧宽松上下文）。SOP Control 这样压住：

1. **项目事实不动** — 规则 / 任务 / 编年在磁盘上。  
2. **`task rebind --model <NEW>`** — 旋钮只**收紧**（与更保守画像取交），不继承上一执行者的放宽。  
3. **Harness 校验** — 载荷声明的 `model` ≠ 已绑定执行者时，写/bash **拒绝**，直到 rebind。  
4. **投影 + 编年** — 新模型读同一套恢复协议和「何以至此」，而不是过期聊天。

各 harness **拦截深度**不同（诚实表态）：

| Harness | 拦截方式 | 实测 |
|---------|----------|------|
| **OpenCode** | 运行时插件 | 已 live |
| **Codex** | 投影 + `sopctl wrap` 事后门 | 已 live |
| **Claude Code** | PreToolUse 协议 | 已适配；live 视 API key |

**同一世界**；不保证每个 IDE 钩子一样深。

---

## 「有效」长什么样（效果）

以下是**机制 + dogfood**结果，不是营销 SLA：

| 证据 | 结果 |
|------|------|
| 产品模拟（`scripts/verify-product-sim.sh`） | 删掉遗留旁路后 `ambiguity_index` **1→0**；enact、rebind、harness 不一致拒绝均成立 |
| JobsFlow 中途挂用 | 规则 `JF-PREVIEW-001` 从 **gap/documented** → **pass / wired_and_tested**（写表边界接上真实 `require_preview`） |
| 节能 | `doctor` 轻量 ≪ `--full`（大仓常约 4～10×）；投影小节预算约 ≤1500 tokens |
| 回归 | `self-test` 穿透 + 语料变异 + 全量 pytest |

报告见 [`docs/verification/`](docs/verification/)（SIM_*、REDTEAM_*）。

**仍须人：** 「团队会不会觉得更省事」要靠真仓用几周，每周看 `growth measure` / `diff`。

---

## 快速开始

```bash
# Python >= 3.10
git clone https://github.com/mixxmax/sopcontrol.git && cd sopcontrol
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
sopctl --help

# 本仓自检
sopctl vertical-check .
./scripts/vertical-check.sh          # 更严（含 pytest）
bash scripts/verify-product-sim.sh   # 抛开真仓的消歧模拟
```

**挂到任意项目（含已成熟的产品仓）：**

```bash
pip install -e /path/to/sopcontrol
# 或：pip install "git+https://github.com/mixxmax/sopcontrol.git"
cd /path/to/your-app
sopctl init .
sopctl identity init .
sopctl hook install .
sopctl project all .
sopctl doctor .                      # 轻量：下一刀，不跑全仓 audit

sopctl rule add --id DEMO-001 \
  --statement "变更必须经统一入口" \
  --modality MUST --status proposed \
  --source-ref README.md --source-type document \
  --consumer-marker demo_gate
sopctl rule accept DEMO-001 .

sopctl audit . --compact             # 观察；persist 时无感生长
sopctl growth measure .              # ambiguity_index 快照
sopctl growth diff .
sopctl candidate enact CAND-… . --allow path/to/bypass.py   # 出现 delete_entry 时
sopctl gate .
```

日用顺序见 [`PLAYBOOK.md`](PLAYBOOK.md)。最小夹具演示：[`examples/minimal`](examples/minimal)。

```text
文档 / 对话 / 运行时拒绝
        ↓  观察（无感）
   Candidates（无授权力）
        ↓  人授权 / enact / 修剪
   .sopcontrol/ 里的规则与任务
        ↓  编译
   投影 · harness · gate · 编年
        ↓
   新会话 / 新模型恢复同一个世界
```

---

## 核心命令

| 命令 | 作用 |
|------|------|
| `sopctl doctor` / `--full` | 自诊 + **下一刀**（默认轻量） |
| `sopctl audit` / `gate` / `self-test` | 观察 · 终点门 · 穿透演习 |
| `sopctl rule …` | 生命周期：add/accept/suspend/narrow/deprecate |
| `sopctl task …` | 契约 → submit → verify → deliver · **`rebind`** |
| `sopctl growth status\|measure\|diff` | 无感生长 + 空间是否变窄 |
| `sopctl candidate enact … --allow …` | 有界删旁路任务 |
| `sopctl chronicle` | 何以至此 |
| `sopctl inventory` | 受控 / 旧入口 / 平行状态 |

产品对抗质检（不是外部攻击红队）：[`docs/verification/REDTEAM_CHECKLIST.md`](docs/verification/REDTEAM_CHECKLIST.md)。

---

## 深入设计文档

| 文档 | 内容 |
|------|------|
| [`DESIGN.md`](DESIGN.md) | 代码为何长成这样 |
| [`docs/SOP_Control_活在项目里的可进化规则空间技术手册_2026-08-31.md`](docs/SOP_Control_活在项目里的可进化规则空间技术手册_2026-08-31.md) | 活空间哲学 |
| [`docs/SOP_Control_产品与技术架构手册_2026-08-23.md`](docs/SOP_Control_产品与技术架构手册_2026-08-23.md) | 产品与架构 |
| [`RESIDUAL_RISKS.md`](RESIDUAL_RISKS.md) | 已知绕过家族 |
| [`ROADMAP.md`](ROADMAP.md) | 权威推进日志 |

---

## 开发

```bash
pip install -e ".[dev]"
pytest -q
./scripts/vertical-check.sh
```

CI：[`.github/workflows/ci.yml`](.github/workflows/ci.yml) · [`.github/workflows/gate.yml`](.github/workflows/gate.yml)

**自用说明：** 本仓 `.sopcontrol/tasks/` 可能含自应用残留。干净演示请用 `corpus/fixtures/` 与 `examples/minimal`。

---

## 许可

MIT — 见 [`LICENSE`](LICENSE)。
