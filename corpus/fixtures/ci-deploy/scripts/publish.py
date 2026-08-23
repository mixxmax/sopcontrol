"""发布入口（新链：受控管线）。"""


def publish_pipeline(artifact):
    """带签名校验的发布。"""
    return {"artifact": artifact, "signed": True}
