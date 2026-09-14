# SOP Control 非 JobsFlow 立即修复执行技术手册

> 版本：1.0  
> 日期：2026-09-13  
> 执行对象：第一次接触 SOP Control 的外部执行模型  
> 任务范围：只修复 SOP Control 本身；不接入、不修改、不调用 JobsFlow 真实业务系统。  
> 目标：完成所有可以脱离 JobsFlow 闭环的代码、架构、性能、安装、升级和发布候选工作。

---

## 0. 给执行模型的第一条指令

你不是来“评价报告”的，而是来把报告中仍能在 SOP Control 仓库内完成的事项逐项变成可复现证据。

不要因为报告写了 PASS 就停止检查。报告是线索，不是权威证据。必须以当前工作区中的代码、测试、真实本地执行和干净安装结果为准。

本手册完成后，最终状态应为：

```text
SOP Control Release Candidate
本地代码/规则/动态 SOP/自然逻辑/升级/性能/安装均已闭环
唯一未关闭的事项：真实宿主产品（JobsFlow 及第二个真实宿主）演练
```

在 JobsFlow 尚未接入前，不得把最终状态写成“GA 已发布”。可以写成“本地发布候选，等待真实宿主验证”。

---

## 1. 工作边界和不可违反事项

### 1.1 允许修改的范围

允许修改：

- `sopcontrol/` 中的 SOP Control 生产代码；
- `tests/` 中的行为测试、集成测试和基准测试；
- `pyproject.toml`、打包配置、CI、README、CHANGELOG 和发布文档；
- 新增一个与 JobsFlow 无关的本地参考宿主，用来验证 CLI/API/worker adapter。

### 1.2 明确禁止的范围

禁止：

- 修改 JobsFlow 或 JobsDB；
- 为了让测试通过而关闭 gate、跳过检查、扩大豁免或降低阈值；
- 把测试 fixture 的模拟结果写成真实宿主接入证据；
- 直接编辑 `.sopcontrol/` 内的 registry、ledger、evidence 或其他控制状态；
- 用 `git reset --hard`、`git checkout --` 覆盖用户已有修改；
- 删除用户已有文件、hook、插件或测试；
- 在没有真实 runtime 的情况下把空目录当成升级成功；
- 把大模型的自报“已遵守”当成执行证据；
- 未经明确授权 push 到远端。

`.sopcontrol/` 是受保护控制目录。凡是需要变更规则、账本、任务或证据，必须通过已有 `sopctl` 子命令；找不到命令时先查 CLI 实现，不得直接绕过。

### 1.3 修改行为规范

每完成一个工作包，都必须：

1. 修改或新增最小实现；
2. 新增至少一个正向测试和一个负向测试；
3. 执行定向测试；
4. 记录实际命令和结果；
5. 再进入下一个工作包。

不允许先大规模重写，再用一轮全量测试猜哪里坏了。

---

## 2. 先理解产品目标

### 2.1 三类规则是永久且平级的

SOP Control 维护一个永久规则空间，包含：

1. **产品本体规则**：产品设计和实现过程中形成的事实、状态、入口、约束和不可违反条件。
2. **动态 SOP**：用户在使用过程中不经意表达但希望长期保留的细腻工作规则，例如审查范围、允许偏差、修改上限、停止条件和“不要过度谨慎”。
3. **自然逻辑**：在目标已经明确时，可以证明更自然、更省步骤、更少外部调用、更少 token 和更少范围扩大的默认执行方式。

三类规则在永久保存、来源、修订、解释、升级保留和生命周期上平级。它们的适用范围可以不同，但分类本身不能被当成隐式优先级。

### 2.2 动态 SOP 不得自动过期

必须严格区分：

```text
永久规则：不能因时间、重启、换模型、换会话或软件升级自动消失
运行实例：任务 plan、profile、ticket、grant、cache、probe 可以过期
```

如果代码里存在 `expires_at`，必须证明它只作用于运行实例、票据、证据或明确的临时指令。不能让永久 `dynamic_sop` Rule 通过 `expires_at` 失效。

### 2.3 SOP Control 的职责边界

产品端负责业务语义，例如：

- 如何抓取 JD；
- 如何评分；
- semantic lint 检查什么；
- 什么内容算事实错误；
- 什么产物可以 render 或 push。

SOP Control 负责确保产品端声明的入口和检查真的被调用，并且检查失败时影响后续动作。SOP Control 不应复制业务内容或自己重新实现业务语义。

