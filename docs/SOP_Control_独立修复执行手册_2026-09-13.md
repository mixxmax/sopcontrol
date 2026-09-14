# SOP Control 独立修复执行手册

## ——交给从未接触过本项目的外部模型执行

- 版本：v1.0
- 日期：2026-09-13
- 执行范围：仅修复 SOP Control 本身
- 业务范围：不修改 JobsFlow、JobsDB、抓取逻辑、材料生成逻辑或业务语义 lint
- 目标：让 SOP Control 可靠地确保“系统按照系统设计运行”，并能够承载复杂而变化的控制规则，而不是替业务系统判断业务内容

---

## 0. 给执行模型的第一条指令

你第一次接触本仓库。不要把任何旧报告中的“已完成”“全部通过”“评分 8.8”当成事实，也不要因为测试数量很多就直接宣布完成。

你必须自行：

1. 读懂本仓库的项目规则、目录、调用链和测试；
2. 先用最小实验复现本手册列出的缺口；
3. 只修复已经确认的缺口及其必要的回归问题；
4. 为每个缺口添加能够证明“原来会失败、现在被阻断或正确完成”的测试；
5. 运行定向测试、全量测试、静态检查和项目门禁；
6. 最后按本手册第 16 节的格式报告，逐项给出文件、测试名称和命令证据。

不要通过删除规则、关闭 enforce、放宽断言、跳过测试、伪造 receipt、修改测试预期或降低 coverage 门槛来“修复”问题。

---

## 1. 产品定位与本次修复目标

### 1.1 SOP Control 应该负责什么

SOP Control 是一个控制面。它负责约束工作流是否经过系统规定的入口、阶段、检查和状态转换，负责把动态控制规则编译成可执行的门，负责识别上下文是否一致，负责在无法证明安全或合规时停止。

它至少应该能够控制：

- 哪个动作可以执行；
- 当前动作是否处于正确阶段；
- 当前任务、运行、操作者和计划是否匹配；
- 必须经过哪些检查；
- 检查结果是否真实存在且来自规定入口；
- 动态规则在不同层级合成后是否仍然只收紧、不被意外放宽；
- capability ticket 是否绑定当前实际操作；
- 运行回执、摘要和状态是否与实际操作一致；
- 安装、卸载、桥接和回滚是否不会留下错误或越权状态。

### 1.2 SOP Control 不应该负责什么

SOP Control 不负责替业务系统做业务判断。例如：

- JD 是否适合某种岗位；
- 材料是否符合某项业务事实；
- 语言是否自然；
- 某个业务术语是否准确；
- 内容是否完成了 LLMO；
- 业务审计应该检查哪些具体语义。

这些由业务产品及其检查引擎负责。SOP Control 的职责是：如果业务系统声明某项检查是必需的，SOP Control 必须确保该检查在正确阶段、由正确入口、以正确规则完成；但 SOP Control 不应擅自创造一套自己的业务审计风格。

### 1.3 本次修复的成功定义

完成后必须同时满足：

- 任何受控写动作都不能因为漏填 side effect、漏传绑定或走另一条 CLI 路径而绕过控制；
- 票据、操作、运行、阶段和回执使用同一套规范化上下文；
- 动态规则支持“未声明字段继承、显式字段收紧”，不能因为模型默认值而把继承误判为放宽；
- 缺少明确检查身份时不得由系统猜测；
- 文件备份、恢复、卸载和 handoff 失败时保持可恢复且不越权；
- symlink、外部备份路径、篡改 manifest 等路径默认拒绝；
- 每个修复都有负向测试，测试证明的是控制行为，而不是只证明函数返回了某个值；
- 既有功能不被无关改造破坏。

---

## 2. 先建立项目地图

### 2.1 必须先阅读的文件

按以下顺序阅读。文件不存在时记录为“缺失”，不要自行假设内容：

1. AGENTS.md
2. DESIGN.md
3. PLAYBOOK.md
4. SKILL.md 或仓库中与 SOP Control 相关的执行说明
5. pyproject.toml
6. 本手册
7. 现有 docs/ 下的闭环、安装、桥接、动态规则和验收文档
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
9. 相关测试：
   - tests/harness/test_effective_plan.py
   - tests/harness/test_task_profile_binding.py
   - tests/harness/test_bridge.py
   - tests/harness/test_canonical_admission.py
   - tests/harness/test_p1_*.py
   - tests/ 中涉及 profile、ticket、task digest、scaffold、handoff、control result 的测试

不要一次性把大型日志、完整 JSONL、完整账本或所有测试输出塞入上下文。先用定向搜索和统计定位。

