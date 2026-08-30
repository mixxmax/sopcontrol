# Web API 网关 SOP

- 对外写操作必须经 request_gate 受控入口。
- 审计钩子必须经 audit_hook 注册，注释提及不算接线。
- 旧链清理必须走 legacy_gate 受控入口（.js 遗留文件按设计永留词法层，判定须自曝）。