---

## 3. 开始执行前：建立基线

### 3.1 检查当前工作区

在仓库根目录逐条执行：

```bash
pwd
git status --short
git rev-parse HEAD
python3 --version
```

如果 `sopctl` 在 PATH 中，记录：

```bash
sopctl --version
```

如果不在 PATH，使用：

```bash
python3 -m sopcontrol.cli --help
```

不得因为 `sopctl` 不在 PATH 就重新安装、覆盖环境或修改用户 shell。先使用仓库现有 Python 环境。

### 3.2 定向阅读

必须先阅读：

- `AGENTS.md`；
- `README.md` 和中文 README；
- `pyproject.toml`；
- `sopcontrol/model.py`；
- `sopcontrol/dynamic_sop.py`；
- `sopcontrol/control_profile.py`；
- `sopcontrol/control_result.py`；
- `sopcontrol/upgrade.py`；
- `sopcontrol/resolve_cli.py`；
- `sopcontrol/attachment.py`；
- `tests/dynamic/`；
- `tests/logic/`；
- 与 bridge、coverage、runtime 相关的测试。

使用 `rg` 定位调用链：

```bash
rg -n "select_rules|observe_utterance|confirm_candidate|SemanticProjection|plan_upgrade|sync\(|rollback\(|runtime_path|expires_at|RuleStatus|admit\(" sopcontrol tests
```

不要把完整账本、完整日志或大型生成文件读入上下文。只保留支持判断的摘要、计数和关键片段。

### 3.3 跑基线测试

先执行当前项目规定的全量测试。若项目已配置 pytest：

```bash
python3 -m pytest -q
```

再执行当前项目规定的 coverage 命令；如果没有单独脚本，至少执行：

```bash
python3 -m pytest --cov --cov-branch --cov-report=term-missing
```

最后执行：

```bash
python3 -m sopcontrol.cli gate
python3 -m sopcontrol.cli project check
python3 -m sopcontrol.cli chronicle check
```

把基线结果记下：

- passed/failed/skipped 数量；
- 总 coverage 和 branch coverage；
- dynamic_sop、upgrade、registry 等关键模块 coverage；
- gate 是否通过；
- 当前已有失败是否来自用户未提交改动。

基线只用于比较，不能为了降低失败数量修改测试或清除用户变更。

---

## 4. 总工作包和优先级

按以下顺序执行。P0/P1 必须优先，P2 可并行，但最终都要有证据。

| 工作包 | 内容 | 是否依赖 JobsFlow | 优先级 |
|---|---|---:|---:|
| A | 动态规则选择 fail-closed | 否 | P1 |
| B | Rule 生命周期与永久性边界 | 否 | P1 |
| C | 动态 SOP 捕获去噪与来源完整性 | 否 | P1 |
| D | semantic projection 深度 diff | 否 | P1 |
| E | 真实 side-by-side runtime、launcher、sync、rollback | 否 | P1 |
| F | once-only 会话隔离和清理 | 否 | P2 |
| G | 性能、token、ticket 基线 | 否 | P2 |
| H | 关键模块 branch coverage | 否 | P1 |
| I | 干净打包、安装、版本和发布元数据 | 否 | P1 |
| J | 平台支持矩阵和 CI | 否 | 按支持承诺决定 |
| K | 独立本地 API/worker 参考宿主 | 否，但不能替代 JobsFlow | P2 |

---

## 5. WP-A：动态规则选择必须 fail-closed

### 5.1 要解决的问题

如果动态 SOP 要求：

```text
action = materials.audit
```

而本次运行没有提供 `action`，系统不能因为“没有发现冲突”就选择这条规则。缺少必要上下文时，系统无法证明规则适用，必须停止自动激活。

### 5.2 固定语义

对每个 selector 字段：

1. 规则没有限制该字段：不参与匹配；
2. 规则限制了该字段，本次上下文缺失：`unproven`，不选择；
3. 规则限制了该字段，上下文存在但值不匹配：`not_applicable`；
4. 上下文存在且匹配：允许选择。

不要把第 2 种情况伪装成 `not_applicable`。如果现有返回值没有 `unproven`，扩展结构化结果；如果为了兼容旧调用保留旧元组，至少在解释结果中带上 `status=unproven`。

### 5.3 实现步骤