### 2.2 推荐的定向搜索

    pwd
    rg --files -g 'AGENTS.md' -g 'DESIGN.md' -g 'PLAYBOOK.md' -g 'SKILL.md' -g 'pyproject.toml' -g 'sopcontrol/**' -g 'tests/**' -g 'docs/**'
    rg -n "install_scaffold|remove_wrapper|run_bridge|canonical|operation_id|run_id|capability_binding|side_effect|prev_backup|check_id|checked_dimensions|symlink|handoff|_merge_all_fields|model_fields_set" sopcontrol tests
    git status --short --branch
    git log -1 --oneline
    git diff --stat
    git diff --check

### 2.3 修改前的保护要求

开始改代码前，先保存以下信息到自己的工作记录中：

- 当前分支；
- 当前 HEAD；
- 工作区是否已有修改；
- 与本手册无关的已有修改有哪些；
- 当前测试入口；
- 当前 coverage 门槛；
- 当前 gate、project check、chronicle check 的用法。

不要使用以下命令清除用户已有工作：

- git reset --hard
- git checkout --
- git clean
- 删除整个仓库或整个临时目录之外的广泛路径

如果工作区本来就有修改，只修改本手册范围内的文件；不要覆盖或重写无关 diff。

---

## 3. SOP Control 的控制边界

### 3.1 正确的责任链

应当形成下面这条责任链：

    业务系统声明动作和必需检查
      -> SOP Control 读取声明并编译有效控制规则
      -> SOP Control 检查当前 task/run/actor/phase/plan 上下文
      -> SOP Control 通过受控入口进行 challenge/admit
      -> 业务系统执行自己的实际动作和语义检查
      -> SOP Control 验证检查确实发生且证据与上下文匹配
      -> SOP Control 记录或返回控制结果
      -> 只有满足门条件的后续动作才能继续

如果业务系统没有执行语义检查，SOP Control 应该阻断“需要该检查的下一阶段”；不应自己伪造语义检查结果，也不应把“有一段理由”当作独立审计通过。

### 3.2 不要把控制面变成业务审计器

本次修复不得加入以下类型的硬编码：

- 固定某一种业务审计风格；
- 固定要求所有材料都严格服从某个事实基线；
- 固定把合理的轻微夸大都判定为错误；
- 固定设置一套不适用于其他产品的容忍度；
- 让模型通过自由文本理由自行宣布“独立审计通过”。

动态规则能力的目标是让用户或业务系统明确声明检查范围、容忍度、修正策略、最大轮数、停止条件和必要证据，然后由 SOP Control 稳定执行这些声明。SOP Control 不替用户重新定义审计目标。

---

## 4. 已知缺口清单

以下是本手册要求优先复现和修复的缺口。代码行号可能随版本变化，必须以函数名和实际调用链为准。

| 编号 | 缺口 | 风险 | 主要区域 |
| --- | --- | --- | --- |
| R-01 | scaffold 安装路径在 side_effect 省略时可能直接执行已知网络命令 | 写动作绕过 ticket 和 handoff | bridge_scaffold.py、bridge.py、cli.py |
| R-02 | remove_wrapper 对 manifest 中的 prev_backup 缺少可信路径约束 | 篡改 manifest 后可能删除仓库外文件 | bridge.py |
| R-03 | 动态 profile 合成使用已默认化的 Pydantic 模型 | 任务层省略字段被误判为显式放宽 | control_profile.py |
| R-04 | bridge 先生成 envelope，后做自动 side-effect 分类 | ticket operation 与实际 receipt operation 不一致 | bridge.py |
| R-05 | ControlResult 缺少 check_id 时自动从 checked_dimensions 猜测 | 未执行明确检查也可能被伪造成有效结果 | control_result.py |
| R-06 | 文档约定 symlink 默认拒绝，但输入摘要实现会跟随仓库内 symlink | 输入边界与安全策略不一致 | task.py |
| R-07 | install/remove 失败时未形成完整事务 | manifest、wrapper、backup 可能处于不一致状态 | bridge.py、bridge_scaffold.py |
| R-08 | handoff 文件使用普通写入，不保证独占创建和原子落盘 | 竞态、覆盖、symlink 攻击或 secret 泄露 | bridge.py |
| R-09 | capability_binding 没有完整贯穿 run_bridge、CLI、scaffold、ticket 和 receipt | 动态规则的绑定上下文无法稳定复现 | bridge.py、cli.py、tickets.py |

如果当前代码已经修复了某项，仍然要用回归测试证明；不要仅凭函数名字或旧报告把该项标记为完成。

---

## 5. 执行总流程

外部模型必须按照以下顺序工作：

1. 建立项目地图和工作区基线；
2. 为每个 R 编号写最小复现实验；
3. 先修复规范化和边界函数，再修复调用链；
4. 每修复一项立即运行对应定向测试；
5. 所有定向测试通过后再运行全量测试；
6. 最后运行 coverage、ruff、diff check 和 SOP 门禁；
7. 对任何未完成项或环境限制诚实报告；
8. 不自动 commit 或 push，除非发起任务的用户另行明确授权。

