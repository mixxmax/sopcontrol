"""旧入口已拆除的回归：断言 legacy_direct_charge 在生产里不存在。

这是 legacy_entry_alive 的负向对照，旧符号必须以**真实引用**（import）出现，
而不是 `hasattr(billing, "legacy_direct_charge")` 那样的字符串——字符串里的名字
本来就不算引用，检测器对它保持沉默只证明「没看见」，不证明「看见了但认定测试
路径不算绕过」。空转的对照比没有对照更坏：它让人以为这条判断已被守住。

把测试路径的引用判成「旧入口存活」，等于惩罚为拆除写回归的人，而这恰恰是最该
鼓励的行为。shop-checkout/tests/test_settlement.py 是同一模式的第二域对照。
"""

try:  # 旧入口应当已不存在——这个 import 是真实 AST 引用，不是字符串
    from billing import legacy_direct_charge
except ImportError:
    legacy_direct_charge = None


def test_legacy_direct_charge_is_gone():
    assert legacy_direct_charge is None
