# Product red-team checklist（对抗质检，非安全渗透）

**性质：** 发版前 / 每季一次的**产品对抗清单**——证伪本仓库的声称，不是面向外部攻击者的红队产品。  
**非目标：** 新守卫、常驻扫描、对抗方信任根（见 `LIMITATIONS.md`）。  
**信任模型：** 默认合作操作者本机；绕过家族诚实登记在 `RESIDUAL_RISKS.md`。

## 何时跑

- 准备打 tag / 对外说明「可用」之前  
- Living-Project 大切片合并后  
- 真仓 dogfood 发现「控制面自己很吵/很慢」之后（复查节能）

## 怎么跑

1. 按下列五项打勾（机器项跑命令；声称项可人读或另一模型读）。  
2. 复制本清单结构，写成 `docs/verification/REDTEAM_YYYYMMDD.md`（过/不过 + 证据一句）。  
3. **失败则修声称或修实现**；不要用「再加 MUST_NOT」糊弄。

---

## 1. 声称核对（人 / 另一模型）

读：`README.md`、`LIMITATIONS.md`、`PLAYBOOK.md`、最近 `CHANGELOG` Unreleased。

| 问 | 合格标准 |
|----|----------|
| 有没有保证「模型永不犯错」？ | 不得有；LIMITATIONS 须否定 |
| 候选/无感生长会不会自动写 registry？ | 不得；须写明人授权 |
| 中途接入是否可执行？ | doctor「下一刀」+ PLAYBOOK 有路径 |
| harness 深度是否假装一致？ | OpenCode / Codex / Claude 差异须诚实 |

**另一模型提示词（可选）：**

> 只审查声称是否与 LIMITATIONS/PLAYBOOK 一致。列出最多 5 个过度承诺或自相矛盾；不要建议新功能。

---

## 2. 已知绕过仍「登记为抓不住」（抽查）

打开 `RESIDUAL_RISKS.md`，抽 **1～2** 条（建议 R1 重命名、R6 `--no-verify`）。

| 问 | 合格标准 |
|----|----------|
| 文档是否仍承认抓不住？ | 是；不得改口成「已彻底防住」 |
| 若近期修过相关检测 | 须有语料/MUT 或明确缩小该条范围 |

**不要**为抽查临时加生产守卫。

---

## 3. 节能（机器）

```bash
# 本仓
/usr/bin/time -p sopctl doctor .          # 轻量
/usr/bin/time -p sopctl doctor --full .   # 全量
# 投影预算（本仓 AGENTS 中 sopcontrol 小节）
python -c "from pathlib import Path; from sopcontrol.energy import estimate_tokens, PROJECTION_MAX_TOKENS; ..."
```

| 问 | 合格标准 |
|----|----------|
| 轻量明显快于全量？ | 本仓建议 ≥2×；大仓（如 JobsFlow）更应拉开 |
| 投影小节 | ≤ ~1500 tokens 且 ≤ 80 行（`energy.py` 预算） |
| 待人定型候选 | 不宜长期 ≫ 32 且无 triage（会刷节能警告） |

---

## 4. 骨干穿透 + 变异（机器）

```bash
sopctl self-test
pytest tests/corpus/test_mutations.py -q
# 可选更严：
./scripts/vertical-check.sh
bash scripts/verify-product-sim.sh
```

| 问 | 合格标准 |
|----|----------|
| self-test | 旧入口阻断、清洁放行、账本篡改阻断 |
| mutations | 全绿（负向对照可证伪） |
| sim（若跑） | ambiguity 可变窄；rebind/harness mismatch deny |

---

## 5. 真仓抽检（有 dogfood 仓时）

以 JobsFlow / `ai-job-search` 为例：

```bash
sopctl doctor /path/to/jobsflow          # 轻量；看节能警告
sopctl explain JF-PREVIEW-001 /path/...  # 或当前主规则
sopctl growth measure /path/... && sopctl growth status /path/...
```

| 问 | 合格标准 |
|----|----------|
| 主规则 | 若已接线：pass（或诚实 gap + 下一刀） |
| 候选 | 无「上千 observed 碎片」复发；权威不在 candidates |
| ambiguity_index | 有度量帧；消歧后应能解释升降 |

---

## 明确不做

- 为红队新增常驻 agent / LLM 巡检  
- 把 R1/R6 当成「必须本期清零」的安全 KPI  
- 用加守卫代替删旁路或改声称  

## 报告模板

见同目录 `REDTEAM_YYYYMMDD.md`：五项各一行 **PASS/FAIL/SKIP** + 证据；文末「发现」最多 5 条。
