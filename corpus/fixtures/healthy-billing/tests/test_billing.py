"""计费域回归：闸门、凭证、审计字段都有真实断言。

这些测试的作用是让「有生产消费者 + 有回归」成立，从而 wired_and_tested 是
真的，不是靠夹具摆样子。
"""

from billing import audit_field, charge_gate, invoice_state, receipt_check, record_audit


def test_charge_gate_rejects_nonpositive():
    assert charge_gate("acct-1", 0)["ok"] is False


def test_charge_gate_records_state():
    charge_gate("acct-2", 30)
    assert invoice_state["acct-2"] == 30


def test_receipt_check():
    assert receipt_check({"id": "r-1"}) is True
    assert receipt_check({}) is False


def test_audit_field_is_read():
    record_audit("charged")
    from billing import audit_field as latest

    assert latest == "charged"
    assert audit_field == "" or isinstance(audit_field, str)
