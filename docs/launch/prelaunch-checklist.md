# 发布前清单（2026-09-26）

依据：在全新临时仓库里按 README 实际走了一遍首次上手，并用 Claude Code 的真实 PreToolUse 请求格式逐个试探 `sopctl harness-check`。所用版本为本机开发分支 `942d886`；`scripts/demo.sh` 也在 `pip install "git+…@v0.4.0"` 的全新环境里跑过，结果一致。

## 一、阻断项：已修复（TASK-0169，待随下一个版本发布）

下面三处原本会被 HN 读者在第一个小时内试出来，现已修复。修复时又发现第四处：推送检查只认字面的 `git push`，`git -C . push`、`sh -c 'git push'` 等写法会跳过它，一并修了。

- 回归测试：`tests/harness/test_bypass_hardening.py`（81 项）。在修复前的代码上，B1 的 21 个写法、B2 的 6 个写法、B3 的 11 个写法全部放行，推送的 8 种写法里有 6 种跳过了检查；修复后全部按预期拒绝，只读命令和未上锁时的正常写入照常放行。
- 演示：`scripts/demo.sh` 增加了对应场景（Bash 写入、自行解锁、删钩子、`core.hooksPath` 跳过），并已接进 CI。

### B1 「只讨论」锁挡不住 Bash 写文件

- **复现**：先让会话进入 discuss_only，再发送 Bash 工具调用 `echo hi > src/app.py`、`sed -i '' s/a/b/ src/app.py`。两者都返回 `allow`，理由是「不在受控动作清单（观察模式）」。
- **影响**：演示里最打动人的场景，换一个工具就绕过了。
- **建议修法**：discuss_only 期间，Bash 只放行只读命令的白名单（`ls`、`cat`、`head`、`tail`、`grep`、`rg`、`find`、`git status/diff/log/show`、`sopctl … show/list/status`），其余一律拒绝，理由沿用 discuss_only 的说明。不要试图去识别"哪些命令会写文件"，白名单更简单，也更安全。

### B2 Agent 能自己解锁

- **复现**：discuss_only 期间，发送 Bash 调用 `sopctl intent clear .`，或者先写一个含「可以改了」的文件，再执行 `sopctl intake . --conversation <file>`。两者都返回 `allow`。
- **影响**：锁可以被被锁的一方自己解开。
- **建议修法**：把 `sopctl intent clear` 和 `sopctl intake --conversation` 纳入 `GUARD-CONTROLLER-BASH`。Agent 的工具调用一律拒绝，只允许人在终端里执行。

### B3 推送前的检查能被 Bash 卸掉

- **复现**：Bash 调用 `rm .git/hooks/pre-push`、`chmod -x .git/hooks/pre-push`、`git config core.hooksPath /dev/null`，都返回 `allow`。对照组：改 `.claude/settings.json` 会被 `GUARD-SELF-UNINSTALL` 拒绝。
- **影响**：`--no-verify` 被拦下了，但 `rm` 能达到同样的效果。
- **建议修法**：把 `GUARD-SELF-UNINSTALL` 扩展到涉及 `.git/hooks/pre-push` 的 Bash 命令，以及任何设置 `core.hooksPath` 的命令。

**验收方式**：以上场景已作为 DENY 场景加进 `scripts/demo.sh`，CI 每次运行它，演示本身就是回归测试。

## 二、首次上手的摩擦：建议在发布前后尽快处理

| # | 现象 | 建议 |
|---|---|---|
| F1 | 接受一条规则要先 `confirm request --digest <摘要>`，而摘要要自己用 Python 算 `change_digest(rule_id, statement)`，没有命令会打印它 | `confirm request --kind rule-accept --subject RULE-001` 自动计算摘要；或者在交互式终端里，`rule accept` 直接询问 y/n |
| F2 | 对不存在的任务执行 `sopctl task accept TASK-0003`，打印出 Python 的 `KeyError` 堆栈 | 改成一行友好的错误信息，并列出现有任务 |
| F3 | 新规则如果没有 `guard_ids`，就只是 "unwired"（只记录、不生效），`rule add` 时没有任何提示 | `rule add` 时明确说明"已记录，但在接线之前不会拦截任何动作"，并给出接线的方法 |
| F4 | `sopctl hook claude` 只安装 PreToolUse 钩子，所以用户在 Claude Code 里说「只讨论」并不会自动上锁 | 同时安装 UserPromptSubmit 钩子，把用户消息交给 `intake`。这样最有共鸣的那个场景才能真正开箱即用 |
| F5 | 任务范围只在 `task submit` 时检查，写入的那一刻不拦 | 任务执行期间，对范围之外的 Write/Edit 直接拒绝 |
| F6 | 没有发布到 PyPI，`pip install sopcontrol` 装不上 | 发布到 PyPI（这本来也是 GA 阻断项之一），快速开始改成 `pip install sopcontrol` |
| F7 | README 在快速开始之前有大量概念（规则空间、产品本体、动态 SOP、自然逻辑……） | 快速开始已经移到最前面；之后可以考虑把理论部分移到 DESIGN.md，README 只保留链接 |
| F8 | `docs/HANDOFF_2026-09-26.md` 里写着"私有仓库、0.4.0 未发布" | 已过时：仓库是公开的，v0.4.0 已于 2026-09-14 发布 |

## 三、发布顺序建议

1. ~~修 B1 到 B3，加进演示和 CI~~（已完成）；验证 TASK-0169 后发 v0.4.1。
2. 把 README「接到你自己的项目」里的版本号从 `@v0.4.0` 改成 `@v0.4.1`（如果 F6 已完成，就改成 `pip install sopcontrol`）。在此之前，从 `@v0.4.0` 安装的用户还没有这些修复。
3. 用 `vhs scripts/demo.tape` 录 GIF，放在 README 顶部。
4. 工作日美国东部时间上午发 Show HN，发布后的头两个小时守着回复。
5. 当天发 V2EX「分享创造」、即刻、掘金；隔天发小红书。
6. 一周后看三个信号：星标、issue 数，以及有没有团队主动来问怎么落地。
