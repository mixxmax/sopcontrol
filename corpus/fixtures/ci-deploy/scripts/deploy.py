"""部署入口（CI 领域夹具：受控入口断口）。"""

# TODO: cache_gate 预热缓存后再部署（注释提及，并未接线）

deploy_state = {}


def deploy(target):
    """直接部署——手册要求的受控入口在脚本中并不存在。"""
    deploy_state["last"] = target
    print("deploying", target)
