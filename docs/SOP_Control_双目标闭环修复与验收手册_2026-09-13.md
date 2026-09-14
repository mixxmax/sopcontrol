# SOP Control 双目标闭环修复与验收手册

## ——面向从未接触过本项目的外部模型

- 版本：v1.0
- 日期：2026-09-13
- 执行范围：SOP Control 本身
- 不在范围：JobsFlow、JobsDB、业务抓取、材料生成、业务语义 lint 的实现
- 目标 A：建立一个能够随着产品生长而生长的规则空间
- 目标 B：让 SOP Control 接入成本低、覆盖完整，并能执行用户或产品声明的动态 SOP
- 交付要求：至少完成本手册验收项的 90%，未完成项必须逐项说明，不能用“代码已经写完”代替证据

---

## 0. 交给外部模型的第一条指令

你第一次接触这个仓库。不要相信任何历史报告中的“全部完成”“全部通过”“评分 8.8”或类似结论，除非你在当前工作区重新运行命令并得到证据。

你要完成的不是把 SOP Control 做成更复杂的审计平台，而是让它可靠地完成两个职责：

1. 当产品增加、删除或改变工具、脚本、阶段和执行入口时，SOP Control 能发现这些变化，并将其纳入已有规则、候选规则或明确的覆盖缺口；
2. 当产品实际运行时，所有受控动作都经过统一控制入口，动态 SOP 被正确合成和执行，而且不要求用户长期维护大量产品专用胶水代码。

开始前必须：

- 读完本手册；
- 读完 AGENTS.md；
- 查清项目的真实 CLI、测试入口、规则 registry 和门禁流程；
- 先建立工作区基线；
- 先写并运行最小复现实验，再改实现；
- 每修复一项都补回归测试；
- 最后按第 20 节报告。

本手册不授权你修改 JobsFlow 或其他业务产品，不授权你关闭 enforce/ticket，不授权你删除旧测试，也不授权你 commit 或 push。若任务发起者另行明确授权，才可以执行相应 Git 操作。

---

## 1. 两个目标的准确含义

### 1.1 目标 A：随着产品生长而生长的规则空间

目标 A 不是“让 SOP Control 自动替用户制定业务规则”，也不是让模型自由生成一套新的审计标准。

目标 A 的准确含义是：

- 产品增加新能力时，SOP Control 能观察到新能力；
- 新能力有稳定的身份，而不是只按文件路径识别；
- 如果新能力与已有能力相似，优先继承适用规则；
- 如果无法证明可以继承，生成清晰的规则候选或覆盖缺口；
- 规则候选包含来源、影响面、建议继承关系和待确认差异；
- 用户或业务系统确认后，候选才进入权威规则空间；
- 规则空间的每次变化都有版本、摘要和可回滚关系；
- 新规则生效后，新能力自动进入控制链；
- 产品删除或重命名能力时，旧规则不会静默指向别的能力；
- 这一过程不会让每个普通动作都额外触发重复审计或大量 token 消耗。

它遵循四句话：

- 无感发现；
- 最小建议；
- 显式定型；
- 自动执行。

“显式定型”只针对规则含义的变化，不是要求用户批准每一个日常动作。

### 1.2 目标 B：低接入成本、完整覆盖、动态 SOP 执行

目标 B 包含三个独立要求。

#### 低接入成本

用户安装一次或执行一次引导后，SOP Control 应当能够：

- 识别当前项目是什么；
- 发现可用的 Claude、OpenCode、CLI、wrapper、插件、脚本或其他 harness；
- 发现已存在的产品入口；
- 给出覆盖情况和缺口；
- 尽可能生成必要的桥接或 wrapper；
- 保留用户原有配置；
- 不要求用户先大规模改造业务产品；
- 支持产品已经开发到一半时再接入；
- 支持重复执行而不会重复创建或破坏配置。

#### 覆盖完整

覆盖完整不是“扫描到了很多文件”，而是：

- 每一个能够发起受控动作的执行表面都有稳定身份；
- 每一个高影响或外部副作用动作都经过受控入口；
- 入口无法接入时有明确的 gap 或 blocked 状态；
- 不把“发现了文件”误认为“已经控制了文件”；
- 不把只有某一个 harness 接通误认为全部工具都接通；
- CLI、wrapper、shell、解释器、插件、子进程和正式业务入口的结果一致；
- 新增入口能被目标 A 的生长机制发现并纳入覆盖图。

#### 动态 SOP 执行

SOP Control 应当执行用户或业务系统声明的规则：

- 哪个阶段允许什么动作；
- 需要经过哪些检查；
- 哪些检查是必须的；
- 容忍度是什么；
- 是否允许修正；
- 修正范围和轮数是什么；
- 什么条件下停止；
- 哪些规则从上层继承；
- 哪些上下文必须一致。

SOP Control 不负责理解业务内容本身。比如“材料是否贴合 JD”由 JobsFlow 的语义检查负责；SOP Control 只负责确保 JobsFlow 声明的这项检查确实经过，并且结果来自正确入口、对应正确任务和规则。

---

## 2. 两个目标的关系

两个目标不是二选一，而是一条链上的两端：

    产品变化
      -> 发现新的执行表面
      -> 判断是否已有规则可以继承
      -> 生成候选或覆盖缺口
      -> 用户/产品确认规则含义
      -> 编译有效动态 SOP
      -> 新入口接入统一 bridge/harness
      -> challenge/admit/execute
      -> 检查结果和运行上下文绑定
      -> 未来产品变化继续被发现

只有目标 A，没有目标 B：

- 系统可以发现新入口；
- 但新入口可能实际绕过控制；
- 规则空间会变成“观察报告”，没有执行力。

只有目标 B，没有目标 A：

- 已知入口可以被控制；
- 但产品一增长就需要人工逐项配置；
- 最终接入成本随产品规模线性增长；
- 规则空间会变成静态配置，而不是随产品演化。

本次执行必须同时验证 A 和 B 的端到端关系。

---

## 3. 当前距离的起始判断

以下不是最终结论，而是执行模型开始时的待验证基线。

根据最近一次独立检查，项目已经具有：

- rule registry 和自动投影；
- Base、Task、Run、Actor 多层 profile；
- task、plan、run、actor digest；
- doctor、growth status、growth measure、growth diff、candidate 等生长基础设施；
- bridge、wrapper、harness、ticket、receipt；
- 较多定向测试；
- 普通全量测试曾达到 981 passed、1 skipped；
- ruff、gate、project check、chronicle check 曾通过。

但这些事实不能直接证明双目标已经闭环，因为最近的实际复查仍发现以下类型的问题：

