# SOP Control

**意图—规则—交付的编译器与控制平面**（垂直骨干 v0.1.0）

> 让用户的产品意图不再依赖某个模型记得，也不再停留在对话里；让规则经过治理后成为
> 代码可以执行、系统可以验证、失败可以修复、换模型可以延续的长期产品能力。

设计与调研手册见 [`docs/`](docs/)；建构决策记录见 [`DESIGN.md`](DESIGN.md)；
已知绕过家族的诚实登记见 [`RESIDUAL_RISKS.md`](RESIDUAL_RISKS.md)。

## 当前状态：垂直骨干役用闭环 + 14.1 覆盖 15/15

日用顺序见 [`PLAYBOOK.md`](PLAYBOOK.md)；模型交互见 [`SKILL.md`](SKILL.md)。  
本仓自检：`sopctl vertical-check .`（身份/投影/钩子/audit/gate/self-test）。  
完整含 pytest：`./scripts/vertical-check.sh`（多跑测试套件，二者不等同）。

- **OpenCode（运行时拦截，已实测）**：`sopctl hook opencode` 安装 `.opencode/plugins` 插件，
  `tool.execute.before` 调 `sopctl harness-check` 决策。真实模型演习：Edit 控制器文件被当场
  拒绝，模型转述理由后停止。
- **Codex 0.147（无运行时钩子 → 建议+终态，已实测）**：`sopctl project codex` 生成 AGENTS.md
  规则投影（模型会主动遵守，演习中它真的尝试运行 gate）；`sopctl wrap codex -- <args>`
  事后门（真实会话后 gate 阻断，退出码 1）；git/CI 终态兜底。
- **Claude Code（运行时拦截，协议已核实）**：适配完成；本机无 API key，待有 key 环境实测。
- **拦截组件自保护**：删除 opencode 插件/claude 钩子配置 = 卸项圈，一律拒绝（人工动作）。
- 能力画像落盘 `.sopcontrol/harness-profile.yaml`（live_verified 如实记录）。
- **模型能力握手**：`capability-eval --fixture/--responses` 只做离线校准，永不授予宽权限。
  只有 `capability-eval --live` 的真实探针结果，经人工交互执行 `capability-approve` 并绑定本次
  `evaluation_id` 后，`task open --model X` 才可使用画像。未批准、重新评测、身份不匹配、
  探针不完整或 tier 不一致一律按 `unknown` 保守执行：每个 allow 项只授权该精确路径、
  强制 MUST 字段、修复预算最多 1 轮。
- **被动行为画像**：任务拒绝会为对应模型写入独立的 `weak` 安全上限，普通遥测压缩不能解除；
  人工批准画像会锚定状态文件，批准有效时文件缺失或损坏均 fail-closed。同一拒绝重放不续期，
  只有新的拒绝按原始发生时间计算 30 天到期。成功记录只产生建议，不能自动升权或清除上限。
  使用 `sopctl capability-events . --model X` 只读查看事件完整性、建议和当前上限。

B0–B3 能力见 git 历史；检测 10 模式（Python 以 AST 为准，JS/TS/Go/Rust 为词法剥离后
的标识符级代理，边界见 RESIDUAL_RISKS.md）。

- `sopctl task open/accept/submit/verify/deliver` —— 任务契约 → 受控执行 → 完成门 → 交付
- 完成门只信独立审计（E3）：required_rules 全部 pass 才 verified；fail → blocked（人工）；
  gap → repair_required（按任务契约的能力预算熔断；unknown/无画像默认 1 轮）
- 范围走私（契约外路径）拒绝该次提交，可自愈重试；revision 防旧上下文覆盖新状态
- `sopctl intake` —— 意图编译器 v0：文档 MUST 句 → CandidateRule（observed，永不写注册表）
- `sopctl intake --conversation chat.txt` —— 对话意图：discuss_only 锁定写工具；永久政策→Candidate
- `sopctl candidate refresh|list|show|triage|batch-triage` —— 冷路径聚合重复 guard/Finding/纠正；3 个独立 occurrence 才物化；批量裁决全成或零变更；Candidate 永不自动授权或晋升
- `sopctl intent show|clear` —— 查看/解除讨论锁定（14.1 场景1）
- `sopctl repair open <finding_id>` —— 有界修复：断口 → 指纹绑定修复任务（重复开单拒绝、
  同指纹熔断转人工、预算两轮；修复智能在脊柱之外，人在契约内完成最小修复）
