# Go 网关 SOP

- 对外写操作必须经 AdmitRequest 受控入口。
- 审计钩子必须经 RegisterAuditHook 注册。
