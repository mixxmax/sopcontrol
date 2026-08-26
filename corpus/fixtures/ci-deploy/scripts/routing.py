"""通道路由：只读 channel_registry，不维护它（正确分层的读侧）。

长得像 5.8 的双处维护——同一个状态出现在两个生产文件里——区别只在这里没有
任何写入或原地改写。检测器若只数「出现在几个文件」，就会在这里误报。
"""

from registry import channel_registry


def resolve(name):
    return channel_registry.get(name, "default")


def known_channels():
    return sorted(channel_registry)