- 某些入口在 side_effect 省略时可能直接执行外部命令；
- manifest 中的备份路径可能缺少完整 containment 校验；
- 部分 profile 合成可能无法区分“字段未声明”和“字段显式写成默认值”；
- bridge 可能先生成 envelope、后分类 side effect，造成 operation 与 receipt 不一致；
- capability_binding 尚未确认是否贯穿正式 CLI 和所有 wrapper；
- ControlResult 可能从 checked_dimensions 猜测缺少的 check_id；
- 输入摘要的 symlink 实际行为可能与文档不一致；
- 安装、卸载和恢复失败时可能没有完整事务保证；
- handoff 写入可能不是独占、原子和抗覆盖的；
- coverage 的完整 branch 结果最近一次未完成，不能把中断当成通过；
- growth 机制已有骨架，但尚未用一个真实的“新增产品能力”场景证明完整闭环。

因此当前距离可以分成四层：

| 层次 | 当前判断 | 目标 |
| --- | --- | --- |
| 产品理念 | 已基本明确 | 保持边界清晰 |
| 控制基础设施 | 已形成主体 | 修复边界和一致性 |
| 生长闭环 | 有骨架、证据不足 | 用端到端 fixture 证明 |
| 发布级可靠性 | 仍有缺口 | 全量验收后再判断 |

不能直接把当前项目报告为 8.8。更合理的起始判断是：

- 目标 A 的基础设施约已完成 70%～80%，生长闭环的实证约 40%～50%；
- 目标 B 的基础设施约已完成 70%，真实全入口覆盖和低摩擦体验约 50%～60%；
- 整体还需要一次专项收口，不需要重做产品。

执行结束时，外部模型必须用实测结果重新计算，而不能沿用这个估计。

---

## 4. 产品边界和禁止方向

### 4.1 SOP Control 应该保留的能力

- 受控入口；
- 统一动作身份；
- 阶段和状态门；
- 动态规则编译；
- 规则候选与覆盖缺口；
- task/run/actor/plan 上下文绑定；
- 失败时停止；
- 可解释的 doctor 和 gate；
- 安全的安装、卸载、恢复和 handoff；
- 最小充分证据；
- 低开销运行。

### 4.2 不要在 SOP Control 中加入的能力

不要因为“增强控制”而加入：

- JobsFlow 的 JD 语义判断；
- 材料事实和语言质量判断；
- 固定的独立审计风格；
- 要求所有内容严格服从某一种基线解释；
- 每个普通动作都要人工审批；
- 每次小修改都启动多模型交叉审查；
- 用 SOP Control 保存所有业务产物全文；
- 为了留痕而强制对所有文件重复哈希；
- 让模型自由写理由后自称“审计通过”；
- 让规则空间自动扩大检查范围；
- 让未知命令默认安全；
- 用规则关闭或 ticket 关闭来绕过缺口。

业务产品可以声明自己的语义检查和审计目标。SOP Control 只负责控制这些声明是否被执行，不能擅自替换声明内容。

---

## 5. 外部模型的执行纪律

### 5.1 必须先读的文件

按以下顺序定向阅读：

1. AGENTS.md；
2. DESIGN.md；
3. PLAYBOOK.md；
4. SKILL.md 或仓库中的 SOP Control 执行说明；
5. pyproject.toml；
6. 本手册；
7. docs/ 中与闭环修复、动态规则、安装、bridge、growth、发布相关的文档；
8. 生产代码：
   - sopcontrol/control_profile.py
   - sopcontrol/control_result.py
   - sopcontrol/tickets.py
   - sopcontrol/bridge.py
   - sopcontrol/bridge_scaffold.py
   - sopcontrol/task.py
   - sopcontrol/cli.py
   - sopcontrol/cli_task.py
   - sopcontrol/capability.py
   - sopcontrol/scope.py
   - sopcontrol/discovery_manifest.py
9. 相关测试和 fixture。

推荐搜索：

    rg --files -g 'AGENTS.md' -g 'DESIGN.md' -g 'PLAYBOOK.md' -g 'SKILL.md' -g 'pyproject.toml' -g 'sopcontrol/**' -g 'tests/**' -g 'docs/**'
    rg -n "growth|candidate|doctor|discover|coverage|registry|profile|_merge_all_fields|model_fields_set|side_effect|canonical|operation_id|run_id|capability_binding|prev_backup|handoff|check_id|symlink" sopcontrol tests docs

### 5.2 .sopcontrol 的硬约束

不得通过 shell、Python、编辑器或普通文件 API 直接修改 .sopcontrol 内的权威文件。

规则、任务、账本、证据和状态必须使用项目提供的 sopctl 子命令。先查：

    sopctl --help
    sopctl task --help
    sopctl project --help
    sopctl growth --help
    sopctl candidate --help
    sopctl gate --help

如果 sopctl 不在 PATH，使用项目规定的 Python module 入口，例如：

    .venv/bin/python -m sopcontrol.cli --help

不要自行猜测子命令参数。当前仓库的实际命令优先于本手册的示例。

### 5.3 工作区保护

开始时记录：

    pwd
    git status --short --branch
    git log -1 --oneline
    git diff --stat
    git diff --check

保留用户已有修改。不要使用：

- git reset --hard；
- git checkout --；
- git clean；
- 删除仓库范围目录；
- 关闭或卸载已有 hook/插件；
- 通过修改测试预期来消除失败。

临时实验只能在明确创建的临时目录内进行，不要污染项目实际业务目录。

---

## 6. 总体执行顺序

必须按以下阶段执行：

### 阶段 0：基线和项目地图

目标：知道当前有什么，不重复做已完成工作。

交付：

- 文件和入口地图；
- 当前规则和 CLI 说明；
- 当前测试入口；
- 当前已知缺口清单；
- Git 工作区基线；
- 当前 growth/candidate/doctor 状态摘要。

### 阶段 1：建立统一 Surface Inventory

目标：把“产品里所有可能发起动作的地方”定义成可比较的执行表面。

交付：

- 静态发现结果；
- 运行时探针结果；
- 稳定 surface identity；
- covered / uncovered / ambiguous / waived 分类；
- 能够被 growth diff 比较的 manifest。

### 阶段 2：修复目标 B 的控制底座

目标：任何已发现的 surface 都能通过统一控制入口执行，不能漏票、错绑或旁路。

交付：

- 统一 side-effect 分类；
- canonical invocation；
- 稳定 operation/run；
- capability_binding 全链路传递；
- ticket/admit/receipt 一致；
- 安全 wrapper、handoff、安装、卸载和 rollback。

### 阶段 3：修复动态规则编译