1. 阅读 `ActivationSelector` 的所有字段和 `select_rules` 的所有调用者。
2. 确认空 selector 维度代表“不限制”，不能代表“上下文可缺省”。
3. 对有约束且缺上下文的字段，生成明确原因，例如：

   ```text
   规则 DR-001 未激活：无法证明 action，规则要求 action=materials.audit。
   ```

4. 不改变已明确不匹配的解释格式。
5. 不让 `proposed`、`observed` 或 `rejected` 规则进入选择。

### 5.4 必须新增的测试

至少包括：

```text
有 action selector + action 缺失 → 不选中，status=unproven
有 phase selector + phase 缺失 → 不选中，status=unproven
有 product selector + product 缺失 → 不选中，status=unproven
selector 为空 + context 为空 → 可以选择
context 存在但不匹配 → not_applicable
所有 selector 都匹配 → selected
```

同时测试 CLI JSON 输出，不能只测内部函数。

### 5.5 完成条件

- 缺少必要上下文永远不会激活动态 SOP；
- 原有匹配和不匹配行为不回归；
- `unproven` 原因可被产品 adapter 消费；
- 定向测试全部通过。

---

## 6. WP-B：明确 Rule 生命周期，不把“确认”冒充成“已执行”

### 6.1 固定生命周期

复用现有等价状态，不要重复造多个名字。语义必须能区分：

```text
observed     观察到，不能执行
proposed     候选，不能硬拦截
clarified    已澄清，仍不能替代接受
accepted     用户确认，进入永久权威空间
compiled     已被编译器解析
activated    当前上下文允许使用
monitored    已有持续监测
superseded   被明确的新规则取代
deprecated   被明确废止
```

如果项目已有 `wired`、`verified`、`enforced` 等状态，复用；如果没有，至少在结果/证据中表达这些事实。不能仅因为 `confirm_candidate()` 执行完，就宣称规则已经接线和强制执行。

### 6.2 必须满足的状态不变量

- 用户确认只能保证 `accepted`；
- `compiled` 必须有编译成功证据；
- 没有生产消费者的规则不能显示 verified/enforced；
- 没有真实探针的消费者不能显示 verified；
- 当前上下文不匹配不是过期；
- 规则永久存在不代表本次一定激活；
- 规则不能从 active 因时间自动变成 retired。

### 6.3 检查永久性边界

逐项检查：

- `Rule` 是否有 `expires_at` 或等价 TTL；
- dynamic SOP 是否可能写入 `ControlProfile.expires_at` 后被当成规则期限；
- registry reload 后规则是否还在；
- 规则升级后是否还在；
- `suspended_until` 是否只表示暂停窗口，而不是永久退休；
- 规则被取代时是否留下旧规则和 supersedes 链。

正确的结构是：

```text
dynamic_sop Rule：永久
task/run profile：本次规则投影，可有 expires_at
ticket/grant：短期授权，可有 expires_at
```

### 6.4 必须新增的测试

- 确认 dynamic SOP 后重启加载仍存在；
- 把当前时间推进到 profile 过期后，Rule 仍 active；
- 软件版本切换后 Rule ID、statement、source、selector、flexibility 不变；
- 用户未确认时 registry 数量不变；
- 只有显式 retire/supersede 才能结束规则；
- 试图直接把规则状态改成 verified/enforced，但没有消费者和 probe 时失败。

---

## 7. WP-C：动态 SOP 捕获要“少漏但不污染”

### 7.1 现状风险

动态 SOP 的重点是捕获用户不经意说出的长期要求，但如果所有传入的 observation 都直接创建 dynamic candidate，候选箱会被普通讨论、一次性结果纠正和探索性问题污染。

候选不是权威规则，但候选污染会造成：

- 用户频繁确认；
- 普通讨论被误认为产品规则；
- 规则范围逐渐扩大；
- 模型为了减少漏报而把所有文本都上升为长期候选。

### 7.2 三级捕获策略

必须保留所有必要的原话 observation，但不必让每条 observation 都成为高优先级候选：

```text
所有用户原话             → observation，保留来源
疑似执行方式纠正          → candidate，低打扰待确认
明确长期要求/重复纠正      → candidate，高优先级待确认
用户确认                  → accepted dynamic_sop
```

识别信号可以包括：

- 对当前执行顺序或范围的纠正；
- “不要再这样做”“我真正想要的是”；
- 对容忍度、上限、下限和停止条件的说明；
- 同类纠正跨任务重复出现；
- 明确的以后、始终、长期表达。

“仅本次”必须阻断进入永久空间。

