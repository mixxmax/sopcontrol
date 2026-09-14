# Prompt B：JobsFlow 侧更新 SOP Control 与接入自动学习

> 用法：先完成 Prompt A，并取得一个已经提交、可访问的 SOP Control 发布 commit。
> 再把本文件全文交给一个运行在 /Users/xiezhijie/ai-job-search 的执行模型。
> 目标：让 JobsFlow 使用新版 SOP Control，并真正接通自动学习事件和用户确认入口。

---

## 你要执行的任务

将 JobsFlow 从当前固定的旧 vendored SOP Control 更新到指定的新版，并完成两层接入：

~~~
一、依赖更新
SOP Control 发布 commit
    → vendor/sopcontrol 实际代码快照
    → JobsFlow 固定 PIN
    → JobsFlow 使用新版运行时

二、功能接入
JobsFlow 网关事件
    → LearningEvent
    → 任务/阶段窗口
    → Learning Proposal
    → JobsFlow user_prompt/通知协议
    → 用户选择
    → SOP Control 控制层或产品文档
~~~

只更新 vendor 而不接事件，自动识别不会在 JobsFlow 中工作；只接事件而不更新 vendor，JobsFlow 可能调用旧版接口。两部分都必须验证。

---

## 0. 必填发布参数

执行前将下面两个占位符替换成 Prompt A 的实际结果：

~~~
SOPCONTROL_VERSION=<例如 0.3.0 或实际发布版本>
SOPCONTROL_COMMIT=<SOP Control 最终干净 commit>
~~~

不要使用 main、master、浮动分支或“最新代码”作为依赖版本。JobsFlow 必须固定不可变 commit，同时保留人可读版本号。

如果 SOPCONTROL_COMMIT 不存在、无法访问、没有通过 Prompt A 的测试和 gate，停止并报告 BLOCKED，不要自行猜测另一个 commit。

---

## 1. 先读取和验证当前 JobsFlow

你第一次接触 JobsFlow。先阅读：

1. AGENTS.md、SETUP.md、README.md、README_ZH-CN.md；
2. vendor/README.md；
3. tools/sopcontrol_pin.txt；
4. vendor/sopcontrol/PIN.txt、vendor/sopcontrol/pyproject.toml；
5. tools/workflow/sopcontrol_adapter.py；
6. tools/workflow/engine.py、tools/workflow/interaction_shell.py、tools/workflow/__main__.py；
7. JobsFlow 的 workflow 测试、user_prompt/reply_contract 测试和现有 SOP Control 接入测试。

必须确认以下事实：

- JobsFlow 通过 vendor/sopcontrol 运行控制器；
- tools/workflow/sopcontrol_adapter.py 优先把 vendor 路径放进 sys.path；
- 仅执行 pip install -U sopcontrol 不能替换 JobsFlow 实际加载的 vendor 代码；
- JobSearch_2026/ 是私人运行数据，不是要复制代码的地方；
- 当前 JobsFlow 工作树可能有用户改动，必须先保护。

本任务不能修改 /Users/xiezhijie/sopcontrol 源仓库的生产代码；只消费已经发布的版本。

---

## 2. 工作树保护和分支纪律

开始前运行：

~~~
git status --short
git branch --show-current
git log -1 --oneline
~~~

当前工作树已有改动时：

- 不得 git reset --hard；
- 不得 git checkout --；
- 不得用 git pull 覆盖用户改动；
- 建立独立更新分支，或在干净 worktree 中更新；
- 只提交属于本次 SOP Control 更新和 JobsFlow 接入的文件。

如果无法区分已有改动和本任务改动，停止并报告，不要擅自删除或覆盖。

---

## 3. 第一部分：更新 vendored SOP Control

### 3.1 必须更新的内容

使用 SOPCONTROL_COMMIT 对应的干净源码快照，更新：

