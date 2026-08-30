# CTRL-001 — 控制器状态写保护

## 规则

控制器状态目录 `.sopcontrol/` 内任何文件不得直接读写或修改；一切写入必须经
`sopctl` 子命令。

本规则是仓库 `AGENTS.md` 硬约束第 1 条的规则化登记：原文由用户于 2026-08-23
前后写入，本页只做结构化转述，不引入新义务。

## 范围

- 对象：项目内 `.sopcontrol/` 目录下全部文件（registry / ledger / trace 日志 /
  任务账本 / 画像等）。
- 主体：所有 Agent 工具调用（文件写入类工具、shell 类工具），无论哪个 harness。
- 例外：`sopctl` 自身（命令行含 `sopctl` 即豁免）与人工直接操作——人工不经过
  本产品的拦截层，属于带外通道。

## 什么算生产消费者

- `sopcontrol/harness.py::touches_protected_path` —— 判定写入路径是否落在
  `.sopcontrol/` 内（按路径分量大小写不敏感比对）。
- `sopcontrol/harness.py::check_tool_call` —— 工具调用决策入口，把上述判定
  编入 GUARD-CONTROLLER-WRITE 决策。

## 什么算运行时执行

GUARD-CONTROLLER-WRITE 在真实 harness 会话中对工具调用作出决策（allow 或
deny 均算「被咨询」），事件由 `sopctl harness-check` 落盘到
`.sopcontrol/evidence/trace.jsonl`，由 `trace_scan` 传感器摘成 E4 证据。

## 绕过分析（条件5）

已知可绕过路径及为什么可接受：

1. **人工直接编辑** —— 人不经过拦截层，属带外通道；账本完整性校验
   （gate 的篡改检测）是第二道防线，事后必暴露。
2. **卸载插件/钩子** —— 被自保护守卫（GUARD-SELF-UNINSTALL）拦截，视为提权；
   真要卸载是人工动作，等于显式退出本控制平面。
3. **`--no-verify` 跳过 pre-push 门** —— GUARD-NO-VERIFY 拦截；CI 终点门为后盾。
4. **符号链接 / 大小写变体把写引出范围** —— R8 三层守卫（分量 casefold、
   symlink 解析）2026-08-26 闭环，语料含对应用例。
