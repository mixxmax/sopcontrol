# Publish checklist (shell → GitHub)

**Repo:** https://github.com/mixxmax/sopcontrol （已创建空库）

## 推荐推送路径（当前工作在 `zcode/living-project-batch1`）

```bash
cd /Users/xiezhijie/sopcontrol

# 1) 确认 URL 已写入 README / pyproject（应已完成）
# 2) 远端
git remote add origin git@github.com:mixxmax/sopcontrol.git 2>/dev/null || \
  git remote set-url origin git@github.com:mixxmax/sopcontrol.git

# 3) 自检
.venv/bin/python -m pip install -e ".[dev]" -q
.venv/bin/pytest -q
./examples/minimal/run.sh

# 4) 推送功能分支或合并进 main 再推
# 方案 A — 先推当前分支，再在 GitHub 上开 PR / 设默认分支：
git push -u origin zcode/living-project-batch1

# 方案 B — 本地并到 main 再推（若你希望默认就是完整 0.2）：
# git checkout main && git merge zcode/living-project-batch1
# git push -u origin main
# git tag -a v0.2.0 -m "sopcontrol 0.2.0 experimental public shell"
# git push origin v0.2.0
```

## 卫生提醒

- 勿把本仓 dogfood 的 `.sopcontrol/tasks/` / ledger 脏改当作发布内容（除非有意）
- `corpus/fixtures/**/.sopcontrol/rules/candidates.yaml` 已 gitignore

## 可选 PyPI

尚未上架；安装用：

```bash
pip install "git+https://github.com/mixxmax/sopcontrol.git"
```

首发文案建议：

> Experimental but real: a model-neutral control plane that lives in the project. v0.2 — see LIMITATIONS.md.
