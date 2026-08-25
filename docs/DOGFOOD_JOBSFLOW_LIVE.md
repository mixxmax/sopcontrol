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

## 结论

控制面已在真 JobsFlow 仓武装；规则吸收缺口如实暴露（与构想一致：说过须进代码）。
业务接线留给产品侧；本轮不改 tools/ 业务文件。
