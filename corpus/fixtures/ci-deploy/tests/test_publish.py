from publish import publish_pipeline


def test_publish_signed():
    assert publish_pipeline({"pkg": 1})["signed"] is True
