# JobsFlow 启用包 — 把 SOP Control 从"已铺一半"推进到"日常在跑"

对象仓库：`/Users/xiezhijie/ai-job-search`（下称 JobsFlow）。
预计耗时：第 0–2 步约 15 分钟（一次性）；第 3 步以后无额外人工配置成本，随日常开发顺带发生；每次 verify 仍会按声明运行测试。

## 现状盘点（2026-09-06 实测，不是从零开始）

已就位：

- `.sopcontrol/` 已初始化：`rules/`、`evidence/`（ledger、trace、growth、capability events）、
  `manifest.yaml`、`harness-profile.yaml`、`identity.yaml`
- **一条真规则已 accepted**：`JF-PREVIEW-001`「新岗位入表必须先预览后确认，确认后才能写表」
  （MUST，consumer marker `require_preview`）
- **该规则已在真实代码接线**：`tools/workflow/confirmation.py:88` 定义、
  `tools/workflow/adapters/push.py:566` 生产调用、`tests/test_scan_entry_boundary.py` 真回归测试
- **pre-push 钩子已武装**（`.git/hooks/pre-push`，sopcontrol-hook v1）：push 时自动跑终点门

待补：`manifest.yaml` 缺 `test_command`（完成门无 E4 来源）；从没跑过真实任务契约；
投影状态未确认；其余历史断口尚未登记为规则。

## 第 0 步：环境（一次性）

**首选：零安装，直接用绝对路径**（sopcontrol 的 venv 里已经有能跑的 sopctl）：

```bash
SOPCTL=/Users/xiezhijie/sopcontrol/.venv/bin/sopctl
```

本包后续命令均写作 `$SOPCTL`。注意两点：

- `git push` 时的 pre-push 钩子也会调 `sopctl`：若 sopctl 不在 PATH，push 会被
  钩子报错拦下。这不是故障——先 `export PATH="/Users/xiezhijie/sopcontrol/.venv/bin:$PATH"`
  让钩子真跑门，再 push。不要用 `--no-verify` 绕过。
- 若希望日常直接敲 `sopctl`（免绝对路径），可选持久化安装：
  在 JobsFlow 的 venv 里 `pip install -e /Users/xiezhijie/sopcontrol`。
  安装后 `which sopctl` 应指向 `.venv/bin/sopctl`；若指向 `~/.local/bin` 等不在
  PATH 的目录，说明装进了错误的解释器，删掉后改用绝对路径方案。

## 第 1 步：体检基线（约 5 分钟，写操作发生在 JobsFlow，由你执行）

```bash
cd /Users/xiezhijie/ai-job-search
$SOPCTL doctor .        # 轻量体检：旁路/平行状态 + 下一刀建议
$SOPCTL audit .         # JF-PREVIEW-001 的当前吸收等级（预期 wired/wired_and_tested）
$SOPCTL project all .   # 把控制面切片装进 AGENTS.md / CLAUDE.md
```

验收：audit 表格里 JF-PREVIEW-001 判定 pass；`AGENTS.md` 出现带标记的控制面小节。

## 第 2 步：补 test_command（1 分钟，补上 E4 来源）

用控制器命令声明测试命令：

```bash
$SOPCTL test-command --set "pytest -q"
$SOPCTL test-command
```

验收：第二条命令显示 `test_command: pytest -q`。此后每次完成门 verify 都会真跑
JobsFlow 的测试并铸 E4 证据——没有这一行，任务永远只能停在 E3。

## 第 3 步：首批规则 — 修到哪，登记到哪（需要你判断）

**克制原则**：首批只登记"已被真实代码消费"的规则。`findings.md` 里的其余真实断口
对应的是**待修 bug**，不是待登记规则——正确的顺序是：修 bug 的任务绑契约 → 修复落地
（代码消费出现）→ 再登记规则。把没消费者的规则先登记，audit 只会报 gap 逼你还债。

已完成的第 1 条：

- `JF-PREVIEW-001`（历史断口：新岗位写表无预览确认）。**已接线、已 accepted、有真回归。**

建议的第二批（随修复任务登记，命令草案供届时使用）：

| 候选 id | 真实断口（findings.md 行号） | 登记时机 | statement 草案 | consumer marker |
|---|---|---|---|---|
| `JF-ATOMIC-001` | `jd_cache.py:26-44` 直接 `write_text`，中断可截断缓存（对照 `refresh_state.py:119-149` 的正确模式） | 修该 bug 的任务里接线后 | 共享状态/缓存文件写入必须使用同目录临时文件 + fsync + `os.replace` | `os.replace`（cache/state 写路径） |
| `JF-CURSOR-001` | `fresh_24h_scan.py:830-840` 致命错误判定前推进刷新游标 → 故障窗口职位永久漏扫（发布阻断级） | 修该 bug 的任务里接线后 | 刷新游标只有在本次扫描未遇致命门户错误时才可推进 | 游标写入点符号 |

另有一条**超出控制面首批范围的发现**，建议直接修：
`setup.py:352-369` 会把候选人姓名/求职意向写入 tracked 的 `tools/fresh_24h/queries.json`，
与"真实 PII 只在 gitignored 区域"的隐私目标冲突——发布阻断级，不宜等规则治理。

## 第 4 步：日常回路（无额外人工配置，下次干活时顺带）

下次在 JobsFlow 做真实改动时：

```bash
$SOPCTL task open . --objective "<真实目标>" \
  --allow <本次要改的文件> --require-rule JF-PREVIEW-001 --require-field <输出字段>
# 正常干活
$SOPCTL task submit <TASK-ID> . --changed <实际改的文件>
$SOPCTL task verify <TASK-ID> .     # 独立审计 + 真跑 pytest（E4）
$SOPCTL task deliver <TASK-ID> .
git push                            # pre-push 钩子自动跑终点门，无需手动 gate
```

注意：改动控制器自身相关路径时先 commit 基线再 verify；范围走私会被拒（自愈重试）。

## 成功标准（什么叫"用起来了"）

1. 第一条 E4 证据：完成门真跑过 JobsFlow 的 pytest（`task show` 里出现 E4）。
2. 第一次真实拦截：钩子/guard 拒过一次越权动作或范围走私（capability-events 有 deny 记录）。
3. 第一批来自真实工作的 ambient 候选：`sopctl growth status` 有新观察。
4. JF-PREVIEW-001 或第二批规则在 audit 里升到 wired_and_tested / enforced。

四条全中后，§14.2 的"需要真实使用数据"指标开始有解，且真实使用中长出的缺陷
就是下一批施工的原料。

## 边界与回退

- 本包的写操作全部发生在 JobsFlow 仓库内，由你执行；sopcontrol 自主运行不碰外部仓库。
- 卸 pre-push 钩子 = 删除 `.git/hooks/pre-push`，属人工动作（项目刻意不提供卸载命令）。
- 暂停/退休规则走 `rule suspend` / `rule deprecate`（两阶段人工确认）；撤销 dry-run
  影响会在预览中给出。
