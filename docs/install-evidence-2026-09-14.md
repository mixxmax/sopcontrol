# WP-I 安装证据（2026-09-14，darwin-arm64）

版本口径：`pyproject.toml` 已统一 Beta（`Development Status :: 4 - Beta`，
description `(beta)`）；CHANGELOG 0.3.0 仍为 Early Access措辞，不写 GA/Production。
禁提前写 GA —— 遵守。

## 构建（实际命令如实记录）

- `python -m build` 不可用（`build` 包无 `__main__`），用项目允许的等价方式：
  `.venv/bin/python -m pip wheel . --no-deps -w /tmp/sopcontrol-wheel-check`
- 产物：`sopcontrol-0.3.0-py3-none-any.whl`（399KB，117 文件）。
- wheel 内容抽查：`dynamic_sop.py` ✓ `upgrade.py` ✓ `execution_logic.py` ✓
  `goal_contract.py` ✓ `lineage.py` ✓ `operator_contract.py` ✓
  `surface_inventory.py` ✓ `cli.py` ✓，`entry_points.txt` ✓，
  `plugins/` ✓（如发布范围）。

## 干净环境安装（实际命令）

- 系统 `python3` 为 3.9.6（<3.10 且 pip 源旧）：建 venv 装 wheel 失败
  （`tree-sitter-go` 无匹配版本）。**结论：clean venv 必须 ≥3.10，系统 3.9 不可用。**
- `/opt/homebrew/bin/python3.12 -m venv /tmp/sopcontrol-clean-venv` +
  `pip install /tmp/sopcontrol-wheel-check/*.whl`：成功
  （sopcontrol 0.3.0 + pydantic/tree-sitter 系）。
- cwd 在 `/tmp`（非源码目录）冒烟全过：
  `init` ✓ `attach-status` ✓ `dynamic observe` ✓（CAND 落袋）
  `dynamic confirm once_only` ✓（permanent=false）
  `sync --yes` ✓（switched）`rollback` ✓（true）
  `doctor` ✓（MSE 四行节正常输出）。
- 无需激活 shell；不依赖开发机绝对路径（rollback_target 落 venv 内路径）。

## clean checkout（本地 clone，不伪装远端）

- `git clone /Users/xiezhijie/sopcontrol /tmp/sopcontrol-clean-checkout`（HEAD 22c794b）。
- `.venv-check`（python3.12）+ wheel + pytest 就绪。
- 定向 `tests/harness/test_bridge.py`：11 failed / 5 passed ——
  归因：工作区有并发会话未提交文件（`bridge_scaffold.py capability_binding` 等），
  已提交测试依赖其新签名，checkout HEAD 自然缺失。**不是 WP-I 产物的问题**：
  wheel 即从工作区构建（含这些文件），clean venv 冒烟全绿自洽。
- `gate` 在 checkout：通过。
- 遗留事项：6 个源码模块 + 6 个测试文件仍 untracked（`cli_logic/surface/goal/lineage/
  operator/surface_inventory`、`test_p1_*`、`test_growth_joint_fixture`、
  `test_surface_inventory`、`tests/logic/`），需其归属会话提交后重做 checkout 全量；
  本次 checkout 只断言已提交树 + wheel 自洽，不宣称全量通过。
