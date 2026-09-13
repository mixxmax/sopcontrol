# WP-G 性能基线实测（2026-09-14，darwin-arm64，Python 3.12.13）

方法：`scripts/perf_baseline.py`，`time.perf_counter()`，warm-up 20 与有效样本分离；
进程内基准 n=100，进程级/票据全周期 n=20 或 n=5（下表如实标注）。
复现：`.venv/bin/python scripts/perf_baseline.py`。

## 实测数字

| 基准 | n | p50 | p95 | min/max | 其他 |
|---|---|---|---|---|---|
| 内存内规则选择+admission（50 规则） | 100 | 0.04ms | 0.04ms | 见 JSON | LLM 0，ticket 0 |
| 本地 registry 加载+选择 | 100 | 3.98ms | 4.05ms | 见 JSON | LLM 0，ticket 0，文件读 100 |
| 多步骤 phase grant（3 动作/1 grant） | 100 | 254.75ms | 256.99ms | 见 JSON | LLM 0，grant 100（=样本数，每样本恰 1 次签发） |
| 高影响 ticket 全周期（签发→校验→兑换） | 20 | 192.46ms | 194.83ms | 见 JSON | LLM 0，ticket 20 |
| 冷启动 `sopctl project check` | 1+4 | — | — | cold 1.22s / warm 中位 1.13s | 进程级 |
| `attach-status`（新项目） | 1 | 0.29s | — | — | 进程级 |
| 增量扫描（同一项目连续 audit） | 3 | 中位 2.36s | — | — | evidence 2397 对象/次 |
| 宿主开销 `bridge run true(status)` vs 直接跑 | 20 | 直接 2.65ms / bridge 3.32ms | — | — | 中位比 +25%，绝对 +0.67ms |

## 对 §11.4 目标的判定

- ✅ 稳态低风险 admission 零 LLM：全基准 LLM 调用恒 0（快路径无模型调用）。
- ✅ 纯判定 p95 ≤100ms：0.04ms。
- ✅ 含本地状态普通判定 p95 ≤300ms：registry 路径 4.05ms；phase grant 257ms；ticket 全周期 195ms。
- ✅ 只读零 ticket：只读动作（status）全程无 ticket 签发。
- ✅ 同一 phase 连续计划动作最多一次 grant：3 动作共用 1 grant（`issue_phase_grant` + 3 次免消费校验）。
- ⚠️ 普通宿主流程额外中位时延 ≤5%：**未达（+25%）**。降级说明：基线是裸 `true` 进程派生
  （2.65ms），bridge 绝对开销仅 +0.67ms；命令本体 ≥20ms 的真实工作负载下比例 <5%。
  不删门：后续 WP 在宿主基准中跟踪该比值。
- ⚠️ 无变化项目不得重复全仓昂贵扫描：**未达**——连续 audit 每次全量（中位 2.36s）。
  降级策略：audit 只发生在 gate/verify 显式路径（`testrun.should_run` 防测试内套娃），
  doctor 默认轻量；增量跳过进入后续工作项，不阻塞本次发布门。

原始 JSON：跑脚本重产（`scripts/perf_baseline.py` 输出即证据）。
