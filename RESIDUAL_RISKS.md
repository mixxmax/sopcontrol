# 已知绕过家族登记表（Residual Risks）

诚实边界制度化（CC Safety Net SECURITY.md 的做法）：本文件登记当前检测能力
**已知抓不住**的绕过家族。每项注明检测思路与引入阶段。"对当前探测集，拦截率 X%"
是有界经验命题，不是数学定理。

## R1 标识符重命名绕过（现在）

`code_scan` 是 grep 智力：把 `require_preview` 改名为 `rp`、用 `getattr(x,
"req" + "uire_preview")` 动态拼接、通过字符串配置间接引用，检测即失明。
缓解路径：B2 引入入口/调用图传感器；`consumer_markers` 层面保持显式声明。

**反向家族（注释假阳性，已在建仓首夜真实发生）**：注释或 docstring 里*提到*
标记词（哪怕是在说"此处没有该消费者"），grep 也会当成消费者。夹具因此首夜
挂过两条语料用例。教训：夹具与被审代码中，标记词只能出现在真实调用处。

## R2 测试路径启发式可被绕过（现在）

`is_test_path` 按目录名/文件名判断。测试写在 `helpers/`、`fixtures/`、或生产
文件内嵌 `if __name__ == "__main__"` 的自测块，会被误判为生产消费者。
缓解路径：按调用关系而非路径判断（B2）。

## R3 enforced 的过度声称风险（现在，已克制）

`wired_and_tested` 只证明"消费者符号存在 + 测试路径引用过它"，不证明：
负向测试真的会失败、无旁路入口、运行时真的加载了规则。手册 6.5 的七条件中
v0 只满足其二，因此 v0 永不颁发 enforced（宪法测试断言）。

## R4 文档侧规则≠登记规则（现在）

doc_scan 只记录"文档里有 MUST 句"，不把它等同于 registry 中的规则。从对话/
文档自动抽取 CandidateRule 是 B2 的意图编译器职责；在那之前，规则登记是人工的。

## R5 并发写账本（现在）

账本追加无文件锁。两个并发 audit 可能交错写行（JSONL 行级追加在 POSIX 上
单行 ≤ PIPE_BUF 时原子，但跨平台不保证）。单人单项目场景不构成实际风险；
B1 引入 CI 终态门时一并处理。

## R6 hook 可被绕过（B1 起）

pre-push 终态门可被 `git push --no-verify`、直接调用 git 底层传输或未装钩子的
机器绕过（手册 12.2：跨平台不能实时拦截时，至少在终态拦截）。后盾是 CI：
CI 从远端主分支运行可信的 sopctl gate，不信任本地钩子是否安装。另一个已知
缺口：gate 在推送时运行，工作区与被推 commit 可能不一致（skew）——精确绑定
需任务 revision 与提交 hash 的关联（B3 评估）。

## R7 任务文件可被手工篡改（B2 起）

任务状态存于 `.sopcontrol/tasks/*.yaml`，无签名。拥有写权限的 agent 可以手工把
status 改成 verified 绕过完成门——revision 只防并发覆盖，不防恶意改写。当前防线
是完成门验证时重跑独立审计（篡改状态不改变事实），以及 B1 终点门；彻底方案是
任务文件 hash 链或由控制器持有任务状态（B3/B4 评估）。

## R8 allowed_writes 路径匹配（B2 起，2026-08-26 加固）

原始缺口是三个，其中两个方向是 fail-open（漏放），已修：

- **大小写**：macOS / Windows 文件系统大小写不敏感，`.SOPCONTROL/rules/registry.yaml`
  写的就是信任根本身，而字面 `== ".sopcontrol"` 的守卫直接放行。三处 deny 判定
  （`harness` 写入门、`harness` bash 门、`repair` 合并回主树的过滤）已改为按路径
  分量做 casefold 比对。
- **symlink 逃逸**：允许写 `src/` 时，`src/link -> /etc` 让 `src/link/passwd` 字面
  完全合规；末节点自己是 symlink 也一样（`shutil.copy2` 跟随链接）。`worktree.
  resolves_inside` 解析每一层并要求仍落在隔离树内，接在 `repair.apply_repair`
  的合并边界上。因为需要碰文件系统，它不能放进 `task.path_allowed`（迁移门受
  纯函数宪法守卫）。悬空 symlink 单独认：`exists()` 为假但确实会被写穿。

**刻意不改的一个**：allow-list 比对保持大小写敏感。比对不上只是多拒一个改动
（fail-closed，最坏是误报）；而归一化会在大小写敏感的文件系统上把契约外的
`SRC/` 放进 `src` 的范围，那才是 fail-open。守卫的两侧不对称——deny 归一化，
allow 不归一化。宪法测试 `test_allow_list_stays_case_sensitive` 锁住这个判决。

**仍存的边界**：不识别硬链接与 bind mount 等其他路径别名；范围检查只约束声明
路径，submit 不验证文件真实被改——完成门靠独立审计兜底。