### 7.3 LLM 的使用边界

- observation 捕获不依赖 LLM；
- candidate 结构化可以接受模型建议；
- 模型建议不得直接写 registry；
- 用户确认前不得硬拦截；
- 运行时不得每次重新调用模型解释已确认规则；
- 模型不能伪造“用户已经确认”。

### 7.4 来源完整性

永久动态 SOP 至少要能追溯到：

- 原话全文或不可变引用；
- observation ID；
- 会话/文档来源；
- 捕获时上下文；
- 是否经过编辑；
- 谁确认、何时确认；
- 当前规则 revision。

编辑后的规则陈述不能覆盖原话。原话和结构化规则必须分别保存。

### 7.5 必须新增的测试

- 无“永久”关键词的工作方式纠正形成候选；
- 普通讨论只形成 observation，不形成高优先级候选；
- “这次先跳过”不会进入永久 registry；
- 用户选择 `not_a_rule` 后不会无限重复询问；
- 同义重复纠正被聚合；
- 两条不同规则不会因相似词语被错误合并；
- 模型给出建议但用户未确认，registry 零增长；
- 编辑后的规则仍保留原话来源；
- 换会话、换模型后可以从 registry 恢复规则。

### 7.6 完成条件

动态 SOP 同时满足：

```text
不依赖关键词才能被捕获
不把普通对话全部污染成候选
不经用户确认不生效
确认后永久存在
运行时只按上下文选择，不因时间消失
```

---

## 8. WP-D：升级 semantic projection 必须比较真实语义

### 8.1 当前计数式 diff 的问题

只比较以下内容是不够的：

- 规则总数；
- active 数量；
- dynamic SOP 数量；
- block 规则数量。

同样数量的规则，正文、范围、容忍度、选择器或消费者可以完全改变。因此必须比较每个规则的稳定语义投影。

### 8.2 RuleProjection 必须包含的字段

对每一条规则生成规范化对象，至少包含：

```text
rule_id
revision
rule_class
statement
modality
status（排除非语义时间字段后）
scope
scope_paths
activation
flexibility
exceptions
supersedes/superseded_by
consumer_markers
guard_ids
compiler target/version
```

排除 created_at、updated_at 等不会改变行为的时间字段；不能排除会改变适用范围、强度或消费者的字段。

所有规则按 `rule_id` 排序，再生成 digest。摘要必须可复算。

### 8.3 必须识别的升级变化

至少识别：

- dynamic SOP 丢失；
- active 规则减少；
- MUST/MUST_NOT/SHOULD 强度改变；
- statement 改变；
- scope 扩大或缩小；
- activation 改变；
- flexibility 上下界改变；
- 修正策略或停止条件改变；
- consumer/guard 改变；
- schema/protocol 改变；
- adapter digest 改变。

任何可能放宽控制、丢失动态 SOP 或使规则不再接线的变化，必须阻断自动切换。

### 8.4 必须新增的测试

使用相同规则数量和相同规则 ID，分别只改变一项：

- statement；
- activation action；
- flexibility 上限；
- modality；
- scope；
- consumer marker；
- guard ID。

每一项都必须产生 semantic change。另测：纯时间字段变化不应产生语义变化。

---

## 9. WP-E：把 sync 从“记录路径”变成真实 side-by-side runtime

### 9.1 必须修复的实际断点

不能接受以下假升级：

```text
创建 .sopcontrol-local/runtimes/0.4.0 空目录
→ 修改 binding.runtime_path
→ 输出 switched=true
```

升级成功必须意味着：新版本可以被真实启动，新版本的代码和依赖已经安装，新 launcher 确实会执行它。

### 9.2 目标结构

```text
.sopcontrol-local/
  binding.yaml
  runtimes/
    0.3.0/
      bin/sopctl
      lib/python.../sopcontrol/
      runtime-manifest.json
    0.4.0/
      bin/sopctl
      lib/python.../sopcontrol/
      runtime-manifest.json
  bin/
    sopctl-runner
```

规则数据仍然在项目权威空间，不能复制到每个 runtime 目录。

### 9.3 绑定清单

绑定记录至少包含：

- core version；
- runtime path；
- previous runtime path；
- rule schema version；
- adapter protocol version；
- adapter digests；
- runtime package digest；
- last verify；
- migration version；
- 当前和上一回滚点。

不能保存 secret。

### 9.4 `plan` 阶段必须无副作用

检查 `plan_upgrade()`：

