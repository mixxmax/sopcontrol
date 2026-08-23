from checkout import confirm_refund


def test_confirm_refund():
    assert confirm_refund("o-1", 10)["confirmed"] is True
