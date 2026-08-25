# 退款 SOP

- 退款必须先调用 confirm_refund 获得用户确认。
- 大额退款必须携带 risk_review 审核结果。
- 退款流水必须写入 audit_log。
- 退款凭证必须经 receipt_guard 校验。
