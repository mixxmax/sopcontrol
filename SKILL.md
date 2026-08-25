# SOP Control — 模型交互说明卡（Skill 层）

你是编码 agent。SOP Control 是**控制平面**，不是可选建议。  
权威在 `.sopcontrol/rules/registry.yaml` 与 `sopctl` 判定；本卡只说明如何配合。

## 必做

1. **先读投影**：`AGENTS.md` / `CLAUDE.md` 中 `<!-- sopcontrol:v1 -->` 小节（任务状态、硬规则）。
2. **改规则/账本/任务** 只能通过 `sopctl`，禁止直接编辑 `.sopcontrol/`。
3. **完成前跑门**：`sopctl gate .`（或不在 PATH 时 `python -m sopcontrol.cli gate .`）。
4. **用户说只讨论不改码**：不得写文件；若被拦，转述拦截理由后停止。

## 常用命令

```text
sopctl audit .
sopctl explain <RULE-ID> .
sopctl task open . --objective "..." --allow <path> --require-rule <ID>
sopctl task accept|submit|verify|deliver <TASK-ID> .
sopctl task takeover <TASK-ID> .          # 换会话最小接手包
sopctl intake . --conversation chat.txt  # 讨论/政策句 → Candidate 或 discuss_only
sopctl intent clear .                    # 解除讨论锁定
sopctl repair open <finding_id> --allow <path>
sopctl doctor . --vertical
sopctl vertical-check .
sopctl capability-compare --live opencode --baseline strong .
sopctl identity export . --out id.yaml
sopctl identity import . --file id.yaml
```

`submit` 若契约有 MUST 字段：`--field key=value`（漏字段会被拒）。

## 不要做

- 不要用自报“已完成”代替 `task verify` / `gate`。
- 不要扩大 `allowed_writes` 或改 verifier 自证。
- 不要卸掉 hook/插件（提权；需人工）。
- 已 `delivered` 的任务不要重做副作用。

日用全序见 `PLAYBOOK.md`。
