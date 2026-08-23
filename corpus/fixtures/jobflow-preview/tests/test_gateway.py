from gateway import workflow_gateway


def test_rejects_unconfirmed():
    try:
        workflow_gateway(sheet=[], row={}, confirmed=False)
        raised = False
    except ValueError:
        raised = True
    assert raised
