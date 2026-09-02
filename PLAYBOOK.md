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

# 所有 lifecycle 动作都先预览；确认时原样重跑并带回同一快照的 preview_id
sopctl rule suspend MY-001 . --until 2026-09-01T12:00:00Z \
  --reason "维护窗口" --by human-reviewer
sopctl rule suspend MY-001 . --until 2026-09-01T12:00:00Z \
  --reason "维护窗口" --by human-reviewer --confirm-preview <PREVIEW-ID>
sopctl rule reinstate MY-001 . --reason "维护提前结束" --by human-reviewer
sopctl rule narrow MY-001 . --scope src/payments \
  --reason "仅保留支付路径" --by human-reviewer

# 永久退出同样先预览再确认；用新规则接管时改用 supersede --replacement NEW
sopctl rule deprecate MY-001 . --reason "结构保证已替代" --by human-reviewer
sopctl rule deprecate MY-001 . --reason "结构保证已替代" --by human-reviewer \
  --confirm-preview <PREVIEW-ID>
```

暂停在截止时刻仍有效（`at <= until` 规则不生效），只有 `at > until` 自动恢复；也可在窗口内
`reinstate`。`narrow` 只能严格缩小，v1 scope 仅支持项目级或仓库相对路径前缀，不支持任务、平台、
时间级或 Evidence 非路径 subject。`deprecated/superseded` 永久不可恢复。每次 lifecycle 确认都会递增
revision，旧 attestation/trace 需重做；静态系统 invariant guards 不随普通规则暂停关闭。

Candidate 可先 `sopctl intake .` 或 `sopctl intake . --conversation chat.txt`；重复 guard/Finding/结构化纠正用 `sopctl candidate refresh .` 冷路径聚合，达到 3 个独立 occurrence 才物化。用 `candidate list/show/triage` 审查；批量裁决使用 `sopctl candidate batch-triage . --candidate-id CAND-X --candidate-id CAND-Y --status triaged`，任一 ID 无效则全部不变。**晋升必须显式 `sopctl rule add`，候选本身没有授权力**。

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
# audit / gate 阻断 / harness 拒绝 都会无感生长（拒绝不依赖完整 audit）
sopctl audit . --compact
sopctl growth status .             # 待人定型的候选（发现已自动）
sopctl growth measure .            # 打一帧空间快照（旁路/平行状态/歧义指数）
sopctl growth diff .               # 对照最近两帧：指数下降=空间变窄
# 消歧：把 delete_entry 收成有界删旁路任务（人只圈 --allow，不「推进发现」）
sopctl candidate enact CAND-xxxx . --allow src/legacy_path.py
sopctl inventory .                 # 受控/冗余入口/平行状态；应删旁路优先于再加守卫
sopctl explain MY-001 .

# 开任务（unknown/无画像、弱模型或行为安全上限都会收紧到文件级范围、1 轮预算和 MUST 字段）
# 如需解释当前模型为何被收紧，先只读查看：sopctl capability-events . --model <CURRENT-MODEL>
# 投影含「新会话恢复」+ 当前链头（上限 5；verified 折叠）；全量：task list / show / takeover
sopctl project all .                   # 刷新投影后 project check 应 OK
sopctl chronicle show .                # 换会话：项目何以至此（给模型看的编年）
sopctl chronicle check .               # 编年重放 vs registry 核对
# 对话中途换模型（项目事实不变；旋钮只收紧，不继承上一执行者的放宽）
sopctl task rebind TASK-xxxx . --model <NEW-MODEL>
sopctl task submit TASK-xxxx . --changed src/foo.py --model <NEW-MODEL>  # 须与执行者一致
sopctl task open . --objective "接线 MY-001" \
  --allow src/foo.py --require-rule MY-001 \
  --require-field digest --require-field status   # strict_schema 时需要
# 若接替 blocked/failed_unverified：加 --resolves TASK-旧号（可重复）；旧任务保持终态
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
