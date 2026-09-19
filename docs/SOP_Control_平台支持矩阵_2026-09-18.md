# SOP Control 平台支持矩阵（2026-09-18）

## 结论

正式支持范围收敛为：**macOS arm64 + CPython 3.12**。这是当前本机真实
runner 的验证范围；它不等同于“所有列在安装矩阵中的平台都已验证”。

Linux、Windows 和 Cursor 在本轮均明确标为 **UNPROVEN**：当前没有对应的真实
runner 结果，也没有为这些平台单独实现并验证 shell hook、路径、权限、symlink、
launcher 和 rollback 行为。

## 矩阵

| 目标 | 声明/安装面 | 真实证据 | 状态 | 说明 |
|---|---|---|---|---|
| macOS arm64 / CPython 3.12 | 在安装矩阵内 | 本机 `.venv/bin/python`、定向测试、CLI smoke | PASS（正式支持） | 当前唯一正式支持平台 |
| Linux / CPython 3.10–3.12 | `INSTALL_MATRIX` 声明可装 | 无 Linux runner | UNPROVEN | 不宣称已验证；需 Linux CI/runner |
| Windows / CPython 3.10–3.12 | `INSTALL_MATRIX` 声明可装 | 无 Windows runner | UNPROVEN | 不宣称已验证；需 Windows hook/path/权限证据 |
| Cursor | README 仅列发现标记、无专门实现 | 无 Cursor 真实宿主 | UNPROVEN | 不列为已支持执行面 |
| OpenCode | 运行时插件适配 | 仓库 harness 测试与本机代码路径 | PARTIAL | 真实宿主环境仍需按安装方式复核 |
| Claude Code | PreToolUse 协议适配 | 协议测试；真实 key/宿主环境不在本轮 | UNPROVEN | 不把协议适配写成真实宿主验证 |
| Codex | projection + wrap / enter + gate | posthoc 路径测试 | PARTIAL | 没有 pre-tool runtime hook；不能宣称实时拦截 |

## 依据与口径

1. 运行时权威声明位于 [`sopcontrol/product.py`](../sopcontrol/product.py) 的
   `INSTALL_MATRIX`（当前约第 21–50 行）：Python/OS 是 declared matrix，
   `verified` 单独明确为 `macOS arm64` 与 Python `3.12`；其余不是 live proof。
2. README 的“支持的执行面”表位于 [`README.md`](../README.md) 第 571–580 行，
   当前表格明确将 Cursor 写为“仅发现标记，无专门实现 / UNPROVEN”，并把
   Codex、Claude 的接入方式与验证限制分开描述。README 本体不在本任务中修改。
3. [`tests/harness/test_product_phase_f.py`](../tests/harness/test_product_phase_f.py)
   覆盖的是产品矩阵结构、兼容检查和本地路径；它不能替代 Linux/Windows/Cursor
   真实 runner 或真实宿主证据。

## 发布时应保持的诚实边界

- “可安装/列入矩阵”与“已在该平台 live-verified”是两个字段，不合并成一个
  跨平台支持承诺。
- 本地参考宿主只证明 adapter seam 的最小可调用性，不是 JobsFlow 或商业宿主
  证据。
- 在补齐真实 runner、宿主 hook、权限和 rollback 证据前，Linux、Windows、Cursor
  继续保持 UNPROVEN。