不要一开始就运行一轮很慢的全量 coverage。先用定向测试缩短反馈回路；coverage 只在代码稳定后运行一次。若命令被中断，必须报告“未完成”，不能报告为通过。

---

## 6. WP-0：先写复现实验，不要直接改实现

### 6.1 R-01：side_effect 省略导致直接执行

使用临时目录和无网络副作用的协作子进程。不要真的访问网络。

复现目标：

- 调用 install_scaffold 或其正式 CLI 路径；
- command 使用一个项目实际会被识别为网络/外部副作用的命令，例如 curl --version；
- side_effect 省略或为空；
- 记录当前是否出现直接执行；
- 记录是否产生 handoff、challenge、admit 和 receipt。

失败判定：

- side_effect 为空仍直接执行；
- 没有 ticket 或 admit 记录；
- 只有某个内部函数阻断，但正式 CLI 路径仍可执行。

修复后应当是：

- 未明确且未获准的副作用默认拒绝；
- 不能因为命令没有真正访问网络就把 curl 这样的外部工具当作安全本地读操作；
- 所有正式入口都使用同一套分类和 admission；
- 测试不能只调用内部 helper，必须覆盖真实 CLI 或公开 API。

### 6.2 R-02：篡改 prev_backup 访问外部路径

复现步骤：

1. 在临时目录建立一个 sentinel 文件；
2. 生成或安装一个正常 wrapper 和 manifest；
3. 将 manifest 中 prev_backup 改为 sentinel 的路径；
4. 调用正式 remove_wrapper；
5. 检查返回结果、sentinel 是否仍存在、原 wrapper 和 manifest 是否仍可恢复。

失败判定：

- remove_wrapper 接受外部 prev_backup；
- 删除了 sentinel；
- 在发现 manifest 不可信后仍继续 unlink 或 restore；
- 失败后没有保留可恢复证据。

修复后应当是：

- 任何 manifest 路径字段都先 schema 校验、规范化和 containment 校验；
- prev_backup 只能位于 SOP Control 自己声明的回滚目录；
- 外部路径、绝对路径、路径逃逸、symlink、目录、特殊文件和不匹配 owner 均拒绝；
- 在全部校验完成前不得写文件、删除文件或改变权限。

### 6.3 R-03：部分动态 profile 的继承误判

构造一个 base profile，其中若干字段不是默认值，例如：

- 非默认 mode；
- 非默认 tolerance；
- 非默认 budget；
- 非默认 repair policy；
- 非默认 stop policy；
- 非默认 expires_at；
- 非默认 baseline 或 scope。

再构造一个 task layer，只声明其中一个字段，其他字段完全省略。

复现目标：

- task layer 的省略字段应继承 base；
- 不得被 Pydantic 默认值覆盖；
- task layer 明确写出更宽松的值必须被拒绝；
- task layer 明确写出更严格的值才可被接受；
- 未声明和显式声明默认值必须能够区分。

失败判定：

- 省略字段被当成默认值；
- 合成因为 base 非默认、task 默认而报“放宽”；
- 仅通过对所有字段都填满默认值来绕过问题。

### 6.4 R-04：自动分类发生在 envelope 之后

使用 run_bridge 的正式路径，省略 side_effect，并使用可安全结束的测试 wrapper。

记录：

- 原始 argv；
- 规范化调用；
- 自动分类结果；
- challenge 的 operation_id；
- ticket 的 operation；
- admit 的 operation；
- 最终 receipt 的 operation_id；
- run_id；
- plan digest、task digest 和 capability binding。

失败判定：

- 分类前生成 envelope，分类后重新计算 operation；
- challenge/ticket 与 receipt 的 operation 不一致；
- receipt 仅因为“命令成功”就被标为 pass；
- run_id 在 challenge 和重试之间无稳定关系。

### 6.5 R-05：缺失 check_id 被猜测

构造 ControlResult：

- check_id 缺失或为空；
- checked_dimensions 非空；
- 其他字段看起来足以通过。

失败判定：

- 系统自动选择 checked_dimensions[0] 作为 check_id；
- 仅凭维度名称生成 idempotency key；
- 没有明确的检查身份仍能被后续阶段接受。

修复后应当是：

- check_id 是显式身份，不允许猜测；
- 缺失、空白、非法格式均拒绝或返回无法证明；
- checked_dimensions 只能描述检查覆盖面，不能替代 check_id。

### 6.6 R-06：输入摘要跟随 symlink

在临时任务目录内创建：

- 一个普通文件；
- 一个指向任务目录外文件的 symlink；
- 一个指向任务目录内文件的 symlink；
- 需要时再创建目录 symlink 或特殊文件。

复现目标：

- 对照文档和安全策略确认默认行为；
- 检查摘要是否读取了 symlink 目标内容；
- 检查 digest 是否把 link 本身和目标内容混为一谈。

修复后默认行为：