~~~
vendor/sopcontrol/sopcontrol/
vendor/sopcontrol/plugins/
vendor/sopcontrol/pyproject.toml
tools/sopcontrol_pin.txt
vendor/sopcontrol/PIN.txt
~~~

如果新版发布中包含必须随包携带的 README、license 或 manifest，也一并按现有 vendor 规则更新。

不能只改两个 PIN 文件。PIN 改了但实际代码没换，属于假升级，必须失败。

### 3.2 更新后的强制检查

在 JobsFlow 使用的 Python 环境中运行：

~~~
python3 -c '
import sopcontrol
print("version:", sopcontrol.__version__)
print("module:", sopcontrol.__file__)
'
~~~

模块路径必须指向 JobsFlow 的：

~~~
/Users/xiezhijie/ai-job-search/vendor/sopcontrol/...
~~~

版本必须等于 SOPCONTROL_VERSION。如果输出来自错误的 site-packages，修复解释器或 editable 安装，不要继续。

如 JobsFlow 需要直接使用 sopctl 命令，在 JobsFlow 自己的 venv 中执行：

~~~
python3 -m pip install -e vendor/sopcontrol
~~~

这只是 CLI 安装，不替代 vendor 快照。长时间运行的 Python/Agent 进程更新后必须重启。

### 3.3 vendor 完整性

验证：

- vendor/sopcontrol/sopcontrol/__init__.py 版本正确；
- 新版自动学习 Module、插件和 CLI 若属于发布范围，确实存在；
- vendor 中没有旧版本残留文件；
- 两个 PIN 相同；
- vendor 代码摘要与发布源一致；
- vendor 快照可在无 SOP Control 源码目录的 cwd 中独立导入。

建议生成或更新 vendor manifest，至少包含版本、commit、包摘要和文件数量。若项目已有 manifest，复用，不要创建第二套。

---

## 4. 第二部分：接通 JobsFlow 的 LearningEvent

### 4.1 不复制 SOP Control 逻辑

JobsFlow 只负责把产品事实提交给 SOP Control，不自己实现：

- 规则归并；
- LLM 提炼；
- 规则分类权威；
- Registry 写入；
- 编译和激活；
- 文档/控制层决策逻辑。

JobsFlow 可以有一个很薄的 Adapter，例如在现有 sopcontrol_adapter.py 或独立模块中提供：

~~~
record_learning_event(event) -> event_id
review_learning_window(window_scope) -> proposal list
submit_learning_decision(proposal_id, decision, edited=None) -> result
~~~

实际接口以新版 SOP Control 为准。Adapter 只做字段映射、产品上下文和宿主协议转换。

### 4.2 必须采集的产品事件

在不改变 JobsFlow 业务状态机的前提下，接入以下事件：

- 用户消息中明确的纠正或长期执行要求；
- 模型/网关准备执行的关键动作；
- SOP admission 或产品门拒绝的动作；
- 用户要求撤回、重做或缩小范围的动作；
- 最终采用的替代计划；
- 任务和阶段边界；
- 明显由错误顺序引起的额外成本或范围扩大。

优先使用 JobsFlow 已有的结构化 user_prompt、reply_contract、网关请求和结果对象；不要通过扫描全部日志或复制整段私人对话实现。

每个事件必须包含：产品、动作、阶段、task/session ID、来源引用、时间和经过脱敏的上下文。不得把 JD、简历、Cover Letter、Cookie、token、secret 或大段正文直接发送给学习模块。

### 4.3 窗口边界

推荐在以下节点调用回顾：

- 一个 workflow action 完成；
- 一个任务阶段完成；
- 用户纠正已被采用；
- 相同路径即将再次被执行；
- 用户显式 /learn。

禁止在每个工具调用后启动大模型。JobsFlow 只提交事件或请求回顾，由 SOP Control 负责窗口汇总和成本预算。

---

## 5. 第三部分：接通用户提示和确认

### 5.1 使用现有 JobsFlow 交互协议

