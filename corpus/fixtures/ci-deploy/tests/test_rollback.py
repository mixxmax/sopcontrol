from rollback import rollback, rollback_guard


def test_guard():
    assert rollback_guard("api")["allowed"] is True


def test_rollback_via_guard():
    assert rollback("api")["allowed"] is True
