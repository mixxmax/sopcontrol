# 最终报告（非 JobsFlow 手册 §19，2026-09-14）

## A. 结论

- 当前版本：0.3.0（Beta 口径；禁 GA）。
- 当前 commit：`fced900` 起至本报告任务止（分支 `zcode/living-project-batch1`，本地 ahead，禁 push）。
- 发布判定：**Beta**（本地证据闭合；真实宿主验证待补）。
- JobsFlow 是否执行：**未执行**。
- 除 JobsFlow 外是否还有阻断：有两项已知缺口（见 G）：launcher 真实链归属并发会话文件；
  6 源码 + 6 测试文件仍 untracked 待归属提交。

## B. 修复清单（WP-A～K）

| WP | 原问题 | 修改文件 | 行为 | 兼容 | 新增测试 | 状态 |
|---|---|---|---|---|---|---|
| A | 缺上下文伪装 not_applicable | dynamic_sop/cli_dynamic/cli（前序） | 三桶 + unproven | 是 | 36 项 | delivered(TASK-0108) |
| B | 确认冒充已执行 | dynamic_sop/model（前序） | confirm 止 accepted + compile 证据 | 是 | 永久性 6 项 | delivered(0110) |
| C | 捕获污染/去噪 | dynamic_sop（前序） | 三级捕获 + 去重升级 | 是 | 去噪/来源 | delivered(0111) |
| D | 计数式 diff 虚假 | upgrade（前序） | 逐规则 15 字段 diff | 是 | §8.4 七项 | delivered(0112) |
| E | 空目录假升级 | upgrade.py | plan 只读/staging 真装+探针/原子切换+后验恢复/旧 runtime 真探针 | staged 结构新增，旧 binding 兼容 | 9 项（只读/非空/manifest/损坏fail-closed/回滚保规则/探针防永真） | delivered(0118/0123) |
| F | once-only 无会话绑定 | dynamic_sop/cli_dynamic/cli.py | session 绑定/默认仅当前/轮换/清理 | 旧记录 session 空=当前会话可见 | 隔离/残留/失败/来源 4+1 项 | delivered(0119/0120) |
| G | 无实测基线 | scripts/perf_baseline.py + docs | 四组基准实测 | 无（新增） | 脚本即证据 | delivered(0121) |
| H | 覆盖率口径/负向缺口 | pyproject + 4 测试文件 | omit staged 副本 + 新分支负向 | omit 只剔构建产物 | 后验恢复/坏源/读写失败/未绑定兼容等 | delivered(0122/0123) |
| I | 版本口径/安装未证 | pyproject + docs | Beta 统一 + wheel + clean venv + checkout | classifier Alpha→Beta | 烟测链 | delivered(0124) |
| J | 平台宣称过宽 | product.py + LIMITATIONS | verified 段 + 双 verified 位 | 加字段 | 本机双 true | delivered(0125) |
| K | 缝只被一个产品用过 | examples 双宿主 + 测试 | Host-CLI/API 穿 admission/票据/契约 | 无（新增） | 5 项 | delivered(0126) |

断点 B4/B6/B8（三红收敛 + 脏区）见 TASK-0113/0114/0116/0117，全 delivered。
手册 3（P0-A/B，P1-A～E，P2-A～C）：`sopcontrol/learning.py` 新建，
30 测试，全 delivered（TASK-0127～0136）。

## C. 关键负向证据（均为实跑）

- 缺上下文不激活：select unproven 桶（WP-A，前序）。
- 动态 SOP 丢失阻断升级/回滚：`test_rule_loss_blocks_auto_switch`、
  `test_rollback_refused_if_dynamic_sop_lost`。
- 同数量语义变化被发现：changed_rules 字段级（WP-D + WP-E 伪造改写对照）。
- 空 runtime 不得切换：staging 空目录/坏源拒绝，binding 不动。
- launcher 指向错误版本被拒：**未覆盖**（并发会话持有 bridge_scaffold，见 G）。
- rollback 失败时旧状态保持：探针不一致/不可启动保持当前版本（3 项）。
- once-only 不跨 session：rotate 后旧记录不可读为 active。
- 模型建议未确认不入 registry：P0-A 双基线 + 全链路候选箱隔离。

## D. 性能证据（docs/perf-baseline-2026-09-14.md，复现命令在内）

- admission：内存选择 p50 0.04ms / p95 0.04ms（n=100）。
- 含本地状态：registry 加载+选择 p95 4.05ms；phase grant p95 257ms；
  ticket 全周期 p95 195ms（n=20）。
- cold/warm start：`project check` 冷 1.22s / 热中位 1.13s（n=1+4）。
- LLM 调用：恒 0。ticket/grant：只读 0；同 phase 3 动作 1 grant。
- attach/status：0.29s。增量扫描：连续 audit 中位 2.36s（evidence 2397/次，未达免重复门，降级策略见基线文档）。
- receipt 大小：ticket 文件约 682B。
- 宿主开销：bridge 中位 +0.67ms（+25%，基线为裸 true 派生；≥20ms 负载下 <5%）。

## E. 安装与升级证据（docs/install-evidence-2026-09-14.md）

- wheel：`/tmp/sopcontrol-wheel-check/sopcontrol-0.3.0-py3-none-any.whl`，
  sha256 `d38975f6…bfb3f`，117 文件（entry_points/plugins/新模块齐）。
- clean venv（python3.12）：安装成功；init/attach/observe/confirm/sync(switched)/
  rollback(true)/doctor 全过；系统 python3.9 不可用（<3.10）已记录。
- 两个 runtime 并排：staging `runtimes/0.3.0` + manifest（package_digest + 版本探针）。
- launcher 实际执行版本：**未覆盖**（同 C）。
- sync 结果：blocked（硬门/影子/staging 失败保持旧版）与 switched 皆有实测。
- rollback 结果：true（保规则）与 false（探针失败保当前）皆有实测。
- migration 中断：staging 失败旧 binding 不动；后验失败自恢复旧 binding。

## F. 测试证据

- 全量：1187 passed + 1 skipped（E4，约 270s/轮；本会话 20+ 轮全绿，
  1 次单发 flaky 经 repair 轮收敛）。
- 新增：learning 30 项、upgrade（含 WP-E/H）24 项、双宿主 5 项、
  dynamic_sop（含 F/P0-A）40+ 项、product 10 项。
- skipped：1（既有 repair 用例跳过，非新增）。
- branch coverage（TOTAL 85.3%，fail_under=85 通过；--cov-branch）：
  registry 88.8%、control_lifecycle 96.5%、control_result 84.5%、task 91.6%、
  tickets 92.3%、dynamic_sop 88.6%、upgrade 85.6%、product 88.2%。
  全关键模块 ≥95% 未达——新分支有负向覆盖，存量缺口为后续项（未删门）。
- lint：ruff 全绿/轮；gate 全绿/轮；diff-check 全绿/轮。

## G. 外部验证剩余项（仅真实宿主相关）

- JobsFlow 真实入口覆盖；JobsFlow 产品检查接线；JobsFlow 真实升级演练。
- 第二个真实商业宿主（参考宿主已证明缝通用，但明确非商业证据）。
- 真实宿主弹窗送达（P1-E 标 UNPROVEN）；真实 LLM Distiller（P1-C 标 UNPROVEN）。
- 跨平台真实 runner（Win/Linux fixture 可补，当前只能标 unproven）。
- 已知非外部缺口（不逃避，已在上文如实列为未覆盖）：launcher 真实链、
  untracked 文件归属提交后的 checkout 全量重跑。