- 先用 lstat 判断目录项类型；
- 默认拒绝 symlink，不因为目标位于任务目录内就自动跟随；
- 若未来支持跟随，必须是独立、显式、可绑定、可测试的策略，不能悄悄改变默认语义。

### 6.7 R-07：安装和卸载失败事务

为以下步骤注入失败：

- wrapper 临时文件写入；
- wrapper 原子替换；
- manifest 临时文件写入；
- manifest 原子替换；
- backup；
- restore；
- chmod 或 fsync。

每次失败都检查：

- 原目标是否保持原内容；
- 新 wrapper 是否不会半写；
- manifest 是否仍指向真实 backup；
- backup 是否存在且权限正确；
- 重试或 remove 是否仍可安全进行；
- 是否产生半成品 handoff 或 receipt。

### 6.8 R-08：handoff 写入竞态

用两个并发或快速重复调用模拟：

- 同名 handoff；
- 已存在的 handoff；
- handoff 路径上的 symlink；
- 写入中途异常；
- 进程在写入后、消费前退出。

必须检查：

- 不会覆盖已有 handoff；
- 不会通过 symlink 写到外部；
- 内容不是半截 JSON；
- 权限从创建开始就是 0600；
- 成功消费后清理；
- 失败、过期和异常退出都有清理或可恢复路径；
- secret 和 secret 的片段不会出现在 receipt、异常摘要或命令回显中。

---

## 7. WP-1：统一 side-effect 分类与受控入口

### 7.1 设计要求

实现一个单一的、可测试的 side-effect classifier，并让以下路径复用它：

- install_wrapper；
- install_scaffold；
- bridge run；
- bridge challenge；
- bridge admit；
- 正式 CLI；
- scaffold 生成的 wrapper；
- 任何会把业务命令交给子进程的入口。

不要在某个入口加一个局部 if，然后让另一个入口仍然使用旧逻辑。

### 7.2 分类原则

分类输入必须至少考虑：

- 原始 argv；
- 去除 wrapper、解释器、shell 外壳后的业务 argv；
- 显式 side_effect；
- integration；
- 当前 action；
- task、plan 和 capability binding；
- 是否为只读本地操作；
- 是否包含 curl、wget、ssh、scp、rsync、浏览器、数据库客户端、远程 URL、远程 host 或其他外部交互信号。

建议规则：

- 已知外部工具即使当前参数是 --version，也不能仅凭“此次不会联网”自动视为安全；
- 显式声明的 side_effect 必须与自动分类兼容；
- 显式声明比自动分类更宽松时拒绝；
- 无法可靠分类时返回 unknown 或直接拒绝，不能默认 readonly；
- 只有安全、明确、可证明的本地只读命令才允许 direct；
- side effect 的最终值必须在 canonical envelope 构造之前确定。

### 7.3 必须保持的操作一致性

同一次操作中：

- challenge.operation_id = ticket.operation；
- admit 使用的 operation_id = ticket.operation；
- receipt.operation_id = ticket.operation；
- ticket、admit 和 receipt 的 run_id 一致；
- 计划、任务摘要、阶段和 capability binding 一致；
- 任何影响上述值的分类变化都必须导致旧 ticket 失效，而不是复用旧 ticket。

### 7.4 测试要求

至少增加或完善以下类别的测试：

- omitted side effect 识别 curl/wget/ssh 等外部工具；
- 显式 readonly 与自动副作用冲突时拒绝；
- wrapper、shell -c、python -m、解释器路径不会污染业务 argv；
- classify-before-envelope；
- challenge、admit、receipt operation 一致；
- 正式 CLI 与内部 API 得出相同分类；
- unknown 不会静默降级为 safe；
- 失败路径不产生伪造成功 receipt。

---

## 8. WP-2：manifest、备份和安装/卸载事务

### 8.1 Manifest 是不可信输入

manifest 不是天然可信。无论它来自本程序、旧版本、用户编辑还是恢复文件，都必须在使用前重新验证。

至少校验：

- JSON/schema 结构；
- integration 和 wrapper owner；
- files 列表；
- 每个 files 路径是否位于项目允许目录；
- prev_backup 是否位于专属回滚目录；
- 所有路径的 resolve 和 containment；
- lstat 类型；
- 是否为 symlink；
- 是否为普通文件；
- 是否为目录、socket、设备或其他特殊文件；
- 文件是否存在以及权限是否符合预期；
- manifest 的版本、digest 和关联 task/installation id。

### 8.2 路径边界

推荐的边界：

- 自有 wrapper 只能位于项目内约定的 .sopcontrol-local/bin；
- 自有 rollback backup 只能位于项目内约定的 .sopcontrol-local/bridge-rollback；
- 不允许 prev_backup 指向任意绝对路径；
- 不允许通过 ../ 逃逸；
- 不允许通过 symlink 逃逸；
- 不允许删除一个不属于当前安装记录的目标；
- 目录、特殊文件和未能确认 owner 的文件一律拒绝。

