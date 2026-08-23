# SOP Control

**意图—规则—交付的编译器与控制平面**（行走骨架 v0.0.1）

> 让用户的产品意图不再依赖某个模型记得，也不再停留在对话里；让规则经过治理后成为
> 代码可以执行、系统可以验证、失败可以修复、换模型可以延续的长期产品能力。

设计与调研手册见 [`docs/`](docs/)；建构决策记录见 [`DESIGN.md`](DESIGN.md)；
已知绕过家族的诚实登记见 [`RESIDUAL_RISKS.md`](RESIDUAL_RISKS.md)。

## 当前状态：B4 harness 适配 + B5 模式库扩展

- **Claude Code 适配**：`sopctl hook claude` 安装 PreToolUse 钩子（项目级、合并式、幂等）；
  `sopctl harness-check` 按 Claude 协议输出 allow/deny/ask 决策。策略：控制器文件禁止普通
  写入口触碰（信任根）、`--no-verify` 一律拒绝、`git push` 走终点门三态（fail→deny、
  gap→ask、clean→allow）、门上下文缺失 fail-closed。协议字段已对照官方文档核实。
- **检测模式库（8 模式）**：新增 `write_only_state`（只写不读代理，info）、
  `state_in_parallel_files`（双处维护真源不明，gap）、`state_marker_absent`（声明状态不存在，
  info），各配跨领域夹具与语料用例。
- **自应用闭环**：本次模式库扩展本身经任务机交付（契约→submit 范围检查→完成门独立
  审计 SELF-001/002→delivered），TASK-0001 存于本仓库 `.sopcontrol/`。

B0–B3 能力见 git 历史；检测器仍为 grep 智力（边界见 RESIDUAL_RISKS.md）。

- `sopctl task open/accept/submit/verify/deliver` —— 任务契约 → 受控执行 → 完成门 → 交付
- 完成门只信独立审计（E3）：required_rules 全部 pass 才 verified；fail → blocked（人工）；
  gap → repair_required（默认两轮熔断 → failed_unverified）
- 范围走私（契约外路径）拒绝该次提交，可自愈重试；revision 防旧上下文覆盖新状态
- `sopctl intake` —— 意图编译器 v0：文档 MUST 句 → CandidateRule（observed，永不写注册表）
- `sopctl repair open <finding_id>` —— 有界修复：断口 → 指纹绑定修复任务（重复开单拒绝、
  同指纹熔断转人工、预算两轮；修复智能在脊柱之外，人在契约内完成最小修复）

检测器仍为 grep 智力（边界见 RESIDUAL_RISKS.md）。

## 快速开始

```bash
# 安装（Python >= 3.10）
pip install -e ".[dev]"

# 跑语料与宪法测试（验收方式）
pytest

# 在目标项目上使用
sopctl init /path/to/project
sopctl rule add --id PUSH-001 \
  --statement "新岗位入表必须先预览后确认" \
  --modality MUST --status proposed \
  --source-ref docs/sop.md --source-type document \
  --consumer-marker require_preview
sopctl rule accept PUSH-001 /path/to/project
sopctl audit /path/to/project            # 观察模式：只建议，不阻断
sopctl audit /path/to/project --strict   # CI 门：存在 gap/fail 时退出码 1
sopctl explain PUSH-001 /path/to/project # 谁消费、证据是什么、为什么
sopctl doctor /path/to/project           # 安装自诊：注册表/账本完整性/插件/终态门
sopctl gate /path/to/project             # 终点门（hook 与 CI 调用同一入口）
sopctl hook install /path/to/project     # 安装 pre-push 终态门
sopctl self-test                         # 穿透演习：验证 gate 真实有效
sopctl task open . --objective "接线 X" --allow src --require-rule X-001
sopctl task accept/submit/verify/deliver TASK-0001 .
sopctl intake .                          # 文档 MUST 句 → 候选规则（不写注册表）
sopctl hook claude .                     # 安装 Claude Code PreToolUse 钩子
echo '{"tool_name":"Bash","tool_input":{"command":"git push"}}' | sopctl harness-check .
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
