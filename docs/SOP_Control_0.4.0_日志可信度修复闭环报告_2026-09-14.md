# 0.4.0 日志可信度与发布卫生修复闭环报告

- 日期：2026-09-14
- **未 push / 未 tag**

## 结论

复查列出的 P0/P1 发布阻断已在正式工作区落地并独立抽查。  
当前建议状态：

```text
Release status: READY FOR BETA TAG CANDIDATE (local)
Product core: Beta candidate
Logging/observability: Beta-hardening landed (was Alpha)
GitHub tag v0.4.0: 仍建议先跑一遍全量干净 suite，再授权 tag/push
```

## HEAD

| 仓库 | HEAD |
|---|---|
| SOP Control | `e308ee2` |
| JobsFlow | `2ed4021`（pin → `e308ee2`） |

## 对照复查清单

| # | 问题 | 状态 | 证据 |
|---|---|---|---|
| 1 | gate allow 即 verified completed | **已修** | allow → `action_started`/`observed`；测试 `test_fake_completed_*` |
| 2 | CLI 伪造 verified | **已修** | append 强制 `cli/declared`；伪造不计入 verified |
| 3 | 顶层字段泄密 | **已修** | `test_top_level_free_text_fields_are_redacted` |
| 4 | 轮转/并发/health | **已修** | flock；`log_degraded` → health≠healthy |
| 5 | benchmark 假热路径 | **已修** | 同时报 direct + production p95；prod≥direct，ceiling 500ms |
| 6 | vendor `.DS_Store` | **已修** | 干净 `git archive` 上 `--verify` OK |
| 7 | JobsFlow 脏 push.py | **已处理** | 工作区干净 |
| 8 | eligible 100% 虚高 | **已修** | `eligible_units=unknown` / `partial_observation` |
| 9 | Agent 自兑 confirmation | **已修** | 仅 `--confirmation-id` 仍 `needs_user` |
| 10 | schema pin / CI / learning_observed | **已修** | `EVENT_SCHEMA_VERSION=2`；相关 CI/观察写入在 06c2114 包内 |

## 独立抽查

- activity_log + action_plane：**27 passed**
- JobsFlow learning/vendor/adapter：**23 passed**
- Agent 两次 learn decide（无 secret）：**仍 needs_user，Registry=0**
- 干净 archive `vendorize --verify`：**OK**

## 建议下一步（发布）

1. 在干净 clone 跑 SOP 全量 pytest + JobsFlow 全量（无脏树）  
2. 通过后授权：`git tag -a v0.4.0` 与 push  
3. 在此之前不要把内部 RC 说成已公开发布 Beta  
