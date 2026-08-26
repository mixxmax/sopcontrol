"""结算回归：受控入口的真断言 + 旧入口已拆除的断言。

旧符号必须以**真实引用**的形式出现在这里（import 而非字符串），否则这条对照
是空的：字符串里的名字本来就不构成引用，检测器的沉默只说明「没找到」，没说明
「找到了但认定测试路径不算绕过」。用 ImportFrom 让 direct_settle 真的进入本文件
的 AST 引用集，legacy_entry_alive 的沉默才归功于它只看生产路径这一判断。

拆掉旧入口后最该做的事就是留一条断言防止它回来。把这种引用读成「旧链仍存活」，
等于惩罚真的把旧入口拆掉的人。
"""

from settlement import settle_gate
from settlement_view import last_settlement

try:  # 旧入口应当已不存在——这个 import 是真实 AST 引用，不是字符串
    from settlement import direct_settle
except ImportError:
    direct_settle = None


def test_settle_via_gate():
    assert settle_gate("o-9", 50)["settled"] is True


def test_audit_field_is_read():
    settle_gate("o-9", 50)
    assert last_settlement() == "o-9:50"


def test_direct_settle_removed():
    assert direct_settle is None
