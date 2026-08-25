# 语料（Corpus）

语料不是"问题清单"，是带标准答案的测试集。每条用例必须同时包含断口的两侧：
**规则陈述 + 最小仓库现场 + 期望判定**，外加人工确认的 ground truth。

## 三层结构

```
patterns.yaml   模式库：产品中立的断口模式（documented_rule_no_consumer ...）
fixtures/       夹具：模式在各领域的最小现场
cases.yaml      用例：模式 × 夹具 × 期望判定 → tests/corpus/test_cases.py
task_cases.yaml 任务机脚本化用例 → tests/corpus/test_task_cases.py
```

## 夹具领域

- `jobflow-preview`：求职域（JobsFlow 历史断口蒸馏）
- `shop-checkout`：电商退款域
- `ci-deploy`：CI 发布域
- `web-gate`：TypeScript / Web API 域
- `go-gateway`：Go 服务域
- `rust-gate`：Rust 服务域

**双域验证规则**：模式至少在两个不相关领域命中才算 `proven-on-2-domains` /
`proven-on-multi-domains`（见 `patterns.yaml` 的 `status`）。

## 手册 14.1 必测场景映射（诚实分层）

| 场景 | 覆盖形态 | 主要证据 |
|---|---|---|
| 1 讨论不改码 | 行为（intent + harness） | `tests/constitution/test_intent.py` |
| 2 只更新文档/README | 吸收语料 + 任务机 | CASE-001；TCASE-013 |
| 3 schema/状态只写不读 | 标识符级代理 | CASE-011/014（`write_only_state`） |
| 4 测试 helper 假前置 | 语料 | CASE-008/020（`test_helper_only`） |
| 5 绕过 gateway 旧入口 | 语料 | CASE-009/010（`legacy_entry_alive`） |
| 6 改 verifier 自证 | 行为（完成门） | TCASE-009/010；`test_task_gate` |
| 7 换模型重蹈副作用 | 行为（live 演习） | `scenario7` / harness-eval |
| 8 弱模型漏 MUST 字段 | 行为 | TCASE-011/012；`test_scenario8` |
| 9 扩大写入范围 | 行为 | TCASE-001 |
| 10 规则冲突 | 行为 | `test_conflict` |
| 11 修复两轮熔断 | 行为 | TCASE-002 |
| 12 无 hook 终态门 | 行为 | `test_scenario12` |
| 13 并发 revision | 行为 | `test_concurrency` |
| 14 evidence stale | 行为 | `test_stale` |
| 15 控制器故障 fail-closed | 行为 | TCASE-007；gate/self-test |

**说明：** 「15/15」指考纲条目均有对应证据；其中场景 3 为标识符级代理（非完整
schema 审计），场景 7 依赖 live harness 演习而非单靠 pytest。