目标：不同层的规则能正确继承和收紧，不能被模型默认值或上下文漂移破坏。

交付：

- absent 与 explicit 的区分；
- Base/Task/Run/Actor 合成；
- scope、baseline、expires、budget、repair、stop 等语义；
- profile/effective plan digest；
- 缺少 check_id 不再被猜测。

### 阶段 4：实现目标 A 的生长闭环

目标：模拟产品增加、修改、删除能力，证明规则空间能跟随变化。

交付：

- 发现新 surface；
- 规则匹配或候选生成；
- 候选解释和 diff；
- 接受、拒绝、撤回、版本化、回滚；
- 新 surface 纳入控制；
- 旧 surface 删除或重命名不会产生错误映射。

### 阶段 5：成本、噪声和中途接入优化

目标：生长和控制不会让用户承担持续的配置、审计和 token 成本。

交付：

- 增量发现；
- 稳定缓存；
- 一次逻辑动作尽量一次 challenge/admit；
- 只在规则变化或高影响缺口时升级；
- 中途接入不覆盖既有产品配置；
- doctor 输出可直接执行的最小修复建议。

### 阶段 6：最终验收

目标：全量证明，不凭局部测试宣布完成。

交付：

- 定向测试；
- 生长 fixture；
- 全量测试；
- branch coverage；
- ruff；
- gate/project/chronicle；
- 最终报告和剩余风险。

---

## 7. WP-A1：建立 Surface Inventory 和稳定身份

### 7.1 什么是执行表面

执行表面是任何可能触发 SOP 约束动作的入口，包括但不限于：

- CLI 命令；
- Python、Node 或其他解释器脚本；
- 可执行文件和 shebang 文件；
- wrapper；
- shell -c；
- Claude/OpenCode tool adapter；
- plugin；
- subprocess；
- CI 脚本；
- 浏览器、网络、SSH、数据库等外部工具；
- 生成、写入、发布、部署、发送、删除等高影响动作；
- 产品在运行时动态加载的入口。

发现文件不等于发现执行表面。一个脚本可能没有被调用，一个命令也可能通过多个 wrapper 被调用。

### 7.2 Surface identity

为每个 surface 建立稳定身份。身份至少考虑：

- integration；
- surface_kind；
- 规范化业务 argv；
- action；
- phase；
- 业务入口的稳定名称；
- 产品声明的 capability 或 binding；
- 相关 task/plan 关系。

身份不能主要依赖：

- 临时 wrapper 路径；
- $0；
- 解释器的绝对路径；
- 当前时间；
- attempt；
- handoff 临时文件名；
- ticket secret；
- 机器本地临时目录。

同一业务命令换一个 wrapper 仍应能识别为同一业务 surface；两个业务动作即使共用一个 wrapper，也必须有不同 identity。

### 7.3 Inventory 状态

每个 surface 至少有以下状态之一：

- observed：已发现，尚未完成映射；
- mapped：已映射到一个明确控制入口；
- governed：已经通过统一 admission；
- candidate：需要确认适用哪条规则；
- ambiguous：存在多个可能映射，不能自动选择；
- gap：发现但没有可用控制入口；
- waived：有明确、可追溯的豁免；
- retired：已删除或不再存在；
- blocked：由于缺少必要条件而阻断。

不得把 observed 直接标记成 governed。

### 7.4 WP-A1 验收

新增一个 fixture surface 后必须证明：

- discovery 能发现它；
- surface identity 稳定；
- wrapper 路径变化不导致错误的新 surface；
- 业务 argv 变化能产生不同 identity；
- surface 状态从 observed 开始；
- 没有 admission 的 surface 不能变成 governed；
- 未知 surface 不会被默认当作只读安全入口。

---

## 8. WP-A2：覆盖模型和完整覆盖判定

### 8.1 覆盖记录

为每个 surface 生成一条覆盖记录，至少包含：

- surface_id；
- source/discovery evidence；
- intended action；
- side_effect；
- phase；
- control route；
- adapter/harness；
- required checks；
- task/profile/plan 绑定；
- last observed digest；
- last governed receipt；
- current status；
- gap reason；
- waiver 信息（如有）。

### 8.2 “完整覆盖”的判定

完整覆盖必须按动作而不是文件数量计算：

    可触发受控动作的 surfaces
      = governed surfaces
      + 明确、安全且有理由的 waived surfaces
      + 明确记录的 blocked/gap surfaces

当存在未解释的 surface 时，覆盖不能报告为 100%。

建议输出至少三个数字：

- discovered_count；
- governed_count；
- unresolved_count。

还要输出高影响未覆盖数量。即使普通只读 surface 有少量 gap，只要高影响写动作未覆盖，就不能通过 enforce 发布门。

### 8.3 防止虚高

以下不算覆盖：

- 只扫描到文件名；
- 只发现了一个主入口；
- 只测试了 Claude，未测试 OpenCode 或 CLI；
- 只测试内部函数，未测试正式 CLI；
- 只生成了 wrapper，没有证明 wrapper 的执行经过 admission；
- 有 receipt，但 receipt 与实际 argv 不一致；
- 有 ticket，但 ticket 绑定了错误的 operation；
- 规则 registry 中有规则，但 surface 没有使用它；
- 业务系统说“会调用 lint”，但没有证据证明该阶段确实经过 lint。

### 8.4 覆盖缺口的严重级别

建议至少分为：

- P0：可绕过 enforce 或执行高影响动作；
- P1：已知入口没有稳定控制或上下文可错配；
- P2：安装、卸载、恢复、诊断或版本兼容问题；
- P3：信息展示、性能、文档或非关键可用性问题。

任何 P0/P1 未解释问题都阻断完成。

---

## 9. WP-B1：统一 side-effect 分类

### 9.1 设计要求

实现一个唯一的 side-effect classifier，并让以下路径复用：

- install_wrapper；
- install_scaffold；
- bridge run；
- bridge challenge；
- bridge admit；
- 正式 CLI；
- scaffold 生成的 wrapper；
- plugin/adapter；
- 任何会 spawn 子进程的入口。

不要在某一个入口增加局部判断而保留其他旁路。

### 9.2 分类原则

分类必须基于：

- 原始 argv；
- 去掉 wrapper、解释器和 shell 外壳后的业务 argv；
- 显式 side_effect；
- integration；
- action；
- phase；
- task、plan 和 capability binding；
- 是否触发网络、外部进程、文件写入、发布、删除或其他外部副作用。

至少关注：

- curl；
- wget；
- ssh；
- scp；
- rsync；
- 浏览器自动化；
- 数据库客户端；
- 远程 URL；
- 远程主机；
- 发布和部署命令；
- 写文件、删除、移动和权限变化。