- 不能创建 runtime 目录；
- 不能写 binding；
- 不能迁移规则；
- 不能修改 hook；
- 不能下载或安装包。

用测试在执行前后比较项目目录摘要，确认 plan 是真正只读。所有写入移动到 `sync/apply`。

### 9.5 staging 阶段

`sync` 必须：

1. 解析目标版本和来源；
2. 获取或构建真实 wheel/sdist；
3. 校验包摘要；
4. 安装到临时 staging runtime；
5. 生成 runtime manifest；
6. 运行新 runtime 的 `--version` 和自检；
7. 运行新 runtime 的规则编译、adapter 加载和负向 gate；
8. 验证通过后再将 staging 目录提升为版本目录。

任何一步失败，都不得改变当前 binding。

### 9.6 launcher 必须真正使用 binding

检查所有 hook、bridge 和 scaffold 的执行路径，确认它们不是只按 PATH 找当前 Python。

稳定 launcher 必须：

1. 找到项目根目录；
2. 读取 binding；
3. 验证 runtime path 在项目允许目录内；
4. 验证 manifest 版本和 digest；
5. 调用绑定 runtime 的 `sopctl`；
6. binding 损坏时 fail-closed，并给出修复建议。

不得把绝对开发机路径硬编码进 hook。可以记录路径，但执行时必须具备可移植 resolver。

### 9.7 原子切换和回滚

切换步骤：

```text
新 runtime 完整存在
→ 新 runtime 影子验证通过
→ 临时 binding 写入并 fsync
→ 原子替换 binding
→ launcher 读取新 binding
→ 运行后验 probe
```

后验 probe 失败时自动恢复旧 binding。

rollback 必须：

- 使用旧 runtime 真实执行，而不是当前 Python 重新模拟；
- 规则数据不回滚、不删除；
- 回滚前再次检查旧 runtime 是否能保留所有 active dynamic SOP；
- 回滚失败时保持当前可用版本；
- 回滚动作可重复且不会损坏 binding。

### 9.8 必须新增的测试

- `plan` 前后目录完全不变；
- 新 runtime 目录不是空目录；
- 新 runtime 的版本输出与 binding 一致；
- launcher 实际执行新 runtime；
- 新版本规则正文改变时 semantic diff 阻断或要求确认；
- staging 中断时旧 runtime 继续工作；
- 原子切换中断时 binding 可恢复；
- 新 runtime probe 失败时不切换；
- rollback 真实执行旧 runtime；
- rollback 不丢 dynamic SOP；
- binding 被破坏时 fail-closed；
- 两个版本可以并排存在而不互相覆盖。

这些测试可以使用本地构建的两个 wheel 或两个隔离虚拟环境完成，不需要 JobsFlow。

---

## 10. WP-F：once-only 必须是真正的会话级记录

### 10.1 目标语义

“仅本次”不是永久规则，也不是下一次会话的默认规则。它只能影响当前 session。

### 10.2 实现要求

- 每条 once-only 记录绑定 session ID；
- session ID 不从用户可控的普通文本中推断；
- 新 session 默认不能读取旧 session 的 once-only；
- 进程退出或 session 结束后清理，或至少变成不可执行历史记录；
- 残留文件不得影响 rule selection、admission、ticket 或 gate；
- 过期清理失败不能导致永久规则被删除。

### 10.3 测试

- 同 session 可以读取；
- 新 session 不能读取为 active instruction；
- 重启后不能影响规则选择；
- 文件残留时仍不能影响权限；
- 清理失败不会删除 registry；
- once-only 永远不进入 permanent registry。

---

## 11. WP-G：性能、能耗和 token 基线

### 11.1 不能用“纯函数很快”代替测量

纯函数测试耗时不能代表 CLI、文件读取、进程启动、adapter 和产品入口的端到端耗时。

### 11.2 建立四组基准

分别测量：

1. 内存内规则选择和 admission；
2. 带本地 registry、profile 和 plan digest 的普通动作；
3. 多步骤 phase grant；
4. 高影响 capability ticket。

同时测量：

- cold start；
- warm start；
- attach/status；
- 未变化项目的增量扫描；
- 新增 surface 后的扫描。

### 11.3 测量方法

使用 `time.perf_counter()`，先 warm-up，再至少 100 次有效样本。报告：

- p50；
- p95；
- min/max；
- LLM 调用次数；
- ticket/grant 调用次数；
- 文件读写次数；
- receipt 字节数；
- 扫描对象数量。

