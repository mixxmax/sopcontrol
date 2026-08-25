# 发布手册

- 部署必须通过 deploy_gate 入口执行。
- 回滚必须经过 rollback_guard 校验。
- 发布产物必须携带 release_guard 签名。
- 部署完成通知必须经 notify_hook 发出。
- 部署冒烟必须经 smoke_probe 探针。
- 金丝雀标志必须单一维护。
- 金丝雀提升必须经 CanaryHook。