已知外部工具即使本次参数是 --version，也不能单凭参数表面把它归为安全 readonly。

### 9.3 冲突处理

- 显式 side_effect 比自动分类更宽松：拒绝；
- 显式 side_effect 比自动分类更严格：可以接受，但要进入 canonical payload；
- side_effect 无法确定：unknown 或拒绝；
- unknown 不能静默降级为 safe；
- 分类必须在 envelope 和 operation_id 生成之前完成；
- 分类变化必须让旧 ticket 失效。

### 9.4 R-B1 复现

使用临时目录和安全协作子进程：

- 调用 install_scaffold 的正式路径；
- command 使用可被识别为外部工具的命令；
- 省略 side_effect；
- 记录是否直接执行；
- 记录是否产生 challenge、admit、ticket、receipt。

修复后必须证明：

- 省略 side_effect 不会获得 direct 执行；
- 正式 CLI、内部 API、wrapper 结论一致；
- 失败路径不生成成功 receipt；
- 不需要真实网络。

---

## 10. WP-B2：canonical invocation、operation 和 run

### 10.1 规范化流水线

所有受控操作必须按如下顺序：

    raw argv
      -> 去除 wrapper/解释器/shell 外壳
      -> business argv
      -> side-effect classification
      -> 合并显式 side_effect
      -> 输入摘要
      -> task/phase/plan/actor/capability context
      -> canonical invocation
      -> operation_id
      -> stable run_id
      -> challenge/ticket/admit
      -> execute
      -> receipt

不能先生成 envelope，再补做 side-effect 分类。

### 10.2 canonical payload

canonical payload 至少绑定：

- integration；
- action；
- 规范化业务 argv token；
- side_effect；
- task digest；
- phase；
- plan digest；
- capability binding；
- 必要的 input digest。

不要绑定：

- wrapper 路径；
- $0；
- 解释器路径；
- shell 外壳；
- 当前时间；
- attempt；
- handoff 文件名；
- ticket secret；
- 只在本地存在的临时路径。

### 10.3 一致性不变量

同一次操作必须满足：

- challenge.operation_id = ticket.operation；
- admit.operation_id = ticket.operation；
- receipt.operation_id = ticket.operation；
- ticket、admit、receipt 的 run_id 一致；
- task、phase、plan、actor、capability binding 一致；
- 业务 argv 改变后旧 ticket 失效；
- side_effect 改变后旧 ticket 失效；
- 输入摘要改变后旧 ticket 失效；
- capability binding 改变后旧 ticket 失效；
- 票据消费后不能重放；
- 空 binding 不能解释为通配。

### 10.4 稳定 run_id

challenge 和重试必须可以使用同一个稳定 run_id 或由稳定 operation_id 派生的 run_id。

禁止：

- 每次 CLI 重试都无条件生成新的 run_id；
- 让票据指纹绑定 run_id，但又不给调用方传入或复用 run_id 的办法；
- 通过不断生成新票据制造 challenge 死循环。

---

## 11. WP-B3：capability ticket 的正确位置和低成本实现

### 11.1 ticket 的职责

ticket 是受控操作的短期、一次性许可，不是用户需要反复手工维护的业务配置。

它应证明：

- 当前动作已被 challenge；
- 当前 operation、run、task、phase 和计划一致；
- 当前动作在允许范围内；
- ticket 尚未消费、未过期、未被重放。

### 11.2 低成本要求

在不削弱控制的前提下：

- 一个逻辑动作尽量只做一次 challenge 和一次 admit；
- 多阶段操作可以使用一个有明确 phase grant 的 operation chain；
- 不要每个内部 helper 都重新挑战；
- 纯函数和只读计算不应创建 ticket；
- 只有真正的受控 side effect 才需要 ticket；
- ticket 错配时立即失败，不重复自动生成无限新 ticket；
- 重试最多一次，且必须复用稳定上下文；
- 任何 ticket 失败都要告诉调用方缺少哪个字段或哪个 digest 不一致。

建议建立成本计数器，至少统计：

- challenge_count；
- admit_count；
- execute_count；
- retry_count；
- repeated_context_count。

验收时报告一条普通动作和一条多阶段动作的实际计数。

### 11.3 票据安全

必须保证：

- allowed_actions 空集合不会变成允许全部；
- 空 binding 不会变成通配；
- consumed ticket 默认拒绝；
- 过期 ticket 拒绝；
- operation 不匹配拒绝；
- action/phase 不匹配拒绝；
- secret 不进入 receipt、日志、异常摘要或命令 tail；
- 预兑换但未在 payload 中传递的 ticket 不能让 admit 放行；
- 不支持 env 隐式注入时，CLI 必须提供明确的透传方式。

---

## 12. WP-B4：capability_binding 的全链路传递

如果动态规则需要 capability_binding，必须检查并补齐：

- run_bridge API；
- CLI；
- scaffold；
- wrapper；
- challenge；
- admit；
- ticket；
- handoff；
- receipt；
- task/plan/profile（如果它参与规则绑定）。

必须用端到端测试证明：

    CLI 参数
      -> canonical payload
      -> challenge
      -> ticket
      -> admit
      -> 子进程
      -> receipt

缺少 capability_binding 时：

- 如果当前规则要求它，返回 missing_context 或 unknown；
- 不得生成万能 ticket；
- 不得从 action 或 ticket id 猜测 binding；
- 不得从旧 receipt 自动复用。

---

## 13. WP-B5：动态 profile 的正确合成

### 13.1 未声明和显式声明必须区分

动态 profile 分层通常包括：

- Base；
- Task；
- Run；
- Actor。

必须区分：

- absent；
- explicit null；
- explicit default；
- explicit non-default；
- nested field absent；
- nested field present。

不能把每层先解析成所有字段都有默认值的完整模型，再判断是否放宽。这样会把“没有声明”错误地当成“主动放宽”。

可使用：

- partial model；
- Pydantic model_fields_set；
- presence map；
- 原始 layer config + normalized value 的双重表示。

### 13.2 只收紧语义

默认合成规则：

- checks：只能增加，不能删除；
- required/excluded 冲突：拒绝；
- mode：只能向严格方向变化；
- tolerance：只能向严格方向变化；
- budget：只取显式层中的更小值；
- rounds：只取显式层中的更小值；
- repair：只能减少权限或范围；
- stop：只能增加停止条件，不能移除；
- baseline：省略则继承，显式改变必须拒绝或形成明确新 revision；
- scope：省略则继承，不能扩大；
- expires_at：取更早的有效时间；
- actor constraint：只能收紧；
- unknown field：拒绝。

