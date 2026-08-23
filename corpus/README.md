# 语料（Corpus）

语料不是"问题清单"，是带标准答案的测试集。每条用例必须同时包含断口的两侧：
**规则陈述 + 最小仓库现场 + 期望判定**，外加人工确认的 ground truth。

## 三层结构

```
patterns.yaml   模式库：产品中立的断口模式（documented_rule_no_consumer ...）
fixtures/       夹具：模式在各领域的最小现场（jobflow-preview / shop-checkout / ci-deploy）
cases.yaml      用例：模式 × 夹具 × 期望判定 → tests/corpus/test_cases.py 逐条断言
```

## 夹具领域刻意分散

- `jobflow-preview`：JobsFlow 历史断口的蒸馏现场（手册 1.2 症状 3），求职域
- `shop-checkout`：电商退款域，含正向对照与三种吸收状态变体
- `ci-deploy`：CI 发布域，含 test-helper-only 断口（手册 14.1 场景 4）

**双域验证规则**：模式至少在两个不相关领域命中才算 `proven-on-multi-domains`
（见 patterns.yaml 的 status 字段）。合成夹具领域必须与任何真实被审项目无关，
防止检测器过拟合到单一项目的语言习语。

## 与手册 14.1 必测场景的映射（路线）

已覆盖：场景 4（测试 helper 自造前置，CASE-008）；场景 5 的标识符级形态（绕过
gateway 走旧入口，CASE-009/010）。
待建模式：场景 2（实现只更新 README）、场景 3（schema 字段只写不读）、
场景 6（改 verifier 自证，需要 B2 信任根）、场景 7（换模型重蹈副作用，需要 B2 状态机）。
每建一个模式，同步在此登记映射。
