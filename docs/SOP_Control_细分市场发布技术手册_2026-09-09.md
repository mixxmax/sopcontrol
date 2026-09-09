# SOP Control 细分市场发布技术手册

## 0. 手册定位

本手册面向 SOP Control 的第一次细分市场发布，不以企业级治理平台、通用沙箱或所有 Coding Agent 的完整实时接管为目标。

目标发布形态：

> 面向使用 Coding Agent 的个人开发者、小团队和 AI 产品团队，发布一个项目内生长、模型中立、低开销的 SOP 控制面 Early Access / Experimental Release。

本手册的当前审计基准为提交 `f65b191`。它只新增发布准备工作，不改变 SOP Control 的产品核心：限制 Agent 的行动和工作流漂移，让已确定的 SOP 在跨任务、跨会话和模型切换时继续有效。

---

## 1. 发布承诺必须先冻结

### 1.1 可以承诺的能力

发布说明可以明确承诺以下内容：

1. SOP Control 将用户和项目规则保存在项目内的控制面，而不是依赖模型记忆。
2. `attach` 可以接入新项目，也可以接入已有项目；默认不改业务源码。
3. 规则、任务、证据、判定、编年和空间度量可以跨会话恢复。
4. 已接入的工具面可以通过 Action Plane、Harness hook、Git hook 或 CI gate 受到约束。
5. 控制覆盖会区分 `detected`、`observable`、`enforceable`、`verified` 和 `gap`，不会把“发现了适配器”冒充为“已经生效”。
6. 快速路径以本地确定性检查为主，不要求每次变更都调用第二个模型。
7. 发现、候选聚合和空间度量可以自动进行；权威规则变更和永久退出仍由用户控制。

### 1.2 发布说明中不能承诺的能力

以下表述必须禁止：

- “保证模型永远不会犯错”；
- “所有 Harness 都支持实时调用前拦截”；
- “已经是沙箱，子进程无法绕过”；
- “自动理解并验证所有业务语义”；
- “安装一次后所有未知工具和外部系统天然都受控”；
- “覆盖率 100% 等于所有未来行为不可绕过”。

推荐的一句话定位：

> SOP Control 是一个项目内生长的、模型中立的 SOP 控制面，用来约束 Coding Agent 的行动和工作流，并诚实显示哪些执行表面已经受控、哪些仍然是 gap。

---

## 2. 当前产品是否适合细分市场

### 2.1 目标用户

首发用户应同时满足以下条件：

- 使用 Claude Code、OpenCode、Codex、Cursor 等 Coding Agent；
- 有明确且希望模型严格遵守的项目规则或工作流程；
- 关心模型换会话、换模型、接手遗留项目后的行为漂移；
- 接受“已验证的表面强制、未支持的表面显式 gap”这一诚实模型；
- 不把 SOP Control 当作敌对环境下的系统级安全沙箱。

### 2.2 首发用户不应包括

- 需要 SSO、组织级策略中心、审计后台和多租户管理的企业客户；
- 要求所有工具调用均在副作用前实时阻断的用户；
- 需要系统自动判断业务结果正确性的团队；
- 把不可信 Agent 当作对抗者、需要系统权限隔离的安全场景；
- 依赖尚未提供适配器的外部 scheduler、浏览器或产品专属业务 breaker 的用户。

### 2.3 产品功能结论

细分市场发布在功能上是可行的。核心差异已经成立：SOP Control 不是 AgentOps 的运行观测系统，而是项目中的规则执行和工作流控制面。

但发布对象必须是“需要 SOP 忠实执行的 Coding Agent 用户”，而不是“所有 AI 自动化用户”。

---

## 3. 当前发布阻断项

下表是发布前必须处理的事项。P0/P1 未关闭前，不应打正式 Release；P2 可以放到首发后的补丁或路线图。

