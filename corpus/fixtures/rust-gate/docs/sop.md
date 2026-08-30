# Rust 网关 SOP

- 对外写操作必须经 admit_request 受控入口。
- 审计钩子必须经 register_audit_hook 注册。
- 限流必须经 enforce_rate_limit 受控入口，并有经 use 闭合的真实回归。
