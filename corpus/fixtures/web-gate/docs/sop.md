# Web API 网关 SOP

- 对外写操作必须经 request_gate 受控入口。
- 审计钩子必须经 audit_hook 注册，注释提及不算接线。