| 编号 | 优先级 | 当前问题 | 为什么阻断 | 处理要求 |
|---|---|---|---|---|
| REL-001 | P0 | Ruff 在 `sopcontrol/cli_product.py` 使用 `sys.stderr`，但没有导入 `sys` | CI 的阻断检查会失败；而且超预算告警路径是实际功能路径 | 补导入，并增加覆盖超预算分支的测试 |
| REL-002 | P0 | 完整 pytest 主体通过，但 pytest-cov 收尾出现 statement/branch 数据混用的内部错误 | 不能把当前测试命令称为可重复的绿灯；CI 可能无法产出合法覆盖率 | 隔离 coverage 数据目录，统一子进程 branch 配置，或明确排除不应采集的子进程；重新得到有效的 `>=85%` 结果 |
| REL-003 | P0 | `AGENTS.md`、`CLAUDE.md` 相对权威 registry 已 stale | 模型实际读取到的项目切片可能不是当前控制面 | 运行 `sopctl project all .`，再运行 `sopctl project check .`，并把刷新结果纳入发布提交 |
| REL-004 | P1 | 当前工作树的 pre-push hook 仍是裸 `exec sopctl`；当 `sopctl` 不在 PATH 时 push 会失败 | 与“一次安装、低摩擦接入”目标冲突；GUI Git 和未激活 venv 的用户会直接被卡住 | fresh attach、upgrade、GUI/无 PATH 三种场景都验证 hook resolver；旧 hook 必须可自动刷新或给出明确迁移命令 |
| REL-005 | P1 | 当前代码提交未形成新的发布版本；`v0.2.0` 标签指向更早提交，CHANGELOG 仍有 `Unreleased` | 用户无法确定安装到的是哪个产品版本，也无法复现产品行为 | 冻结发布 SHA，更新版本号和 CHANGELOG，创建新 tag；不得把旧 tag 当作当前发布版本 |
| REL-006 | P1 | 项目本地有 dogfood 产生的 `.sopcontrol` evidence/task 脏改 | 可能把开发者自己的控制面历史误当成产品内容 | 发布提交不得包含本地任务和 ledger 脏改；发布前要区分源码、文档和 dogfood 数据 |
| REL-007 | P2 | 声明支持 macOS/Linux/Windows，但 CI 目前不是完整三平台矩阵 | 不能把未验证平台写成同等级 live-verified | 首发可只声明已验证平台；若继续声明 Windows，至少补安装、hook、路径和权限 smoke test |

### 3.1 当前最重要的判断

REL-001、REL-002、REL-003 是真正的发布阻断，不是产品方向问题。

REL-004 是与 SOP Control 核心价值直接相关的产品接入阻断，不能只靠“让用户自己 export PATH”长期解决。

REL-005、REL-006 属于发布卫生，但必须在正式打 tag 前收口。

---

## 4. Bug 修复手册

### 4.1 修复 `compat --measure` 的异常路径

目标文件：`sopcontrol/cli_product.py`

要求：

1. 导入 `sys`。
2. 保留当前正常测量路径和预算输出。
3. 增加至少两条测试：
   - `attach-status` 超预算时，命令仍输出 warning 并按产品约定返回；
   - `coverage` 超预算时，命令仍输出 warning 并按产品约定返回。
4. 运行：

```bash
.venv/bin/ruff check sopcontrol plugins tests
.venv/bin/pytest -q tests/harness/test_product_phase_f.py tests/harness/test_coverage_boost.py
```

### 4.2 修复 coverage 收尾不稳定

先不要直接提高或降低 `fail_under`。目标是让 coverage 结果真实、可重复。

发布前诊断顺序：

```bash
mkdir -p /tmp/sopcontrol-release-coverage
COVERAGE_FILE=/tmp/sopcontrol-release-coverage/.coverage \
  .venv/bin/pytest -q --cov --cov-report=term-missing
```

如果仍然出现 `Can't combine statement coverage data with branch data`：

1. 检查 pytest 启动的 Python 子进程是否继承了 coverage 环境；
2. 检查所有 coverage 数据是否统一使用 `branch = true`；
3. 对不应计入产品覆盖率的测试子进程关闭自动 coverage；
4. 在 CI 中使用独立的 runner 临时目录，不读取开发者工作树残留的 `.coverage*`；
5. 将“coverage 合并成功”本身加入 CI 验收，而不是只看测试数量。

完成定义：

- 测试命令退出码为 0；
- 没有 pytest-cov INTERNALERROR；
- 测试数量、跳过数量和覆盖率结果都被记录；
- statement + branch 综合覆盖率仍不低于 85%；
- 至少在一个干净环境中重复成功一次。

### 4.3 刷新规则投影

不得手工修改 `AGENTS.md` 或 `CLAUDE.md` 的自动生成区。使用：

```bash
.venv/bin/sopctl project all .
.venv/bin/sopctl project check .
```

完成定义：

- `project check` 返回 0；
- 中英文产品文档和投影中的核心定位一致；
- 当前链头、硬约束、Harness 边界与 registry 一致；
- 重新运行 `sopctl gate .` 后没有新的 fail。

### 4.4 修复 pre-push hook 的接入体验