如果当前层没有声明某字段，直接继承上层有效值，不参与“放宽比较”。

### 13.3 digest

effective profile digest 必须包含：

- 规范化后的 effective profile；
- 各层 digest；
- 各层实际声明字段集合；
- task、run、actor snapshot；
- baseline、scope、expires_at；
- mode、tolerance、budget、repair、stop；
- schema/version。

不能包含：

- secret；
- wrapper 临时路径；
- 未排序字典；
- 不稳定时间；
- 未声明字段被模型默认填入的内容。

### 13.4 动态规则与业务语义的边界

如果 JobsFlow 声明：

- 检查材料是否贴合 JD；
- 允许合理的表达性夸大；
- 不反复修正不重要的小差异；
- 事实基线作为起点而非无限制的二次质疑；

这些内容可以作为业务产品的 profile 参数、check registry 或审计配置传入。SOP Control 负责：

- 规则是否声明；
- 规则是否按层正确继承；
- 必需检查是否执行；
- 结果是否属于正确 check_id；
- 后续阶段是否被正确阻断或放行。

SOP Control 不应自行判断这些语义。

---

## 14. WP-B6：ControlResult 和检查身份

check_id 是检查的正式身份，不是可推测的展示字段。

必须禁止：

- 从 checked_dimensions[0] 自动填充 check_id；
- 从自由文本 reason 生成 check_id；
- 从 action、phase 猜测 check_id；
- 只有 checked_dimensions 但没有明确检查身份时放行；
- 只有 user_accepted=true 就当作独立检查通过。

允许通过的结果必须满足：

- check_id 明确存在；
- check_id 格式有效；
- check_id 在当前 registry/profile 中声明；
- 结果与 task、phase、plan 和 actor 匹配；
- checked_dimensions 作为补充信息；
- 必要的检查证据真实存在。

缺失 check_id 时可以返回 reject、unknown 或 not_run，但不能返回可供下一阶段直接放行的 pass。

---

## 15. WP-B7：安装、attach、midstream 接入和 detach

### 15.1 一次安装的体验目标

安装或 attach 应完成：

1. 识别项目；
2. 检测现有 harness；
3. 发现可能的执行表面；
4. 生成覆盖摘要；
5. 生成最小必要 wrapper/adapter；
6. 保留现有配置；
7. 运行安全自检；
8. 输出需要用户确认的少量高价值决策；
9. 让一个安全 fixture 走通 challenge/admit/execute/receipt。

不应要求用户先手动改造大量业务代码。

### 15.2 中途接入

中途接入必须：

- 先建立既有产品的输入和入口快照；
- 不覆盖既有脚本、配置和 hook；
- 对未知入口先标为 observed/gap，而不是静默接管；
- 尽可能生成兼容 wrapper；
- 只请求一次必要的规则或集成确认；
- 支持从 observe/diagnose 进入 enforce；
- 接入失败时保留原产品可运行状态；
- 能够输出具体的最小修复清单。

### 15.3 attach 的边界

如果没有真实的 Claude/OpenCode adapter：

- 不要伪造 adapter_alive=true；
- 不要创建无意义的 .claude 或 .opencode 目录；
- doctor 应报告 adapter_missing；
- 可以生成诊断和候选，但不能报告 fully governed。

### 15.4 detach

detach 只能删除自己创建的内容：

- 只移除自己添加的 hook；
- 保留其他 hook；
- 只删除自己拥有的 wrapper；
- 使用 manifest 和 owner 信息；
- manifest 不可信或越界时先拒绝；
- 失败时保留 backup 和 manifest；
- 不删除外部路径；
- 不声称卸载成功。

---

## 16. WP-B8：manifest、备份和失败事务

### 16.1 manifest 是不可信输入

每次使用 manifest 前重新校验：

- schema；
- version；
- integration；
- owner；
- files；
- prev_backup；
- digest；
- installation id；
- task/project 关系；
- 路径边界；
- lstat 类型；
- symlink；
- 权限；
- 文件存在性。

全部校验完成前，不得执行 unlink、rename、chmod、truncate 或写入。

### 16.2 路径 containment

建议边界：

- wrapper 只能位于项目内约定的 .sopcontrol-local/bin；
- rollback backup 只能位于项目内约定的 .sopcontrol-local/bridge-rollback；
- 不接受任意绝对路径；
- 不接受 ../ 逃逸；
- 不接受 symlink 逃逸；
- 不接受目录、socket、设备等特殊文件；
- 不接受未确认 owner 的文件。

### 16.3 安装事务

建议顺序：

1. 读取旧状态并验证；
2. 创建 backup；
3. 写 wrapper 临时文件；
4. 设置权限；
5. fsync 临时文件；
6. 原子替换 wrapper；
7. 写 manifest 临时文件；
8. fsync manifest；
9. 原子替换 manifest；
10. 必要时 fsync 父目录；
11. 全部成功后报告成功。

失败时：

- 尽量恢复旧目标；
- 保留可识别 backup；
- 删除不完整临时文件；
- 不提交成功 manifest；
- 如果恢复失败，返回 recovery_required；
- 不留下“新 wrapper + 旧 manifest”的不可解释状态。

### 16.4 卸载事务

卸载前：

- 验证完整 manifest；
- 验证所有路径；
- 验证 owner；
- 准备恢复动作。

失败时：

- 不删除 backup；
- 不删除 manifest；
- 不删除外部文件；
- 不报告卸载成功；
- 保留恢复所需的现场。

---

## 17. WP-B9：输入 digest 和 symlink

如果产品文档规定 symlink 默认拒绝，实现必须一致：

- 先 lstat；
- 默认拒绝 symlink；
- 拒绝路径逃逸；
- 拒绝目录、socket、设备等特殊文件；
- 目录项排序稳定；
- 空目录行为稳定；
- 大文件使用流式读取；
- 文件内容变化会使旧 digest 失效；
- digest 结果进入 task、plan、operation、ticket 和 receipt 绑定。

如果产品确实需要跟随 symlink，必须另设显式 policy，包含：

- 是否允许；
- 允许的根目录；
- 越界检测；
- 循环检测；
- 目标 digest 语义；
- receipt 字段；
- 测试；
- 用户文档。

不能只修改实现，不同步 policy 和测试。

---

## 18. WP-B10：handoff 和 secret

handoff 必须：

- 位于专属目录；
- 目录边界经过验证；
- 独占创建；
- 禁止覆盖；
- 不跟随 symlink；
- 临时文件写完后原子 rename；
- 创建时就是 0600；
- 写入后 fsync；
- schema 有版本、operation、run、expires_at；
- 消费后清理；
- 过期后可以安全清理；
- 不在异常、命令摘要、stderr tail、receipt 中泄露 secret。