不要把 warm-up 和有效样本混在一起。

### 11.4 目标

在基准机上以以下目标验收，若平台差异较大必须报告 baseline 比例：

- 稳态低风险 admission：零 LLM 调用；
- 纯判定 p95：目标不超过 100 ms；
- 含本地状态的普通判定 p95：目标不超过 300 ms；
- 普通宿主流程额外中位时延：目标不超过 5%；
- 只读、低风险动作：零 ticket；
- 同一 phase 的连续计划动作：最多一次 grant；
- 无变化项目：不得每次重复全仓昂贵扫描。

如果目标不能达到，必须给出数据和用户可理解的降级策略，不得直接删除性能门。

---

## 12. WP-H：关键模块 coverage 与负向测试

### 12.1 覆盖率目标

最终发布候选至少满足：

- 总 branch coverage ≥ 85%；
- dynamic_sop、upgrade、registry、生命周期和准入关键模块 branch coverage ≥ 95%；
- 没有被忽略但属于关键安全路径的模块；
- skipped 测试都有明确原因，关键路径不得 skip。

coverage 不是为了追数字。每个新增分支都必须有行为断言，不要用无意义的调用覆盖代码。

### 12.2 优先补的边界

- selector context 缺失；
- 规则冲突；
- schema 非法；
- 规则生命周期非法迁移；
- dynamic candidate 重复、拒绝和仅本次；
- semantic projection 同数量变更；
- staged runtime 缺失；
- runtime manifest 摘要错误；
- launcher 解析失败；
- binding 损坏；
- migration 中断；
- rollback 目标不可用；
- 影子验证失败；
- secret 脱敏异常。

### 12.3 测试规则

每个关键负向路径都要断言：

- 返回的状态；
- 结构化 reason code；
- 没有发生不应发生的写入；
- binding/registry/runtime 是否保持旧状态；
- 用户下一步动作是否明确。

只断言“抛出了异常”不够。

---

## 13. WP-I：干净打包、安装和发布元数据

### 13.1 修正版本表达

检查 `pyproject.toml`、README、中文 README、CHANGELOG 和 release notes 是否一致。

当前如果代码元数据仍写着：

```text
Development Status :: Alpha
experimental
```

而报告或 README 写成 Beta/可发布，必须统一。外部 JobsFlow 尚未验证时，建议发布候选写为 Beta；不要在 GA 证据尚未完成时提前写 Production/Stable。

### 13.2 构建 wheel

在仓库外的临时目录构建，避免污染仓库：

```bash
python3 -m build --wheel --outdir /tmp/sopcontrol-wheel-test
```

如果 `build` 不可用，使用项目允许的等价构建方式，但必须记录实际命令。检查 wheel 内容，确认包含：

- `dynamic_sop.py`；
- `upgrade.py`；
- 所有新增 logic 模块；
- CLI entry point；
- plugins（如果发布范围包含 plugins）。

### 13.3 干净环境安装

创建一次性虚拟环境，不能依赖当前源码目录：

```bash
python3 -m venv /tmp/sopcontrol-clean-venv
/tmp/sopcontrol-clean-venv/bin/python -m pip install /tmp/sopcontrol-wheel-test/*.whl
/tmp/sopcontrol-clean-venv/bin/sopctl --help
```

再在一个临时项目执行：

```bash
/tmp/sopcontrol-clean-venv/bin/sopctl init /tmp/sopcontrol-clean-project
```

验证：

- 当前目录不是 SOP Control 源码目录也能运行；
- CLI 能找到模块；
- dynamic observe/confirm 能运行；
- sync/rollback 能运行；
- attach/status 能运行；
- 无需激活 shell；
- 不依赖开发机绝对路径。

不要删除用户目录中的任何内容；临时目录使用明确的 `/tmp/sopcontrol-*` 路径并在报告中记录。

### 13.4 clean checkout

在形成候选 commit 后，使用新的临时 checkout 测试：

```bash
git clone <本地远端或已验证来源> /tmp/sopcontrol-clean-checkout
```

如果不能 clone 本地远端，就使用明确的 commit archive 或工作区副本，不要假装是 clean checkout。

在 clean checkout 中重新执行：

- 安装；
- 定向动态 SOP 测试；
- logic 测试；
- upgrade 测试；
- 全量测试；
- coverage；
- gate；
- package smoke。

当前工作区通过而 clean checkout 失败，发布候选不成立。

---