JobsFlow 已有 needs_user、user_prompt、reply_contract 等协议时，复用它们。学习提案应作为结构化的用户选择请求返回，而不是在产品层重新发明第二套确认格式。

建议输出：

~~~
{
  "status": "needs_user",
  "reason": "learning_proposal",
  "proposal_id": "lp-001",
  "user_prompt": "发现一条可能需要长期保留的执行规则：……",
  "choices": [
    "control",
    "edit_control",
    "document",
    "both",
    "once_only",
    "defer",
    "reject"
  ],
  "reply_contract": {
    "type": "learning_decision",
    "proposal_id": "lp-001"
  }
}
~~~

具体字段必须服从当前 JobsFlow 的既有协议。用户提示中的摘要、范围、例外、非目标和证据引用必须来自 SOP Control，不得由 JobsFlow 自己改写成更宽泛的规则。

### 5.2 用户决定回传

用户的选择必须原样、明确地回传给 SOP Control：

- 用户未回复：保持 pending；
- 用户选择 defer：不生效；
- 用户选择 document：只交给产品文档机制；
- 用户选择 control：调用 SOP Control 正规决策接口；
- 用户选择 both：调用统一分流接口；
- 用户选择 once-only：绑定当前 session/task；
- 用户选择 reject：标记拒绝并抑制重复。

JobsFlow 不得代替用户点击，不得把普通对话中的“应该”解释成用户批准。

### 5.3 /learn 显式入口

如果宿主已有 /learn，将它适配为 explicit_learn 来源并把指定会话/任务/主题传给 SOP Control。

如果 JobsFlow 没有原生斜杠命令，提供等价的结构化入口，但不要强迫用户日常使用。自动路线必须独立可用。

/learn 可以直接请求回顾，但仍需使用相同的提案、校验和用户决定流程。

---

## 6. 文档和控制层的边界

JobsFlow 的 AGENTS.md、Rules、Skills 和产品说明仍归 JobsFlow 产品所有。SOP Control 只提供：

- 控制提案；
- 文档目标建议；
- 关联 proposal/digest；
- 运行时控制结果。

不得：

- 把所有 AGENTS.md 的 MUST 自动登记到 Registry；
- 覆盖用户自有文档；
- 把 SOP Control 自己的投影块再次导入；
- 因为文档写入成功就报告控制已接线；
- 让文档和 Registry 互相循环生成提案。

控制规则只有在 SOP Control 侧 confirmed/compiled/select 后，才可影响运行时。

---

## 7. 与现有 JobsFlow 控制接入的兼容要求

当前 SOP Control adapter 还承担 admission、规则映射和 ControlEvent 回执。新增学习能力不得破坏它们：

- scan/push/intake/materials/apply 等既有控制动作继续经过原有 gateway；
- 既有 capability ticket、run_id、receipt 和脱敏逻辑不被学习事件绕过；
- 学习观察本身不申请不必要的高影响 ticket；
- 用户确认 control 后产生的 Registry 写入仍走 SOP Control 正规接口；
- 业务状态机、材料引擎和语义检查仍由 JobsFlow 产品线负责；
- 学习模块不能把业务语义审查范围扩大到用户没有要求的方面。

当前接入状态如果有 git_hook: bare、claude: present_without_sopctl、opencode: absent 或 codex_no_pretool_hook 等 gap，分别报告并按现有 attach 规则处理。不要因为更新 vendor 就声称所有 harness 都已真实接管。

---

## 8. 测试顺序

### 8.1 vendor 更新测试

至少验证：

1. vendor 版本和 commit 正确；
2. vendor 路径优先于旧 site-packages；
3. 新版 CLI/Module 可以导入；
4. 无 SOP Control 源码 cwd 下仍可导入；
5. 旧 registry/rules 可以加载；
6. 既有 JobsFlow gateway 测试不回归；
7. capability ticket、run_id、receipt、脱敏测试不回归。

