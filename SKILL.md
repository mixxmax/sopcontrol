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
sopctl rule suspend <RULE-ID> . --until <ISO-8601> --reason "..." --by <HUMAN>
sopctl rule reinstate <RULE-ID> . --reason "..." --by <HUMAN>
sopctl rule narrow <RULE-ID> . --scope <REPO-PREFIX> --reason "..." --by <HUMAN>
sopctl rule deprecate <RULE-ID> . --reason "..." --by <HUMAN>
sopctl rule supersede <OLD-ID> . --replacement <NEW-ID> --reason "..." --by <HUMAN>
sopctl task open . --model <CURRENT-MODEL> --objective "..." \
  --allow <exact-file> --require-rule <ID> --require-field <name>
sopctl task accept|submit|verify|deliver <TASK-ID> .
sopctl task takeover <TASK-ID> .          # 换会话最小接手包
sopctl intake . --conversation chat.txt  # 讨论/政策句 → Candidate 或 discuss_only
sopctl candidate refresh .              # 冷路径聚合重复事实；3 次才物化，不自动授权
sopctl candidate list .                  # 查看候选
sopctl candidate batch-triage . --candidate-id <ID> --status triaged  # 原子批量裁决，不晋升
sopctl intent clear .                    # 解除讨论锁定
sopctl repair open <finding_id> --allow <path>
sopctl repair apply <TASK-ID> --harness opencode
sopctl doctor . --vertical
sopctl vertical-check .
sopctl capability-compare --live opencode --baseline strong .
sopctl capability-events . --model <CURRENT-MODEL>  # 只读查看遥测完整性、建议与安全上限
sopctl identity export . --out id.yaml
sopctl identity import . --file id.yaml
```

所有 `rule suspend/reinstate/narrow/deprecate/supersede` 都先预览，再由人工原样重跑并带 `--confirm-preview <ID>`；agent 不得自签。暂停到点 inclusive，只有 `at > until` 自动恢复；`deprecated/superseded` 永久不可恢复。scope v1 只接受项目级或仓库相对路径前缀。生命周期 revision 变化后旧 attestation/trace 不再有效；静态 invariant guards 不随普通规则暂停关闭。

`--model` 必须填写当前执行模型，并与已存画像中的身份完全一致；省略或不匹配时按 `unknown` 保守执行。fixture/响应文件只用于离线校准，不能授权；只有人工批准的 live 评测可放宽，agent 不得自行运行 `capability-approve`。`submit` 若契约有 MUST 字段：`--field key=value`（漏字段会被拒）。

## 不要做

- 不要用自报“已完成”代替 `task verify` / `gate`。
- 不要扩大 `allowed_writes` 或改 verifier 自证。
- 不要卸掉 hook/插件（提权；需人工）。
- 已 `delivered` 的任务不要重做副作用。

日用全序见 `PLAYBOOK.md`。