## 14. WP-J：平台支持矩阵

先决定产品实际承诺，不要用模糊的“跨平台”三个字。

### 如果当前只支持 macOS arm64

立即在 README、pyproject classifiers 和支持文档中明确：

```text
正式支持：macOS arm64
其他平台：未承诺或实验性
```

这时 Windows/Linux 不能被写成已验证能力。

### 如果要宣称跨平台

必须补：

- Linux CI；
- Windows CI；
- shell hook 行为；
- Git Bash/WSL 说明；
- symlink 和权限；
- 路径分隔符；
- clean package install；
- launcher 和 rollback。

Windows/Linux 的 fixture 测试可以现在完成，但没有真实 runner 结果时只能标 `unproven`。

---

## 15. WP-K：构造独立本地参考宿主

这不是 JobsFlow，也不能冒充第二个真实商业宿主。它的作用是提前证明 adapter seam 不是只为一个产品写的。

至少构造两个结构不同的本地宿主：

### Host-CLI

- CLI 入口；
- 文件读取；
- 一个低风险只读动作；
- 一个受控写动作；
- 一个外部 hook；
- 一个高影响动作。

### Host-API/Worker

- Python API 或本地 worker；
- 输入集合和输出集合；
- 一个昂贵操作；
- 一个集合缩小操作；
- 一个产品业务检查 stub；
- 一个失败和重试路径。

用这两个宿主验证：

- Surface Inventory；
- Operator Contract；
- attach；
- adapter protocol；
- admission；
- 自然逻辑；
- sync；
- rollback；
- 覆盖率和 probe。

报告必须明确标注这是参考宿主，不得把它写成 JobsFlow 真实证据。

---

## 16. 最终执行顺序

执行模型必须按下面顺序收口：

### 第一阶段：代码正确性

1. WP-A selector 缺失上下文 fail-closed；
2. WP-B lifecycle 和永久性分离；
3. WP-C 动态捕获去噪、来源和确认；
4. WP-D semantic projection 深度 diff；
5. WP-E 真实 runtime、launcher、sync、rollback。

### 第二阶段：质量与效率

6. WP-F once-only；
7. WP-G 性能基线；
8. WP-H 关键 branch coverage；
9. WP-J 平台声明或 CI；
10. WP-K 本地参考宿主。

### 第三阶段：发布候选

11. WP-I 构建 wheel；
12. 干净虚拟环境安装；
13. clean checkout 验证；
14. 全量测试、gate、project check、chronicle check；
15. 检查工作区是否仍有未提交的必要修改；
16. 生成最终报告。

---

## 17. 最终验收矩阵

执行模型必须逐行填写下表，不允许只写“已完成”。

| 编号 | 验收要求 | 代码证据 | 测试证据 | 实际运行证据 | 状态 |
|---|---|---|---|---|---|
| A-01 | selector 缺上下文不激活 |  |  |  |  |
| A-02 | 不匹配和缺失分别解释 |  |  |  |  |
| B-01 | dynamic SOP 永久保存 |  |  |  |  |
| B-02 | profile 过期不影响 Rule |  |  |  |  |
| B-03 | accepted/compiled/verified 不混淆 |  |  |  |  |
| C-01 | 无关键词纠正可生成候选 |  |  |  |  |
| C-02 | 普通讨论不污染高优先级候选 |  |  |  |  |
| C-03 | 模型建议不能直接入 registry |  |  |  |  |
| C-04 | 原话、上下文、确认人可追溯 |  |  |  |  |
| D-01 | 同数量规则正文变化可检测 |  |  |  |  |
| D-02 | selector/flexibility/scope 变化可检测 |  |  |  |  |
| E-01 | plan 无副作用 |  |  |  |  |
| E-02 | staged runtime 真实可执行 |  |  |  |  |
| E-03 | launcher 使用 binding 指向版本 |  |  |  |  |
| E-04 | 新 runtime 失败不切换 |  |  |  |  |
| E-05 | rollback 真实可执行且不丢规则 |  |  |  |  |
| F-01 | once-only 绑定 session |  |  |  |  |
| G-01 | admission p50/p95 已测 |  |  |  |  |
| G-02 | 普通动作零 LLM/零 ticket |  |  |  |  |
| H-01 | 关键模块 branch coverage ≥95% |  |  |  |  |
| I-01 | wheel 内容完整 |  |  |  |  |
| I-02 | clean venv 可安装运行 |  |  |  |  |
| I-03 | clean checkout 可复现 |  |  |  |  |
| J-01 | 平台承诺与证据一致 |  |  |  |  |
| K-01 | CLI 参考宿主接入 |  |  |  |  |
| K-02 | API/worker 参考宿主接入 |  |  |  |  |