所有校验必须发生在任何 unlink、rename、chmod、truncate 或写入之前。

### 8.3 安装事务

建议事务顺序：

1. 读取旧状态并完整校验；
2. 在专属目录创建 backup；
3. 将新 wrapper 写入同目录临时文件；
4. 对临时文件设置 0600 或最终所需权限；
5. fsync 临时文件；
6. 原子 rename 到目标；
7. 写 manifest 临时文件；
8. fsync manifest；
9. 原子 rename manifest；
10. 必要时 fsync 父目录；
11. 只有全部步骤成功才返回安装成功。

任一步失败：

- 尽量恢复旧目标；
- 保留可识别的 backup；
- 删除不完整的临时文件；
- 不提交一个声称成功的 manifest；
- 不留下“新 wrapper + 旧 manifest”这种不可解释状态；
- 若恢复本身失败，返回明确的 recovery_required，并保留现场，不能静默吞错。

### 8.4 卸载事务

建议顺序：

1. 读取 manifest；
2. 完整验证所有路径和 owner；
3. 准备恢复动作；
4. 将当前自有 wrapper 移入临时位置或安全备份；
5. 恢复原文件；
6. fsync；
7. 删除本次安装生成的 manifest 和 backup；
8. 全部成功后返回卸载成功。

在校验失败或恢复失败时：

- 不删除外部路径；
- 不删除原 backup；
- 不删除仍需要恢复的 manifest；
- 不声称已卸载；
- 允许用户根据 recovery_required 继续修复。

### 8.5 测试要求

至少覆盖：

- 正常安装、重复安装、正常卸载；
- manifest 逃逸；
- prev_backup 外部路径；
- prev_backup symlink；
- files 外部路径；
- files 目录和特殊文件；
- manifest schema 损坏；
- backup 缺失；
- 每个写入步骤失败；
- restore 失败；
- 安装中断后重新运行；
- 卸载中断后重新运行；
- 失败后没有越权删除；
- 只删除当前安装拥有的文件。

---

## 9. WP-3：动态规则的部分层合成

### 9.1 核心问题

动态规则通常分为：

- Base profile；
- Task profile；
- Run profile；
- Actor profile。

关键区别是：

- 字段没有出现，表示继承；
- 字段明确出现，才表示该层提出了约束；
- 字段明确写出默认值，不等于字段没有出现；
- nested object 没有出现，也必须保持“未声明”状态。

不能把每层先解析成一个所有字段都有默认值的完整 ControlProfile，再根据值判断是否放宽。这样会丢失“用户是否真的声明过这个字段”的信息。

### 9.2 推荐实现

可以选择以下方式之一：

- 使用单独的 partial/presence model；
- 使用 Pydantic 的 model_fields_set；
- 使用显式 presence map；
- 使用原始层配置和规范化字段集合同时保存。

无论选哪一种，必须能区分：

- absent；
- explicit null；
- explicit default；
- explicit non-default；
- nested field absent；
- nested field present。

### 9.3 合成语义

默认只允许收紧：

- checks：只能增加必要检查，不能删除；
- required checks 与 excluded checks：冲突时拒绝；
- mode：只能从宽松向严格；
- tolerance：只能从宽松向严格；
- budget：只取显式层中的最小值；
- max rounds：只取显式层中的最小值；
- repair policy：只能减少修复权限或减少可修改范围；
- stop policy：只能增加停止条件，不能移除；
- baseline：省略则继承，显式改变必须拒绝或形成新的明确 revision；
- scope：省略则继承，不能扩大到项目范围之外；
- expires_at：取更早的有效时间；
- actor constraints：只能收紧；
- unknown fields：拒绝；
- required 新增：如果该层语义不允许新增，必须明确拒绝，而不是静默接受。

如果某字段没有在当前层出现，它不参与“放宽比较”，直接继承上一层有效值。

### 9.4 Digest 要包含什么

有效 profile digest 至少要稳定包含：

- 规范化后的 effective profile；
- 各层的 profile digest；
- 各层实际声明过的字段集合；
- task id、run id、actor snapshot；
- baseline 和 scope；
- expires_at；
- mode、tolerance、budget、repair、stop；
- 必要的 profile schema/version。

digest 输入不能包含：

- 字典未排序造成的随机顺序；
- secret；
- 临时文件路径；
- 当前时间，除非它是已规范化并明确进入规则的 expires_at；
- wrapper 路径或 shell 外壳；
- 未声明字段被自动填入的默认值。

### 9.5 测试矩阵

至少测试：

- base 非默认 + task 字段省略：继承成功；
- base 非默认 + task 显式相同值：按显式约束处理；
- base 严格 + task 显式放宽：拒绝；
- base 宽松 + task 显式收紧：接受；
- nested object 部分声明：未声明子字段继承；
- budget 和 rounds 的边界值；
- baseline 改变；
- scope 扩大；
- unknown field；
- required/excluded 冲突；
- profile digest 对声明存在/不存在敏感；
- 相同规范化输入 digest 稳定；
- actor 能力变化导致旧计划或旧结果失配。