父进程和子进程顺序：

- 父进程在 spawn 前读取必要 secret 或安全指针；
- handoff 成功落盘后才启动子进程；
- 同一 handoff 只能被一个执行者消费；
- 子进程只拿到最少必要信息；
- 失败不会留下可重放 secret。

脱敏测试必须检查真实字符串：

- secret 本身不出现；
- secret 的明显前缀和后缀不出现；
- argv、command、summary、stderr、exception text 均检查；
- 不能只断言输出是 "***" 而不检查原始泄露路径。

---

## 19. WP-A3：规则空间生长闭环

### 19.1 生长事件

至少识别以下变化：

- 新增执行表面；
- 新增 action；
- 新增 phase；
- 新增工具或 adapter；
- 新增外部副作用；
- 已有 surface 的业务 argv 变化；
- 已有 surface 的输入边界变化；
- 规则 registry 变化；
- profile 变化；
- surface 删除；
- surface 重命名；
- wrapper 替换；
- 产品从一条路径切换到另一条路径。

### 19.2 自动匹配策略

对新 surface 依次尝试：

1. 精确 identity 匹配；
2. 明确的产品 capability binding 匹配；
3. 同 integration、同 action、同 phase 的继承模板；
4. 同 side_effect 的安全模板；
5. 生成 candidate；
6. 无法证明时标记 ambiguous/gap。

不得因为“看起来相似”就自动扩大 scope、降低 tolerance 或删除 required check。

### 19.3 Candidate 内容

candidate 至少包含：

- candidate_id；
- surface_id；
- 发现来源；
- observed digest；
- 关联旧 surface；
- 建议继承的 rule/profile；
- 与旧规则的 diff；
- side_effect；
- action/phase；
- 影响等级；
- 缺少的上下文；
- 自动匹配理由；
- 需要用户确认的字段；
- 创建时间；
- registry/profile schema version；
- 状态；
- 可回滚信息。

candidate 不是权威规则。只有接受后才进入权威 registry 或有效 profile。

### 19.4 Candidate 生命周期

至少支持：

- observed；
- proposed；
- accepted；
- rejected；
- superseded；
- rolled_back；
- expired；
- retired。

接受 candidate 时：

- 生成新的规则或 profile revision；
- 保留旧 revision；
- 生成稳定 digest；
- 重新编译 effective plan；
- 让不兼容的旧 ticket 失效；
- 重新运行新 surface 的 admission smoke test。

拒绝 candidate 时：

- 保留拒绝理由；
- 防止每次扫描生成完全相同的噪声；
- 规则不得因此自动变宽；
- 后续真实变化仍可重新提议。

### 19.5 人工确认的边界

只在以下情形要求确认：

- 新规则含义无法由已有规则证明；
- scope 需要扩大；
- required check 需要新增；
- side_effect 从安全变成外部副作用；
- 现有规则与新 surface 冲突；
- 删除或替换会影响已有覆盖；
- 规则基线、容忍度或修正策略发生实质变化。

不要求确认：

- 同一规则下新增的普通实例；
- 仅 wrapper 路径变化；
- 仅机器临时路径变化；
- 已明确声明的、规则完全继承的低风险 surface；
- 每一次日常运行。

---

## 20. WP-A4：生长与低接入的联合验收 fixture

必须创建一个不依赖 JobsFlow 的最小产品 fixture，至少模拟：

- 一个已有只读动作；
- 一个已有写动作；
- 一个已有外部副作用动作；
- 一个 wrapper；
- 一个 shell -c 外壳；
- 一个插件或 adapter；
- 一个多阶段流程；
- 一个需要动态检查的 profile。

然后按以下序列执行：

### 场景 1：从零安装

1. 创建 fixture；
2. 运行 attach/install；
3. 运行 doctor；
4. 查看 discovered、governed、gap、ambiguous；
5. 执行一个只读动作；
6. 执行一个写动作；
7. 检查 ticket、operation、run、receipt；
8. 检查没有覆盖用户原有配置。

应证明：一次安装后已有入口可以开始受控运行。

### 场景 2：中途接入

1. 先运行 fixture 并生成既有产品状态；
2. 再安装 SOP Control；
3. 记录安装前后文件和配置；
4. 运行 doctor；
5. 执行已有动作；
6. 执行未知动作；
7. 检查未知动作被标为 gap/candidate，而不是静默放行。

应证明：中途接入不要求大规模重写，也不会破坏原产品。

### 场景 3：新增能力

1. 添加一个新脚本或新 tool；
2. 改变一个 action 或 phase；
3. 重新运行增量 discovery；
4. 检查生成的 surface identity；
5. 检查是否继承已有规则；
6. 若不能继承，检查 candidate；
7. 确认 candidate；
8. 重新运行新能力；
9. 检查它已经经过统一 admission；
10. 检查新规则 revision、digest 和 receipt。

应证明：新能力能进入规则空间和控制入口。

### 场景 4：规则冲突

1. 新能力声明比旧规则更宽松的 mode/tolerance；
2. 或删除 required check；
3. 或扩大 scope；
4. 运行合成或 candidate accept；
5. 检查系统拒绝或要求明确确认；
6. 检查旧规则不被静默修改。

应证明：生长不会变成无声放宽。

### 场景 5：删除和重命名

1. 删除旧 surface；
2. 将另一个 surface 重命名；
3. 重新 discovery；
4. 检查旧 surface 进入 retired；
5. 检查新 surface 不错误继承旧身份；
6. 检查旧 ticket 不能用于新 surface；
7. 检查 candidate/diff 可解释。

### 场景 6：失败和恢复

1. 注入 wrapper 写失败；
2. 注入 manifest 写失败；
3. 注入 restore 失败；
4. 注入 handoff 写入竞态；
5. 检查状态、backup、manifest、receipt；
6. 检查重新执行仍可恢复；
7. 检查没有外部文件被误删。

---

## 21. WP-A5：增量发现、噪声与成本控制

### 21.1 增量发现

生长机制不能每次动作都完整扫描整个仓库。

建议：

- 对 surface inventory 使用稳定 manifest；
- 只有内容、mtime、入口声明或依赖 digest 变化时重新分析；
- 将发现和执行分离；
- 只在安装、显式 doctor、CI 或变化检测时运行 discovery；
- 普通受控动作读取已有有效 plan，不重新发现全项目；
- 变化检测结果可缓存，但缓存必须绑定版本和根目录。

### 21.2 噪声控制

相同变化不应每次生成新 candidate。

必须：

