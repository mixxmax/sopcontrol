# JobsFlow 真仓狗粮（控制面 only）

**日期：** 2026-08-26 01:05
**目标仓：** `/Users/xiezhijie/ai-job-search`
**授权：** 仅 `.sopcontrol` + 投影/钩子（不改业务代码）

## 已执行

- `sopctl init` / `identity init` + `lock`
- `intake`（产生 candidates.yaml，observed，未进注册表）
- 登记并 accept `JF-PREVIEW-001`（consumer=`require_preview`）
- `project all` → AGENTS.md / CLAUDE.md 投影小节
- `hook install` → pre-push
- `audit --compact`：JF-PREVIEW-001 → **gap/documented**（生产无 require_preview 消费者）
- `doctor --vertical`：通过
- `gate`：通过（仅 gap 警告，无 fail）

## 结论（2026-08-26）

控制面已在真 JobsFlow 仓武装；规则吸收缺口如实暴露（与构想一致：说过须进代码）。
业务接线留给产品侧；本轮不改 tools/ 业务文件。

## 续：吸收接线（2026-09-02）

- 在 `tools/workflow/confirmation.py` 增加生产消费者 `require_preview`；`adapters/push.py` 在确认→写表边界调用
- `tests/test_scan_entry_boundary.py` 覆盖无预览阻断 / 有预览放行
- 顺手修 sopcontrol：`iter_files` 排除 `.worktrees` 等，否则 500 上限被工作树占满、主树消费者不可见
- 复验：`sopctl audit` → **JF-PREVIEW-001 pass / wired_and_tested**；`ambiguity_index=0`
- JobsFlow 提交：`b01b522`（Wire require_preview…）
