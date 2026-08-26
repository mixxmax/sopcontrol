# 计费域 SOP（负向对照）

本文件的每条 MUST 在代码里都真的做到了。它的用途是让检测器在「规则被正确
吸收」的项目上保持安静。

- 所有扣费必须经 charge_gate 闸门，不得直接改 invoice_state。
- 退款凭证必须经 receipt_check 校验。
- 发票状态必须单一真源：billing.py 写，其余模块只读。
- 审计字段 audit_field 必须被下游读取，不得只写不读。