- 用稳定 candidate identity；
- 对相同 observed digest 去重；
- 记录 rejected/suppressed 状态；
- 只有影响面变化时重新提示；
- 将 low-impact 建议与 high-impact block 区分；
- 不因为未知但无副作用的文件就阻断所有动作；
- 高影响未知 surface 必须 block 或明确 waiver。

### 21.3 运行成本验收

至少测量：

- install 扫描耗时；
- no-change 的 doctor/discovery 耗时；
- 新增一个 surface 的增量扫描耗时；
- 一个只读动作的控制调用数；
- 一个写动作的 challenge/admit/execute 调用数；
- 多阶段动作的重复 challenge 数；
- 规则未变化时是否重复编译；
- ticket 重试次数。

建议目标：

- 日常动作不触发完整项目扫描；
- 一次逻辑动作不产生无必要的多次 challenge；
- 同一 operation 的重复调用可复用稳定上下文；
- 只有规则变化、上下文变化或高影响缺口才升级；
- 业务语义检查仍由业务系统执行，不在 SOP Control 中重复执行。

如果实际测量超过目标，不要简单删除控制。先确定重复发生在哪一层，再合并或缓存。

---

## 22. 检测体系

单一的 pytest 全绿不足以证明双目标。必须同时使用四类检测。

### 22.1 静态检测

检查：

- 所有脚本和 executable；
- 所有 wrapper；
- CLI entry points；
- plugin/adapter；
- shell 和解释器调用；
- CI 和发布脚本；
- 规则 registry 和 profile；
- 发现 manifest；
- 未知 write/network/delete 入口。

静态检测输出：

- discovered；
- mapped；
- governed；
- gap；
- ambiguous；
- retired；
- 证据路径。

### 22.2 运行时探针

使用安全 fixture 验证：

- 正常入口是否进入 bridge；
- side_effect 是否正确分类；
- challenge/admit 是否发生；
- ticket 是否被消费；
- receipt 是否对应真实 argv；
- 规则检查是否发生；
- 不满足时是否阻断；
- 失败时是否没有假 receipt。

### 22.3 负向/攻击检测

至少覆盖：

- 省略 side_effect；
- 显式声明 readonly 但命令实际有副作用；
- 替换业务 argv；
- 替换 task digest；
- 替换 plan digest；
- 替换 capability binding；
- 使用旧 run_id；
- 重放 consumed ticket；
- 过期 ticket；
- 空 binding；
- shell -c 外壳；
- wrapper 伪装；
- 篡改 manifest；
- prev_backup 越界；
- symlink；
- handoff 覆盖；
- 缺少 check_id；
- profile 显式放宽；
- candidate 未接受就执行；
- 删除 surface 后使用旧规则；
- adapter_alive 伪造。

### 22.4 生长检测

至少覆盖：

- 新增 surface 被发现；
- 相同业务动作更换 wrapper 仍可匹配；
- 新 action 生成不同身份；
- 新 phase 不被错误归入旧 phase；
- 可安全继承时不生成多余 candidate；
- 不能继承时生成 candidate/gap；
- candidate 接受后规则生效；
- candidate 拒绝后不再反复刷屏；
- 规则变更后旧 plan/ticket 失效；
- 删除和重命名可解释；
- 增量 discovery 不漏报也不虚高。

---

## 23. 推荐测试命名和证据要求

测试文件按仓库已有约定放置。名称应体现行为，而不是实现细节。建议增加或核对：

### 目标 B

- test_omitted_side_effect_cannot_direct_execute
- test_all_public_entrypoints_share_side_effect_classifier
- test_classification_precedes_envelope
- test_ticket_operation_matches_receipt_operation
- test_run_id_is_stable_across_ticket_retry
- test_capability_binding_survives_cli_to_receipt
- test_consumed_ticket_is_rejected
- test_empty_binding_is_not_wildcard
- test_prev_backup_outside_rollback_root_is_rejected
- test_manifest_symlink_is_rejected
- test_install_failure_restores_original_target
- test_remove_failure_preserves_recovery_state
- test_handoff_is_exclusive_and_atomic
- test_secret_is_absent_from_all_observable_outputs
- test_missing_check_id_is_not_guessed
- test_task_input_symlink_is_rejected_by_default

### 目标 A

- test_new_surface_is_discovered
- test_surface_identity_ignores_wrapper_path
- test_surface_identity_changes_with_business_argv
- test_unchanged_surface_reuses_existing_rule
- test_ambiguous_surface_creates_candidate
- test_candidate_contains_explainable_diff
- test_candidate_accept_creates_revision
- test_candidate_reject_is_deduplicated
- test_candidate_rollback_restores_previous_rule
- test_removed_surface_becomes_retired
- test_renamed_surface_does_not_reuse_stale_ticket
- test_new_surface_is_governed_after_candidate_accept
- test_growth_does_not_silently_widen_scope
- test_no_change_does_not_rescan_full_project
- test_midstream_attach_preserves_existing_configuration
- test_unknown_high_impact_surface_is_blocked
- test_unknown_low_impact_surface_is_reported_without_global_block

每个测试至少要检查实际行为：

- 返回状态；
- 文件状态；
- ticket/receipt 字段；
- operation/run/context；
- candidate/registry revision；
- 是否真的执行或真的被阻断；
- 是否有不应有的副作用。

不能只检查一个 truthy 返回值。

---

## 24. 验收门

### 24.1 目标 A 通过条件

以下全部满足才算规则空间生长闭环通过：

- 新 surface 能被 discovery 找到；
- surface 有稳定 identity；
- 能够复用明确适用的已有规则；
- 无法证明时产生 candidate/gap；
- candidate 包含可解释 diff；
- candidate 未接受前不修改权威规则；
- 接受后产生 revision 和 digest；
- 新 surface 进入统一 admission；
- 删除、重命名和规则变更可解释；
- 旧 ticket、旧 plan 在不兼容变化后失效；
- 重复扫描不重复生成相同 candidate；
- 普通动作不触发完整项目扫描；
- 规则增长不会自动扩大审查目标。

### 24.2 目标 B 通过条件

以下全部满足才算低成本、完整覆盖、动态 SOP 执行通过：

- 一次安装或一次引导能识别项目和 harness；
- 中途接入不破坏原配置；
- attach/detach 幂等；
- 所有已发现高影响 surface 都 governed、blocked 或有明确 waiver；
- 没有未解释的 unknown direct path；
- 所有正式 CLI 和 wrapper 走统一 classifier/admission；
- ticket、operation、run、receipt 一致；
- capability_binding 完整传递；
- 动态 profile 能正确继承并只收紧；
- 缺少 check_id 不会被猜测；
- manifest、backup、handoff、symlink 安全；
- secret 不泄露；
- 运行成本有测量且没有无必要重复调用；
- 业务语义检查仍由业务系统负责；
- SOP Control 只保证声明的检查被正确经过。

