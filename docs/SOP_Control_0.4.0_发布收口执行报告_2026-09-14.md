# SOP Control 0.4.0 最终发布与运行日志闭环 — 执行报告

- 日期：2026-09-14
- 手册：`docs/SOP_Control_0.4.0_最终发布与运行日志闭环修复技术手册_2026-09-14.md`
- **未 push**

## 实际基线（执行后）

| 仓库 | 分支 | HEAD | 版本 |
|---|---|---|---|
| SOP Control | `zcode/living-project-batch1` | `a6533f0`（含日志功能 `4a51c34` + docs） | **0.4.0** |
| JobsFlow | `codex/sopcontrol-0-3-0-learning` | `a3a90ce`（或后续 retarget commit） | vendor **0.4.0** |

`tools/sopcontrol_pin.txt` ≡ `vendor/sopcontrol/PIN.txt` ≡ `VENDOR_MANIFEST.json` commit/pin/source_commit；`manifest.version` ≡ `sopcontrol.__version__` ≡ **0.4.0**。

## 工作包 A：发布阻断

| 项 | 结果 |
|---|---|
| A1 project all/check | **PASS**（AGENTS/CLAUDE OK） |
| A2 vendorize + manifest digest | **PASS**（`tools/vendorize_sopcontrol.py`，两次 idempotent；CI `--verify`） |
| A3 公开文档 0.4.0 Beta | **PASS**（README EN/ZH、LIMITATIONS、PUBLISH、CHANGELOG；头图未改） |
| A4 CI pin/manifest/import | **PASS**（ci.yml 增加 verify） |
| 干净 venv 安装版本一致 | **PASS**（`__version__` 与 `importlib.metadata` 均为 0.4.0） |
| C5 dynamic confirm 无凭据 | **PASS**（needs_user，Registry 不增） |

## 工作包 B–E：活动日志

| 项 | 结果 |
|---|---|
| 扩展 `events.py` + `activity_log.py` | **PASS** |
| `sopctl log list/show/report/health/benchmark` | **PASS**（实测 list/report/health；benchmark p95≈0.74ms ≤5ms） |
| action_plane / bridge / learning 接线 | **PASS**（已提交） |
| JobsFlow admit/receipt 写活动事件 | **PASS**（失败降级） |
| 热路径零 LLM / 零额外 ticket | **PASS**（设计+benchmark） |
| 日志非权威、不放行 | **PASS**（report 区分 verified/unproven） |

## 测试（本轮定向）

- SOP：`test_activity_log` + dynamic learning/sop → **107 passed**
- JobsFlow：vendor + learning + adapter + beta + interaction → **55 passed**

全量 1265 未在本轮重跑；以定向套件 + 干净安装 + gate/project check 为发布收口证据。若要 tag `v0.4.0`，建议再跑一次全量 pytest。

## 日志用法

```bash
cd /Users/xiezhijie/sopcontrol
.venv/bin/sopctl log list .
.venv/bin/sopctl log show . --run-id <run-id>
.venv/bin/sopctl log report . --run-id <run-id> --format markdown
.venv/bin/sopctl log health .
```

报告目录：`.sopcontrol-local/reports/`（不进 Git）。

## 发布建议

- **状态：Beta / early public（可公开发布候选）**，不是 GA
- 本地已统一到 0.4.0；**未经委托不 push / 不打 tag**
- 建议授权后再：`git push` + `git tag -a v0.4.0`