---

## 10. WP-4：canonical invocation、ticket 和运行绑定

### 10.1 规范化流水线

所有受控执行必须遵循同一顺序：

    原始 argv
      -> 去除 wrapper、解释器和 shell 外壳
      -> 得到业务 argv
      -> 自动识别 side effect
      -> 合并并验证显式 side effect
      -> 计算输入摘要
      -> 读取 task、phase、plan、capability binding
      -> 生成 canonical invocation
      -> 生成 operation_id
      -> 生成稳定 run_id
      -> challenge / ticket / admit
      -> 执行
      -> receipt

关键要求：

- 最终 side effect 在 envelope 之前确定；
- canonical invocation 只包含真正代表业务动作的 token；
- 不把 wrapper 路径、$0、解释器路径、时间、attempt、ticket secret 放入业务指纹；
- operation_id 可以绑定 task、phase、plan、side effect、input digest 和 capability binding；
- run_id 在 challenge 与实际重试之间稳定；
- 重放、换参数、换 task、换阶段、换计划或换 capability binding 必须失配。

### 10.2 capability_binding 的传递

如果系统支持 capability_binding，必须从入口到结果完整传递：

- run_bridge API；
- CLI；
- scaffold 生成的 wrapper；
- challenge；
- admit；
- ticket；
- handoff；
- receipt；
- 必要时 task/plan profile。

不得出现“核心函数有字段，但 CLI 没有参数”或“票据里有字段，receipt 丢失字段”的断链。

缺少必需绑定时：

- 明确返回 missing_context 或 unknown；
- 不应生成一个无绑定的万能 ticket；
- 不应让调用方通过二次自动生成不同 run_id 来永远挑战新票据。

### 10.3 ticket 要求

ticket 必须：

- 绑定 operation；
- 绑定 run；
- 绑定允许的 action/phase；
- 绑定 task、plan、profile 或必要 digest；
- 一次性消费；
- 过期后拒绝；
- secret 不进入日志和 receipt；
- consumed 状态不可通过普通参数绕过；
- allowed_actions 不得被空集合解释成“允许任何动作”；
- 空 binding 不得解释成通配；
- challenge、redeem、admit 使用相同的 canonical payload。

任何内部快捷路径都必须通过同一 admission，不得保留“业务上看似相同但不需要票据”的旁路。

---

## 11. WP-5：ControlResult 必须使用显式检查身份

### 11.1 规则

check_id 是检查的身份，不是展示字段。

必须删除或禁止以下行为：

- 从 checked_dimensions[0] 自动填充 check_id；
- 从自由文本 reason 推导 check_id；
- 从 action、phase 或其他字段猜测 check_id；
- 仅凭 checked_dimensions 生成可被后续阶段接受的结果。

允许的行为：

- check_id 明确存在且格式有效；
- check_id 在当前 profile/registry 中已声明；
- check_id 与 task、phase、plan 和 actor 上下文匹配；
- 结果中的 checked_dimensions 作为补充证据；
- 缺失时返回拒绝、unknown 或 not_run，具体取决于当前门语义，但不得伪造成 pass。

### 11.2 兼容旧数据

如果仓库已有旧 schema：

- 可以提供只读迁移或诊断；
- 可以把旧结果标为 legacy/unverifiable；
- 不得在 enforce 路径上自动猜测身份来放行；
- 迁移规则必须有测试和版本标识。

---

## 12. WP-6：输入摘要与 symlink 策略

### 12.1 默认安全策略

对于 task input digest：

- 使用 lstat 而不是先 resolve 再读取；
- 默认拒绝 symlink；
- 拒绝路径逃逸；
- 拒绝目录、socket、设备等特殊文件；
- 文件顺序稳定排序；
- 空目录行为稳定；
- 规范化相对路径；
- 对超大文件使用流式读取；
- 记录足够的失败原因，但不把敏感内容放入日志。

### 12.2 不要让文档与实现分裂

如果文档写的是“symlink 默认拒绝”，实现必须拒绝；如果产品确实需要跟随 symlink，则必须同时修改：

- policy 定义；
- digest 规范；
- 越界检测；
- 循环检测；
- receipt；
- 测试；
- 用户文档。

不能只修改其中一处。

### 12.3 digest 绑定

输入摘要应进入：

- task 提交记录；
- profile/task gate；
- canonical operation；
- ticket binding；
- receipt；
- 必要的重试和复核判断。

内容改变但路径不变时，旧 digest 必须失效。

---

## 13. WP-7：handoff 与 secret 的安全写入

### 13.1 写入要求

handoff 文件必须：