- `sopctl repair apply <task_id>` —— 自动修复者 v0：在 git worktree 隔离内调模型改动，
  回主树时按 `allowed_writes` 过滤、硬排除 `.sopcontrol/`，契约外改动随隔离树销毁

## 快速开始（垂直骨干 0.1.0）

```bash
# 安装（Python >= 3.10）——开发态（本仓）
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 或从 git 预习安装（将 URL 换成你的远端；当前未正式发布到 PyPI）
# pip install "git+https://github.com/YOUR/sopcontrol.git"

# 确认入口
.venv/bin/sopctl --help

# 本仓役用自检（身份/投影/钩子/audit/gate/self-test；不含 pytest）
.venv/bin/sopctl vertical-check .
# 含 pytest 的完整脚本：
./scripts/vertical-check.sh

# 跑语料与宪法测试
.venv/bin/pytest -q

# 在目标项目上使用
sopctl init /path/to/project
sopctl rule add --id PUSH-001 \
  --statement "新岗位入表必须先预览后确认" \
  --modality MUST --status proposed \
  --source-ref docs/sop.md --source-type document \
  --consumer-marker require_preview
sopctl rule accept PUSH-001 /path/to/project
sopctl rule attest PUSH-001 /path/to/project --bypass-note "……"  # 条件5/7：绑定源文档版本 + 绕过分析
sopctl audit /path/to/project            # 观察模式：只建议，不阻断
sopctl audit /path/to/project --strict   # CI 门：存在 gap/fail 时退出码 1
sopctl explain PUSH-001 /path/to/project # 谁消费、证据是什么、为什么
sopctl doctor /path/to/project           # 安装自诊：注册表/账本完整性/插件/终态门
sopctl gate /path/to/project             # 终点门（hook 与 CI 调用同一入口）
sopctl hook install /path/to/project     # 安装 pre-push 终态门
sopctl self-test                         # 穿透演习：验证 gate 真实有效
sopctl task open . --objective "接线 X" --allow src/x.py --require-rule X-001 --require-field status
sopctl task accept TASK-0001 .
# 修改后提交时携带 MUST 字段；随后依次 verify / deliver
sopctl task submit TASK-0001 . --changed src/x.py --field status=ok
sopctl intake .                          # 文档 MUST 句 → 候选规则（不写注册表）
sopctl hook claude .                     # 安装 Claude Code PreToolUse 钩子
sopctl hook opencode .                   # 安装 OpenCode 运行时插件
sopctl project codex|claude|opencode|all .  # 规则投影（AGENTS.md / CLAUDE.md）
sopctl wrap codex . -- exec -s workspace-write "任务"   # 事后门 wrapper
echo '{"tool_name":"Bash","tool_input":{"command":"git push"}}' | sopctl harness-check .
sopctl capability-eval --model demo --fixture fragile .   # 模型画像（不烧 token）
sopctl intake . --conversation chat.txt                   # 对话意图（讨论≠改码）
sopctl intent show .
sopctl identity init .                                    # 项目身份（Phase 6 种子）
```

## 三个原子

| 原子 | 是什么 | 落在哪儿 |
|---|---|---|
| Rule | 用户意图的规范化记录（出处/强度/scope/生命周期/消费者标记） | `.sopcontrol/rules/registry.yaml` |
| Evidence | 独立于模型自报的观测（E3 级，带 input_hash 与 valid_until） | `.sopcontrol/evidence/ledger.jsonl`（追加式） |
| Verdict | 纯函数判定 `(规则, 事实) → 判定 + 理由 + 下一步` | `sopcontrol/verdict.py`（无 I/O、无 LLM） |

插件只有三种形状：sensor（产 Evidence）、detector（产 Finding）、actuator（消费
Verdict，B1 起接入 git hook / CI）。登记处在 `plugins/__init__.py`。

## 目录

```
sopcontrol/     脊柱：model / registry / ledger / verdict / audit / cli
plugins/        插卡：sensors(code_scan, doc_scan) + detectors(no_consumer)
corpus/         语料：模式库 + 跨领域夹具 + 期望判定（tests/corpus 逐条断言）
tests/          宪法测试 + 语料表驱动测试
docs/           产品与技术架构手册 + 生态调研
```

## 吸收等级

`documented`（只有文档）→ `wired`（有生产消费者，无回归证据）→
`wired_and_tested`（消费者与回归齐备）→ `enforced`（手册 6.5 七条件齐备，v0 不颁发）。
