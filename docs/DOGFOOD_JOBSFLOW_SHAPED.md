# JobsFlow 形狗粮报告（不改外部仓）

**日期：** 2026-08-26  
**约束：** ROADMAP 边界禁止改写 `/Users/xiezhijie/ai-job-search`；本轮在本仓
`corpus/fixtures/jobflow-preview` 上跑完整役用剧本，作为 JobsFlow 形验收。

## 剧本

```bash
FIX=corpus/fixtures/jobflow-preview
# 使用临时拷贝以免污染夹具基线
```

已执行项（见下方命令记录）：

1. 拷贝夹具到临时目录  
2. `identity init` + `lock`  
3. `project all`  
4. `audit --compact` / `explain PUSH-001`  
5. 任务：只改文档 → verify = repair（场景2）  
6. `gate`（夹具含 fail 规则时阻断属预期）

## 结论

- 求职域夹具上，吸收审计与任务完成门行为与 PLAYBOOK 一致。  
- **真实 JobsFlow 狗粮**需用户授权放开外部仓写入边界后再做。  

## 本轮命令记录
工作目录: `/var/folders/zs/_sbp5qfd45l9njbr3l41m4s40000gn/T/jf-dogfood-_zwomp58`

### `identity init` → exit 0
```
项目身份 → proj-8172f98487642fc8
  root: /private/var/folders/zs/_sbp5qfd45l9njbr3l41m4s40000gn/T/jf-dogfood-_zwomp58  locked=False
```

### `identity lock` → exit 0
```
已锁定 project_id → proj-8172f98487642fc8（挪目录不重算）
```

### `project all` → exit 0
```
已写入规则投影 → /private/var/folders/zs/_sbp5qfd45l9njbr3l41m4s40000gn/T/jf-dogfood-_zwomp58/AGENTS.md（只替换带标记小节；权威源仍是 registry.yaml）
已写入规则投影 → /private/var/folders/zs/_sbp5qfd45l9njbr3l41m4s40000gn/T/jf-dogfood-_zwomp58/CLAUDE.md（只替换带标记小节；权威源仍是 registry.yaml）
已同步 AGENTS.md 与 CLAUDE.md；各 harness 控制策略不变
```

### `audit --compact` → exit 0
```
H-002         fail     wired_and_tested   生产路径仍存在旧入口 [direct_write]，受控入口可被绕过（消费者与回归证据齐备 [workflow_gate
PUSH-003         unknown  -                  状态类规则：吸收等级不适用，由 state_health 模式评估（write_only/parallel/absent
PUSH-004         unknown  -                  规则未声明 consumer_markers，无法判定吸收；'什么算消费者'由语料逐模式经验回答，不由宏大定义回答

证据 33 条，finding 4 条，判定 gap/fail 2 项。
账本: /private/var/folders/zs/_sbp5qfd45l9njbr3l41m4s40000gn/T/jf-dogfood-_zwomp58/.sopcontrol/evidence/ledger.jsonl（compact 快照已替换账本；--strict 可作为 CI 门）
```

### `task open` → exit 0
```
已创建任务 TASK-0001 [contract_proposed]：接线 PUSH-001
  写入范围: docs, src
  完成定义: 规则 PUSH-001 全部判定 pass
  修复预算: 2
  下一步: sopctl task accept TASK-0001
```

### `task verify` → exit 0
```
迁移: TASK-0001 repair_required (r4)
  理由: 第 1 轮修复：规则 PUSH-001 未达标（gap/unknown）
  下一步: 最小范围修复后 task submit 重新提交（不重做整个任务）
```

### `gate` → exit 1
```
GAP(警告，不阻断) PUSH-001: 已接受的 MUST 规则在生产路径没有消费者 [require_preview]
FAIL(阻断) PUSH-002: 生产路径仍存在旧入口 [direct_write]，受控入口可被绕过（消费者与回归证据齐备 [workflow_gateway]；enforced 还需要运行时 trace 证据（手册 6.5 七条件
gate: 已阻断——fail 1 项，账本完整
```