- 在专属目录内；
- 目录边界经过验证；
- 使用独占创建，禁止覆盖已有文件；
- 不跟随目标 symlink；
- 写入临时文件后原子 rename，或使用等价安全机制；
- 创建时即为 0600；
- 写入后 fsync；
- 内容有明确 schema、版本、operation、run、expires_at；
- 不把 secret 写入普通日志；
- 消费后立即删除；
- 过期 handoff 可安全清理。

### 13.2 父子进程顺序

父进程应在 spawn 前读取必要 secret 或安全指针，子进程只拿到最少必要信息。

必须避免：

- 子进程启动后才依赖不稳定的 handoff；
- handoff 还没写完就启动子进程；
- 同一个 handoff 被两个执行者消费；
- 通过普通 env 把 secret 打到错误日志；
- exception、command summary、tail、receipt 中出现 secret 或其明显片段。

### 13.3 脱敏测试

测试必须检查实际输出文本：

- secret 本身不出现；
- secret 的前缀、后缀和常见片段不出现；
- argv、command、summary、stderr tail、exception text 均检查；
- 不允许只断言字符串等于 "***"，却没有检查真实泄露路径；
- 脱敏不应破坏普通命令参数的可诊断性。

---

## 14. WP-8：测试纪律

### 14.1 每个修复必须有三类证据

每个缺口至少需要：

1. 原问题的最小复现测试；
2. 修复后的正向通过测试；
3. 邻近边界的负向测试。

例如 prev_backup 不仅要测合法 backup 可以恢复，还要测：

- 外部路径拒绝；
- 路径逃逸拒绝；
- symlink 拒绝；
- 失败后不删除 sentinel；
- 失败后可重试或保留 recovery_required。

### 14.2 测试不能通过这些方式“变绿”

禁止：

- 删除旧测试；
- 把 assert 改成宽泛的 truthy；
- 只检查 return code，不检查文件状态；
- 只调用内部 helper，不走正式 CLI/公开入口；
- 关闭 enforce 或 ticket；
- 使用固定的全局真实目录；
- 依赖网络；
- 将异常吞掉后返回 pass；
- 在测试中硬编码“当前实现的错误行为”。

### 14.3 运行时成本控制

因为 SOP Control 的目标之一是减少不必要的模型耗时和 token 消耗：

- 定向测试优先；
- 不要对每个小改动重复运行 5 分钟以上的全量套件；
- 不要重复运行同一轮 coverage；
- 票据流程的测试应验证链路，但不要为每个纯函数重复启动真实模型；
- 外部工具调用使用假的、可控的协作进程；
- 只在最终阶段运行一次完整验收；
- 如果全量检查异常缓慢，记录耗时和阻塞点，不要通过跳过它来宣布完成。

---

## 15. 验收命令

执行前确认虚拟环境和项目入口。若仓库实际入口不同，以 pyproject.toml 和项目说明为准。

### 15.1 定向测试

    .venv/bin/pytest -q tests/harness/test_p1_*.py tests/harness/test_effective_plan.py tests/harness/test_task_profile_binding.py tests/harness/test_bridge.py tests/harness/test_canonical_admission.py

根据实际新增测试补充文件，但不要删除已有测试。

### 15.2 全量测试

    .venv/bin/pytest -q

如果失败，必须报告第一个失败用例、完整原因和是否为本次改动引入；不能只报告总数。

### 15.3 覆盖率

    .venv/bin/pytest -q --cov --cov-branch --cov-report=term-missing

覆盖率门槛以 pyproject.toml 为准。当前项目若仍设置 fail_under=85，则必须达到该门槛。

注意：

- coverage 命令只在实现稳定后运行；
- 如果被中断，不算通过；
- 不要只报告普通 line coverage 而遗漏 branch coverage；
- 不要修改 fail_under 来适配结果；
- coverage 慢不代表可以伪造通过。

### 15.4 静态与门禁

    .venv/bin/ruff check sopcontrol plugins tests
    git diff --check
    .venv/bin/python -m sopcontrol.cli gate .
    .venv/bin/python -m sopcontrol.cli project check .
    .venv/bin/python -m sopcontrol.cli chronicle check .

如果 sopctl 已在 PATH，也可以使用项目规定的等价命令，但必须在报告中写明实际执行的命令。

门禁命令可能更新 .sopcontrol/evidence 或其他控制器状态。不得直接编辑这些文件；如果门禁提示需要通过 sopctl 子命令完成的状态更新，应按 AGENTS.md 和项目 playbook 执行。

---

## 16. 完成定义

只有满足以下全部条件，才可以报告“本手册完成”：

### 代码行为

- R-01 至 R-09 均已复现、修复或有明确的“当前版本已由回归测试证明不存在”证据；
- 所有正式入口使用统一的 side-effect 分类和 admission；
- operation、ticket、run、receipt 上下文一致；
- profile 层支持未声明字段继承；
- check_id 不再自动猜测；
- symlink 默认策略与文档一致；
- 安装、卸载、恢复和 handoff 失败可恢复且不越权；
- secret 不出现在可观察输出中。