## R11 项目身份随绝对路径漂移（Phase 6 种子）

默认 `project_id` 由绝对路径哈希派生；挪盘/换路径会变。缓解：`sopctl identity lock`
固定 id（仍非全局 registry）。全局 daemon / 远程身份同步仍属 Phase 6 其余部分。

## R12 supervised runtime 不是沙箱（Phase D）

`sopctl enter --mode supervised` 记录进程事件并注入身份环境，**不**拦截子进程直接
读写文件或出网。Coverage 对 `runtime_supervised` / `network` / `browser` 保持
observable+gap，不以 HTTP_PROXY 冒充不可绕过控制。真正隔离属 isolated/system 级，
需单独评估权限成本。

## R13 effect 原语不是产品 breaker（Phase E）

`sopctl effect` 提供网络分类、浏览器会话分类、凭证 ticket、DB 摘要、后台登记与
幂等回执。门户级 WAF / Cloudflare / JobsDB breaker 语义仍在业务 Policy Pack；
Core 不内置任何产品站点规则。

## R10 JS/TS/Go/Rust 词法剥离的已知缝隙（2026-08-30 更新：Go 已结构化）

**Go 已升级**：`go_ast_scan`（tree-sitter-go，2026-08-30 用户授权越过依赖白名单）
产出结构化引用与包/import 证据，`go_scan` 仅作解析失败回退（grounding 如实标
lexical）。同包互见 + import 末段匹配包名的闭包近似：import 路径末段 ≠ 包声明名
时闭合走不通，方向是过报（test_cannot_reach_consumer 误响）而非漏报。

**TS 已结构化（2026-08-30）**：`ts_ast_scan`（tree-sitter-typescript）覆盖
.ts/.tsx（结构化引用 + import 归一顶层名），reachability TS 分支复用 Python 闭包
机器（MUT-011 守过报方向）。**.js/.jsx/.mjs/.cjs 按设计永留词法层**（语料 CASE-048
永久看守词法自曝）；解析失败的 .ts 回退词法并如实标 lexical。

**Rust 已结构化（2026-08-30，件5 收尾）**：`rust_ast_scan`（tree-sitter-rust）
产结构化引用 + use/mod 模块边（use 全段参与闭合，crate/self/super 关键字段剔除；
mod 声明取 name 字段——节点类型是 mod_item 而非 mod_declaration，接手时修正）。
Rust 集成测试是独立 crate：零 use 的测试文件经空边 modules 证据进闭包索引，
只能到自己是替身的形状，被 test_cannot_reach_consumer 识破（CASE-027）；
经 `use crate::limiter` 闭合的真回归通过（CASE-049）。MUT-012 守过报方向。
解析失败的 .rs 回退词法并如实标 lexical。词法判定至此只剩 .js 家族对照（按设计永留）。

## R9 修复智能在脊柱之外（B3 起，2026-08-26 更新）

`repair open` 只提供有界框架（契约/预算/指纹熔断/完成门）；写补丁的语义工作
由人或模型插件在契约内完成，控制器不生成修复。修复不会自动扩大 allowed_writes
或改写规则本身。

`sopctl repair apply`（自动修复者 v0）已补上 git worktree 隔离：模型只在
`.sopcontrol/worktrees/<task_id>` 内改动，回主树时按 `allowed_writes` 过滤并
硬排除 `.sopcontrol/`，契约外改动留在隔离树中随之销毁。`worktree_path` 自身要求
`task_id` 是单一路径分量，绝对路径、`..`、正反斜杠穿越均在底层拒绝，不依赖上游
`TaskStore.load` 偶然兜底。

**仍存的边界**：合并回主树用文件复制，不是 git 合并——主树同一文件的未提交改动
会被覆盖（无三方合并、无冲突检测）。修复者产出的补丁本身未经审阅即落主树，
其正确性完全靠事后的完成门独立审计兜住；`--keep-worktree` 之外没有人工 review
断点。当前仅支持 `harness=opencode`。

## R12 可逆生命周期的事务与作用域边界（第七批 7E）

生命周期 mutation 的 registry 互斥使用 `fcntl.flock`，当前只支持 POSIX/macOS；Windows 等
无 `fcntl` 平台尚无等价锁实现。registry 与 AGENTS/CLAUDE 投影失败时按原字节回滚，但这只是
进程内异常补偿，不是断电安全 journal：进程被杀或机器断电仍可能留下 registry/投影不一致，需
`project check` / `doctor` 发现后人工恢复。

scope v1 只建模项目级与仓库相对路径前缀，不覆盖 Evidence 的非路径 subject，也不表达任务、
平台或时间级 scope；这些维度不能借现有路径 scope 假装已治理。普通规则 suspend 只移出该固定
时点的 effective rules；控制面写保护等静态系统 invariant guards 是更底层信任边界，不随暂停关闭。
反过来，v1 也没有让静态 guard 理解任意动态 scope 例外，需例外语义时仍走显式控制面变更。