新的 hook 模板已经具备 resolver 设计：优先 `SOPCTL_BIN`，其次项目 `.venv/bin/sopctl`，再尝试 common-dir、PATH 和 `python -m sopcontrol.cli`。

发布前必须验证下面三类场景：

| 场景 | 预期 |
|---|---|
| 新项目 `attach` / `hook install` | 写入 resolver，不依赖激活 venv |
| 已有旧版裸 hook 的项目升级 | 能识别并刷新 sopctl 自有 hook，保留第三方 hook |
| GUI Git 或 PATH 没有 `sopctl` | 仍能找到项目 venv，找不到时给出可执行的 fail-closed 安装提示 |

最低验收：

```bash
.venv/bin/sopctl hook install <fixture>
rg 'SOPCTL_BIN|\.venv/bin/sopctl|sopcontrol\.cli' <fixture>/.git/hooks/pre-push
```

不得通过 `git push --no-verify` 作为解决方案。

### 4.5 清理发布快照

发布前只保留以下内容进入产品提交：

- `sopcontrol/` 和 `plugins/` 源码；
- 必要的测试、fixtures、示例；
- 双语 README、限制说明、发布说明和技术手册；
- CI、打包和许可证文件。

不应把本机 dogfood 的 `.sopcontrol/tasks/`、ledger、growth snapshot 作为产品运行数据发布。

---

## 5. Harness 功能验收矩阵

发布说明必须按下面的强度写，不能把三种状态混写。

| Harness | 首发承诺 | 必测场景 | 不得声称 |
|---|---|---|---|
| OpenCode | runtime plugin interception；通过真实 callback 验证 | 允许、拒绝、未知工具、插件损坏、插件移除后 verified 撤销 | 只存在插件文件就算生效 |
| Claude Code | PreToolUse 协议适配；取决于实际 settings/API 环境 | 合并第三方 hook、全工具 matcher、损坏 settings 局部 gap、secret redaction | 所有用户环境都无需适配 |
| Codex | 投影 + `wrap` / `enter` + Git/CI 终态门 | 允许改动、受限路径、gate 阻断、跨会话恢复 | Pre-tool runtime enforceable |
| Cursor | 仅在实际使用的 wrapper/CI 边界上承诺 | wrapper 与终态门 | 任意 Cursor 工具都能实时拦截 |

每次发布都要运行：

```bash
.venv/bin/sopctl compat . --measure
.venv/bin/sopctl coverage . --probe
.venv/bin/sopctl attach-status .
.venv/bin/sopctl doctor . --full
```

推荐性能预算：

| 操作 | 预算 |
|---|---:|
| cold attach P95 | <= 60s |
| warm attach-status P95 | <= 2s |
| warm coverage P95 | <= 5s |
| fixture gate P95 | <= 30s |

当前已测得的 warm attach-status 和 coverage 处于预算内；发布前仍需在干净 fixture 上重复记录。

---

## 6. 产品级 E2E 验收场景

### 6.1 新项目接入

验收：

1. 目标项目无 `.sopcontrol/`；
2. 执行 `attach` 后建立身份、投影和适用 hook；
3. 不自动接受新的权威规则；
4. 普通业务源码不被改写；
5. `attach` 重复执行无语义变化；
6. `doctor` 能给出下一步，而不是要求用户理解内部结构。

### 6.2 中途项目接入

验收：

1. 已有 Git hook 时能够链式保留；
2. 已有 Claude settings 或 OpenCode plugin 时只修改 sopctl 自有部分；
3. 某个 Harness 配置损坏时，其他接入面仍可用；
4. 大量 Markdown、数据目录或遗留代码不会让整个 attach 失败；
5. `coverage` 明确列出未接入表面。

### 6.3 SOP 严格执行

至少验证：

1. Agent 写 `.sopcontrol/` 被拒绝；
2. 规则允许的业务文件可以正常修改；
3. 受限路径之外的写入被拒绝；
4. `--no-verify` 被视为违规，而不是静默放行；
5. 未知工具会降低 coverage 或产生 gap；
6. 适配器文件存在但 callback 未执行时不能标记 `verified`；
7. 模型切换后权限只收紧，不扩大；
8. secret 不出现在 event、receipt、command summary 和 digest 之外的可读内容中；
9. 失败规则会阻断 gate，单独 gap 只按产品约定告警；
10. gate 或账本异常时 fail-closed。

### 6.4 动态空间和低能耗路径

验收：