### 测试

- 每项都有命名测试；
- 负向测试确实检查阻断、文件不变、ticket 失配或 receipt 不产生；
- 定向测试全绿；
- 全量测试全绿；
- branch coverage 达到配置门槛；
- ruff、git diff --check、gate、project check、chronicle check 全绿。

### 产品边界

- 没有把 JobsFlow 的业务语义 lint 搬进 SOP Control；
- 没有把某一种独立审计风格硬编码进 SOP Control；
- SOP Control 只确保业务系统声明的检查被正确经过、结果可验证、后续动作受门控制；
- 没有通过增加无必要的多模型审查、重复验证或无期限 ticket 来扩大耗时。

### 交付诚实性

- 没有把被中断的命令报告为通过；
- 没有把 mock 环境结果报告为真实外部 harness 结果；
- 没有把“代码写完”报告为“已发布”；
- 没有未经授权 commit 或 push；
- 所有剩余风险、未覆盖平台和性能风险都已列出。

---

## 17. 最终报告模板

外部模型完成后，必须按下面结构输出，不得只说“已修复”：

### A. 结论

- 状态：完成 / 部分完成 / 阻塞
- 修复范围：
- 未修改范围：
- 是否满足本手册完成定义：
- 若未满足，阻塞项和原因：

### B. 修改清单

按 R-01 至 R-09 列出：

- 问题；
- 修改文件；
- 修改函数或调用链；
- 行为变化；
- 是否增加回归测试；
- 是否影响公开 CLI 或兼容性。

### C. 关键控制不变量

明确回答：

- side_effect 是否在 envelope 之前确定；
- challenge、ticket、admit、receipt 的 operation_id 是否一致；
- run_id 是否稳定；
- capability_binding 是否贯穿所有入口；
- profile 的 absent 与 explicit default 是否可区分；
- 缺失 check_id 是否会被拒绝；
- symlink 默认策略是什么；
- manifest 外部路径是否会被拒绝；
- 安装/卸载失败时如何恢复；
- secret 是否可能出现在输出中。

### D. 测试证据

列出实际执行的命令及结果：

- 定向测试：通过数量；
- 全量测试：通过数量、跳过数量、失败数量；
- coverage：line 和 branch 结果；
- ruff；
- git diff --check；
- gate；
- project check；
- chronicle check。

不要只写“全部通过”，要写实际数字和命令。

### E. Git 状态

- 当前分支：
- 当前 HEAD：
- 工作区状态：
- 本次新增或修改的文件：
- 是否 commit：
- 是否 push：
- 如果未 commit/push，明确写“未执行，因为本手册未授权”。

### F. 剩余风险

只列真实存在的风险，例如：

- Windows 或其他平台尚未在真实环境验证；
- 超大文件摘要性能；
- 外部 harness 依赖不可用；
- cooperating-operator 边界不等于沙箱级不可绕过；
- 旧版本数据需要迁移；
- 某项兼容性仍需产品方确认。

---

## 18. 禁止的伪完成方式

以下任一行为都不算完成：

- 把 tickets_enabled 设为 off；
- 在 enforce 模式下增加“测试专用永久旁路”；
- 仅在内部 Python API 修复，正式 CLI 仍然可以绕过；
- 让空 side_effect 默认变成 readonly；
- 让空 binding 默认变成通配；
- 让消费过的 ticket 通过 allow_consumed 参数重新使用；
- 让 check_id 从其他字段自动生成；
- 让 profile 默认值覆盖未声明字段；
- 只在日志中写“独立审计通过”，没有真实的已声明检查证据；
- 接受 manifest 中任意绝对路径；
- 在失败时删除 backup 或外部 sentinel；
- 使用普通 write_text 覆盖 handoff；
- 只做正向测试，不做攻击/失败测试；
- 删除或放宽已有断言；
- 降低 coverage 门槛；
- 因为全量测试耗时长而报告未运行的结果；
- 未经用户授权 commit、push、发布或修改业务产品。

---

## 19. 给执行模型的结束语

你要修的是一个控制面，而不是另一个业务引擎。

判断成功的标准不是“代码看起来更复杂”，也不是“增加了多少票据、哈希和审计步骤”，而是：

- 该受控的入口确实受控；
- 不该由 SOP Control 决定的业务语义没有被它擅自决定；
- 动态规则按用户和系统明确声明的目标执行；
- 未声明的内容继承已有规则，显式放宽被拒绝；
- 规则、动作、运行和结果之间没有歧义；
- 失败时停在可恢复状态；
- 正常路径不会因为重复挑战、重复审计和重复 token 消耗而产生不必要的摩擦；
- 任何“通过”都能由测试和真实控制链证明。

完成后，按第 17 节交付证据；不要用一句“已完成”替代证据。
