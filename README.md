# SOP Control

**意图—规则—交付的编译器与控制平面**（行走骨架 v0.0.1）

> 让用户的产品意图不再依赖某个模型记得，也不再停留在对话里；让规则经过治理后成为
> 代码可以执行、系统可以验证、失败可以修复、换模型可以延续的长期产品能力。

设计与调研手册见 [`docs/`](docs/)；建构决策记录见 [`DESIGN.md`](DESIGN.md)；
已知绕过家族的诚实登记见 [`RESIDUAL_RISKS.md`](RESIDUAL_RISKS.md)。

## 当前状态：B0 行走骨架

一个最小闭环已经可以行走：规则登记 → 传感器观测 → 检测器识别断口 → 纯函数判定 →
追加式账本 → 可解释输出。检测器刻意保持在 grep 智力水平——骨架要证明的是接口与判定
链路，不是检测智力。

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
sopctl doctor /path/to/project           # 安装自诊：注册表/账本完整性/插件
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