1. 默认 attach、doctor、coverage 不调用第二个模型；
2. 日常路径不重复跑完整高成本审计；
3. 新入口能够产生 observation 或 candidate；
4. 候选不会自动晋升为权威规则；
5. 用户确认后才 enact、退休或扩大规则；
6. `growth measure/diff` 能显示空间变窄或变宽；
7. 用户可以只处理当前下一刀，不需要重读完整历史。

---

## 7. 发布版本和安装策略

### 7.1 首发渠道

细分市场首发可以先采用 GitHub pinned commit，不必等 PyPI：

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'git+https://github.com/mixxmax/sopcontrol.git@<RELEASE_SHA>#egg=sopcontrol'
.venv/bin/sopctl compat
```

发布文案必须同时给出：

- release tag；
- commit SHA；
- 支持的 Python 版本；
- 已验证的 Harness；
- 明确的非目标能力；
- 回滚/卸载命令。

### 7.2 版本冻结

发布前必须完成：

1. 选择版本号，不让 `pyproject.toml`、CHANGELOG、tag 和 README 各说一套；
2. 将当前 `Unreleased` 内容归入该版本；
3. 记录 release SHA；
4. 从干净 checkout 安装该 SHA；
5. 运行完整验收后再创建 tag；
6. tag 创建后不允许重新指向其他提交。

### 7.3 回滚

回滚只允许回到已验收的 release SHA：

```bash
.venv/bin/pip install -e /path/to/sopcontrol-at-<KNOWN_GOOD_SHA>
.venv/bin/sopctl compat .
.venv/bin/sopctl doctor .
```

回滚不得删除消费者项目的 `.sopcontrol/` 规则和证据。

---

## 8. Release Go / No-Go 清单

### No-Go 条件

任一条件成立，不能发布正式细分市场版本：

- Ruff 或 CI 失败；
- coverage 命令以 INTERNALERROR 结束；
- `sopctl project check` 失败；
- OpenCode/Claude 的声称与真实 callback 不一致；
- Codex/Cursor 被文档误写成实时强制；
- 新鲜安装后 hook 依赖用户手动设置 PATH 才能运行；
- secret 出现在 receipt 或事件摘要；
- 失败规则没有阻断 gate；
- release tag 无法从干净环境复现；
- 发布说明隐瞒“不是真正沙箱”的边界。

### Go 条件

以下全部满足后，可以发布细分市场 Early Access：

- [ ] REL-001 至 REL-006 已关闭；
- [ ] `project check` 通过；
- [ ] `doctor --full`、`compat --measure`、`coverage --probe` 通过；
- [ ] 完整 pytest 和 coverage 在干净环境成功；
- [ ] 最小示例能完成一次预期阻断；
- [ ] 新项目和中途接入两个 E2E 场景通过；
- [ ] 至少一个实时 Harness 和一个事后门 Harness 有真实验收记录；
- [ ] 双语 README、LIMITATIONS、CHANGELOG 和安装命令一致；
- [ ] release SHA、tag、安装命令和回滚命令已记录；
- [ ] 发布后 issue 模板和支持边界已准备。

---

## 9. 首发后的监控指标

首发后不追求复杂后台，先用本地或用户主动提供的结果收集以下指标：

1. 首次 attach 成功率；
2. 中途接入后能继续工作的比例；
3. hook/plugin 真实触发率；
4. `verified` 被撤销的次数；
5. false block rate；
6. 每个任务新增的人工中断次数；
7. attach、coverage、gate 的 P95 时间；
8. 规则上下文新增 Token 量；
9. gap 到可处理 candidate 的收敛时间；
10. 用户明确报告的“模型漂移、绕 SOP、重复劳动”次数。

默认不上传用户源码、对话、凭据或完整浏览器内容。只收集用户主动提供的摘要、分类、计数和错误类型。

---

## 10. 最终发布判断

SOP Control 不需要在首发前变成企业治理平台，也不需要增加默认监督 Agent 或业务语义审批层。

首发真正要证明的是三件事：

1. 用户确定的 SOP 能在支持的执行表面持续约束 Agent；
2. 不支持或尚未接入的表面会被诚实暴露，而不是被虚假标记为已控制；
3. 新项目和中途项目都能低成本接入，不需要先重写业务产品。

当前产品方向已经满足这三个目标的主体设计。完成 REL-001 至 REL-006、通过 Go 清单后，可以以细分市场 Early Access 方式发布；不应把它包装成通用沙箱、企业治理套件或所有 Harness 的实时不可绕过执行器。
