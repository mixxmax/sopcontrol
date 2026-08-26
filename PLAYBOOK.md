# 垂直骨干日用剧本

一条路径用到底。不求多领域、不求自动修复者——只保证控制闭环可日用。

权威状态见 `ROADMAP.md`；本文件是**操作顺序**，不是产品说明书。

## 0. 一次安装（仓库内）

```bash
cd /path/to/your-project   # 或本仓 sopcontrol
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # 本仓开发
# 或：pip install -e /path/to/sopcontrol
```

CI（本仓已提供）：`.github/workflows/gate.yml` 跑 `pytest` + `sopctl gate`。

确认入口：

```bash
sopctl --help    # 或 .venv/bin/sopctl --help
```

## 1. 项目武装（每个仓库做一次）

```bash
sopctl init .                    # 若尚无 .sopcontrol/
sopctl identity init .           # 项目身份
sopctl identity lock .           # 可选：锁定 id，挪目录不重算（缓解 R11）
sopctl identity export . --out identity-bundle.yaml   # 可携带到另一路径 import
sopctl hook install .            # pre-push 终态门
sopctl project all .             # AGENTS.md + CLAUDE.md 投影
sopctl capability-eval --model local --fixture strong .   # 或 fragile/weak
sopctl capability-compare --live opencode --baseline strong .  # live vs 基线归档
sopctl doctor . --vertical       # 应全部通过；身份与钩子已武装
sopctl project check .           # 投影是否相对 registry 过期
sopctl graph .                   # Python import 邻接（认知薄卡）
```

本仓自检：

```bash
sopctl vertical-check .          # 身份/投影/钩子 + doctor --vertical + audit/gate/self-test
./scripts/vertical-check.sh      # 同上，并额外跑 pytest（更严；二者不等同）
```

## 2. 登记规则（人工授权）

```bash
sopctl rule add --id MY-001 \
  --statement "……必须……" \
  --modality MUST --status proposed \
  --source-ref docs/sop.md --source-type document \
  --consumer-marker my_gate_function
sopctl rule accept MY-001 .
```

Candidate 可先 `sopctl intake .` 或 `sopctl intake . --conversation chat.txt`，**晋升必须显式 accept/add**。

想让规则有机会拿到 `enforced`（手册 6.5 七条件）还要补一次确认书：

```bash
sopctl rule attest MY-001 . --bypass-note "可绕过路径：直接调用底层 API 跳过 my_gate_function；已由 legacy_markers 覆盖"
```

它绑定 `--source-ref` 所指仓内文件的当前 hash。那份文档以后改一个字节，下轮 audit 就自动
撤回 `enforced` 并要求复核——条件7 不靠谁记得来撤。`--bypass-note` 必填且不可为空，因为
「这条规则能被怎么绕过」是分析结论、推导不出来；机制只能保证你想过，保证不了你想对。

## 3. 日常循环

```bash
# 观察断口（--compact 用本轮证据替换账本，去掉 stale 噪音）
sopctl audit . --compact
sopctl explain MY-001 .

# 开任务（弱模型画像会收紧预算/字段）
sopctl task open . --objective "接线 MY-001" \
  --allow src/foo.py --require-rule MY-001 \
  --require-field digest --require-field status   # strict_schema 时需要
sopctl task accept TASK-xxxx .
# …改代码…
sopctl task submit TASK-xxxx . --changed src/foo.py \
  --field digest=abc --field status=ok
sopctl task verify TASK-xxxx .
sopctl task deliver TASK-xxxx .

# 推送前
sopctl gate .
git push   # pre-push 再跑同一扇门
```

讨论不改码时：

```bash
sopctl intake . --conversation chat.txt   # 命中「只讨论」→ discuss_only
# 写工具会被 harness-check 拒绝，直到：
sopctl intent clear .
```

## 4. 换模型 / 换会话

```bash
sopctl project all .              # 刷新投影里的任务状态
sopctl task takeover TASK-xxxx .  # 最小接手包
```

## 5. 闭环验收（骨干役用）

下列全部为真，才算本垂直路径役用闭环：

1. `sopctl doctor .` 通过，且身份已登记、pre-push 已武装  
2. `sopctl audit .` 对本仓自应用规则无意外 fail（gap 按阶梯可警告）  
3. `sopctl self-test` 通过  
4. `sopctl gate .` 在清洁策略下退出码 0（或仅 gap 警告）  
5. `pytest` 全绿  
6. 至少一条真实任务曾走到 `delivered`（本仓：TASK-0001）

## 非目标（留给插卡，不算骨干缺口）

- 多语言深度表面、多行业模式库  
- LLM 意图分类器、自动写补丁的修复者、worktree 隔离  
- 全局 daemon / 跨机器稳定 project_id  