### 24.3 联合通过条件

目标 A 和目标 B 必须在同一个 fixture 中联合通过：

- 新增 surface 被发现；
- 它被正确匹配或进入 candidate；
- 接受后自动得到有效 profile/plan；
- 通过统一 bridge 执行；
- ticket operation、receipt operation 和 run 一致；
- 输入或规则改变后旧 ticket 失效；
- 不需要手动修改多个业务文件；
- 没有重复全量扫描和重复语义审计。

---

## 25. 最终执行命令

先运行定向测试。路径以仓库实际结构为准：

    .venv/bin/pytest -q tests/harness/test_p1_*.py tests/harness/test_effective_plan.py tests/harness/test_task_profile_binding.py tests/harness/test_bridge.py tests/harness/test_canonical_admission.py

然后运行目标 A/B 新增 fixture 和定向测试。

    .venv/bin/pytest -q tests/harness -k "growth or surface or coverage or bootstrap or bridge or profile or ticket"

全量测试：

    .venv/bin/pytest -q

coverage：

    .venv/bin/pytest -q --cov --cov-branch --cov-report=term-missing

静态检查：

    .venv/bin/ruff check sopcontrol plugins tests
    git diff --check

项目门禁：

    .venv/bin/python -m sopcontrol.cli gate .
    .venv/bin/python -m sopcontrol.cli project check .
    .venv/bin/python -m sopcontrol.cli chronicle check .

如果项目规定使用 sopctl，则使用等价的正式命令并在报告写出实际命令。

注意：

- coverage 只在实现稳定后运行一次；
- 被中断的 coverage 不算通过；
- 不得降低 fail_under；
- 不得把 mock harness 报告成真实外部 harness；
- gate 可能更新控制器证据，必须使用 sopctl 规定方式；
- 任何命令失败都要报告第一个失败原因。

---

## 26. 不允许的伪完成

下列行为都不算完成：

- 关闭 enforce；
- 通过 tickets_enabled=off 绕过 ticket；
- 只修内部函数，不修正式 CLI；
- side_effect 缺失时默认 readonly；
- 空 binding 当作通配；
- 每次重试自动生成新 run_id；
- 从其他字段猜 check_id；
- 用 Pydantic 默认值覆盖未声明 profile 字段；
- candidate 尚未接受就直接写入权威 registry；
- 未覆盖 surface 被标记为 governed；
- 仅因为 scanner 找到文件就报告 100% coverage；
- 只测试 Claude，不测试正式 CLI 或其他已声明 adapter；
- 用普通 write_text 覆盖 handoff；
- 接受 manifest 任意绝对路径；
- 失败时删除 backup 或外部 sentinel；
- 只做正向测试，不做负向测试；
- 删除或放宽旧测试；
- 降低 coverage 门槛；
- 把中断的命令报告为通过；
- 把业务语义审计塞进 SOP Control；
- 为了“独立”而强制每个动作人工批准；
- 未经授权 commit、push、发布或改动业务产品。

---

## 27. 最终报告模板

外部模型完成后必须按以下格式交付。

### A. 总结

- 目标 A 状态：完成 / 部分完成 / 阻塞
- 目标 B 状态：完成 / 部分完成 / 阻塞
- 联合闭环状态：
- 按本手册完成度：
- 当前仍不能宣称的内容：
- 与执行前估计的差异：

### B. 距离评估

分别给出证据支持的结论：

- 规则空间基础：
- 新 surface 自动发现：
- candidate 生命周期：
- 规则接受和回滚：
- 全入口覆盖：
- 一次安装：
- 中途接入：
- 动态 profile：
- ticket/operation/run 一致性：
- 运行成本：
- 发布级可靠性：

不能只给一个总分，必须解释每个维度的证据。

### C. 修改清单

按 WP-A1 至 WP-B10 列出：

- 是否执行；
- 修改文件；
- 生产函数或调用链；
- 新增测试；
- 行为变化；
- 是否影响 CLI/API；
- 是否有兼容性风险。

### D. 双目标闭环证据

至少写出联合 fixture 的完整过程：

- 初始 surface 数量；
- 初始 governed/gap/ambiguous 数量；
- 新增 surface；
- discovery 结果；
- candidate 结果；
- candidate accept/reject 结果；
- 新 revision 和 digest；
- 新 surface 的 challenge/admit/receipt；
- 删除或重命名结果；
- 规则变化后旧 ticket 的结果；
- 最终 coverage 数量；
- 实际控制调用成本。

### E. 测试证据

列出实际命令和结果：

- 目标 B 定向测试；
- 目标 A 生长测试；
- 联合 fixture；
- 全量测试；
- skipped 数量；
- failure 数量；
- line coverage；
- branch coverage；
- ruff；
- git diff --check；
- gate；
- project check；
- chronicle check。

### F. Git 状态

- 当前分支；
- 当前 HEAD；
- 工作区状态；
- 本次修改文件；
- 是否 commit；
- 是否 push；
- 若未执行，写明原因。

### G. 剩余风险

只列真实风险，例如：

- Windows 或其他平台没有真实验证；
- 某个外部 harness 只做了 mock；
- 超大仓库增量扫描性能；
- 旧版本 registry 需要迁移；
- cooperating-operator 不等于沙箱级不可绕过；
- 某类动态加载入口无法静态发现；
- 需要业务产品方确认 candidate 的规则语义。

---

## 28. 最终判断标准

本手册真正要证明的不是“规则更多了”，也不是“审计次数更多了”，而是以下事实：

- 产品生长时，SOP Control 能看见变化；
- 看见变化后，优先复用已有规则；
- 无法复用时，给出最小、清楚、可回滚的候选；
- 候选被确认后，新能力自动进入控制链；
- 产品运行时，所有重要动作确实经过控制；
- 动态 SOP 按用户和系统声明执行，而不是被模型自行解释；
- 控制不会因为不同模型、不同 wrapper 或不同 CLI 产生漂移；
- 用户不需要长期维护大量接入代码；
- 日常运行不会因为控制机制产生不必要的重复调用；
- SOP Control 不越界替业务产品判断语义；
- 失败会停在可恢复状态；
- 每一个“通过”都可以由实际测试和运行证据证明。

如果只完成了静态扫描、规则 registry 或 ticket 机制，而没有完成“新增能力到新规则再到实际受控执行”的联合 fixture，就不能称为两个目标已经闭环。
