# Limitations（诚实边界）

SOP Control **v0.2** 是可用的实验性控制平面，不是企业治理套件。

## 它是什么

- 把用户意图变成**项目内**的 Rule / Evidence / Verdict
- 换会话、换模型时从项目恢复同一受控空间
- 无感积累观察与候选；**写入权威规则 / 删代码仍需人确认**

## 它不是什么

- 不是「保证模型不犯错」的产品
- 不是自动写完所有 SOP 的 Agent
- 不是跨机器全局策略云 / SSO / 管理后台

## 平台兼容性

| Harness | 运行时拦截 | 实测状态 |
|---------|------------|----------|
| OpenCode | 插件 `tool.execute.before` | **已 live 实测** |
| Codex | 无运行时钩子 → 投影 + `wrap` 事后门 | **已 live 实测** |
| Claude Code | PreToolUse 协议已适配 | 协议核实；**live 视环境 API key** |

## 已知技术边界

完整绕过家族见 [`RESIDUAL_RISKS.md`](RESIDUAL_RISKS.md)。摘要：

- 标识符重命名 / 动态拼接可削弱部分扫描（多语言深度不一）
- `git push --no-verify` 可绕过本地 hook（CI gate 为后盾）
- 任务 YAML 可被有写权限者手改状态（完成门重跑审计兜底）
- 检测「旁路仍在」≠ 自动删掉旁路；消歧要人 `candidate enact` 圈范围

## 安全与信任模型

默认假设：**合作操作者在自己的机器上**。  
若存在真实对抗方，需另设信任根与部署边界；本仓库不假装已解决。