状态只能使用：

- `PASS`：实现、测试和实际证据齐全；
- `PARTIAL`：有实现但证据或范围不完整；
- `GAP`：尚未实现；
- `UNPROVEN`：没有足够实际证据；
- `BLOCKED`：明确阻断发布。

---

## 18. 通过标准

除 JobsFlow 真实接入和第二个真实商业宿主外，以下项目不得保留为未解决 GAP：

- selector 缺上下文的错误激活；
- dynamic SOP 自动过期；
- 动态规则来源丢失；
- 模型建议直接成为权威规则；
- semantic diff 只比较数量；
- 空 runtime 目录被当成升级成功；
- launcher 不使用 binding；
- rollback 只修改记录、不运行旧版本；
- once-only 能跨 session 影响执行；
- 没有性能数字却声称低开销；
- 关键模块 coverage 不足且没有解释；
- wheel 依赖源码目录才能运行；
- package 元数据与 README 发布级别矛盾；
- 工作区通过但 clean checkout 无法复现。

如果这些项全部关闭，SOP Control 可以称为：

```text
本地工程与发布闭环完成，等待真实宿主验证的 Release Candidate
```

不能称为：

```text
已经在所有产品中 GA 发布
```

---

## 19. 最终报告模板

完成后严格按以下格式输出：

### A. 结论

- 当前版本：
- 当前 commit：
- 发布判定：Release Candidate / Beta / Not Ready
- JobsFlow 是否执行：必须写“未执行”
- 除 JobsFlow 外是否还有阻断：

### B. 修复清单

逐项列出 WP-A 至 WP-K：

- 原问题；
- 修改文件；
- 修改行为；
- 是否涉及兼容性；
- 新增测试；
- 最终状态。

### C. 关键负向证据

必须列出实际跑过的：

- 缺上下文不激活；
- 动态 SOP 丢失阻断升级；
- 同数量规则语义变化被发现；
- 空 runtime 不得切换；
- launcher 指向错误版本被拒；
- rollback 失败时旧状态保持；
- once-only 不跨 session；
- 模型建议未确认不入 registry。

### D. 性能证据

- admission p50/p95；
- cold/warm start；
- LLM 调用次数；
- ticket/grant 次数；
- attach/status 时间；
- 增量扫描时间；
- receipt 大小。

### E. 安装与升级证据

- wheel 路径和摘要；
- clean venv 安装结果；
- 两个 runtime 版本；
- launcher 实际执行版本；
- sync 结果；
- rollback 结果；
- migration 中断结果。

### F. 测试证据

- 定向测试数量；
- 全量测试数量；
- skipped 及原因；
- 总 branch coverage；
- dynamic_sop coverage；
- upgrade coverage；
- registry/lifecycle coverage；
- lint/type/package/gate 结果。

### G. 外部验证剩余项

只能列真实宿主相关事项，例如：

- JobsFlow 真实入口覆盖；
- JobsFlow 产品检查接线；
- 第二个真实商业宿主；
- 真实宿主升级演练。

不能把本手册中已经可以本地完成的事项放到这里逃避修复。

---

## 20. 终极完成定义

本手册完成的标志不是测试数量增加，也不是报告写成“全部门禁绿”，而是：

1. 动态规则在缺上下文时不会错误激活；
2. 三类规则都永久存在且生命周期清楚；
3. 动态 SOP 能从不经意纠正中被捕获，但不会污染规则空间；
4. 用户确认和模型建议的权威性严格分开；
5. semantic diff 能发现同数量规则的真实行为变化；
6. sync 安装并运行真实新 runtime；
7. launcher、binding、adapter、hook 和 rollback 是一条真实执行链；
8. 普通动作的控制成本被限制在合理范围；
9. once-only 不会跨会话泄漏为长期规则；
10. clean package 和 clean checkout 可复现；
11. 关键分支有负向测试；
12. 文档、版本元数据和实际支持范围一致；
13. 所有未完成事项都确实属于真实宿主验证，而不是 SOP Control 自身的代码、架构或发布缺口。

达到以上条件后，等待 JobsFlow 真实接入只是外部证明工作，不再是 SOP Control 自身尚未完成的修复工作。
