# 发布手册

- 部署必须通过 deploy_gate 入口执行。
- 回滚必须经过 rollback_guard 校验。
- 发布产物必须携带 release_guard 签名。
- 部署完成通知必须经 notify_hook 发出。