### 8.2 学习接入测试

至少覆盖：

1. 普通 workflow 不触发 LLM；
2. 用户一次纠正形成事件但不立即阻断；
3. 任务/阶段结束时事件进入窗口；
4. 多个 JobsFlow 事件被 SOP Control 归并为一条 proposal；
5. proposal 通过现有 needs_user 协议展示；
6. 用户未回复不生效；
7. control/document/both/once-only/defer/reject 分别正确；
8. /learn 显式入口和自动入口使用同一管道；
9. 用户明确要求反向逻辑时不被默认自然逻辑错误阻断；
10. 外部 AGENTS/Rules 变化只形成提案；
11. 私人 JD、简历、Cookie、token 不进入学习事件；
12. Distiller 不可用不阻断无关 workflow；
13. 同一提案不会重复弹窗；
14. 自动学习不会修改 JobsFlow 业务产物或材料内容。

### 8.3 真实演练

必须至少有：

- 一个真实 JobsFlow 任务中的用户纠正 → proposal → 用户选择；
- 一个真实 /learn 或等价显式入口 → proposal → 用户选择；
- 一次 control 选择后，下一次匹配动作确实能读取/选择该规则；
- 一次 document-only 选择证明 Registry 没有新增控制规则；
- 一次 once-only 选择证明新任务/重启后不变成永久规则。

没有真实宿主或真实 UI 时，诚实报告 UNPROVEN，不能用 fixture 冒充真实接入。

---

## 9. 运行检查和发布

使用 JobsFlow 自己的 Python 环境运行：

~~~
python3 setup.py --doctor
python3 -m tools.workflow doctor
~~~

使用已更新的 sopctl 运行：

~~~
sopctl attach-status .
sopctl compat .
sopctl project check .
sopctl gate .
~~~

根据仓库实际测试入口运行完整测试和安全检查。禁止因为存在旧工作树问题而删除测试或降低门槛。

JobsFlow 发布前必须提交：

- vendor 实际代码快照；
- 两个 PIN 文件；
- 学习事件 Adapter；
- Notification/user_prompt Adapter；
- /learn 入口（如果宿主支持）；
- 回归和真实演练测试；
- 版本更新说明。

如果没有明确 push 授权，只提交并报告 commit；不要自行推送。

---

## 10. 最终报告格式

~~~
# JobsFlow × SOP Control 更新与自动学习接入报告

## A. 结论
- vendor 更新：PASS / PARTIAL / BLOCKED
- 版本：
- 固定 commit：
- 实际加载路径：
- 自动 LearningEvent：PASS / PARTIAL / UNPROVEN
- 窗口级回顾：PASS / PARTIAL / UNPROVEN
- 用户提示：PASS / PARTIAL / UNPROVEN
- /learn 入口：PASS / PARTIAL / UNPROVEN
- control/document 分流：PASS / PARTIAL / UNPROVEN
- 真实 JobsFlow 演练：PASS / UNPROVEN

## B. 修改文件
逐文件写原因和测试。

## C. vendor 证据
- PIN 文件内容一致性：
- 版本探针：
- module path：
- vendor digest：

## D. 自动路线演示
- JobsFlow task/session：
- 事件数量：
- proposal_id：
- user_prompt：
- 用户决定：
- 控制层最终状态：

## E. /learn 路线演示
- 输入来源：
- 是否复用同一 proposal 管道：
- 用户决定：

## F. 安全和成本
- 普通 workflow LLM 调用：
- 每窗口 Distiller 调用：
- 敏感数据脱敏：
- capability ticket 变化：

## G. 测试和门禁
- JobsFlow 全量测试：
- SOP Control 接入测试：
- doctor：
- attach-status：
- compat：
- project check：
- gate：

## H. 剩余 gap
逐项写真实证据和关闭条件，不得用理论支持替代实测。
~~~

