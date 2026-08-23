"""部署入口（CI 领域夹具：受控入口断口）。"""


def deploy(target):
    """直接部署——手册要求的受控入口在脚本中并不存在。"""
    print("deploying", target)
