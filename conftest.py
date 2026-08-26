# 仓库根 conftest：让 pytest 把仓库根加入 sys.path，tests/ 与 corpus/ 可直接引用。
import os

# E4 递归自锁（手册 4.3）：本仓库的 manifest.test_command 就是 pytest 自己，而
# tests/corpus/test_task_cases.py 与 tests/repair/test_repair.py 会在测试内调用
# 完成门。不设这个标记的话，只要哪天夹具里出现 manifest.yaml，就会 pytest 套
# pytest。靠「夹具恰好没有 manifest」是运气，不是机制，所以在此处显式钉死。
os.environ.setdefault("SOPCONTROL_TEST_RUN_ACTIVE", "1")
