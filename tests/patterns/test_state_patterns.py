"""state_health 检测器单元测试（同时构成 SELF-001/SELF-002 规则的回归证据）。"""
from pathlib import Path

from plugins import DETECTORS, SENSORS
from plugins.detectors.state_health import (
    finding_state_in_parallel_files,
    finding_write_only_state,
)
from sopcontrol.audit import run_audit

# AST 可见引用：SELF-001/002 的测试路径消费者（字符串不算）
_SELF_REGRESSION = (finding_write_only_state, finding_state_in_parallel_files)
assert _SELF_REGRESSION

REGISTRY = """rules:
- rule_id: STATE-001
  statement: 状态必须单一真源
  modality: MUST
  status: accepted
  scope: app
  owner: product
  risk: medium
  source:
    type: manual_seed
    ref: tests
  state_markers:
  - order_state
"""


def build(tmp_path: Path, files: dict[str, str]):
    (tmp_path / ".sopcontrol" / "rules").mkdir(parents=True)
    (tmp_path / ".sopcontrol" / "rules" / "registry.yaml").write_text(REGISTRY)
    for rel, content in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def patterns_for(tmp_path, rule_id="STATE-001"):
    report = run_audit(tmp_path, SENSORS, DETECTORS)
    return {(f.pattern_id, f.severity) for f in report.findings if f.rule_id == rule_id}


def test_write_only_state_detected(tmp_path):
    build(tmp_path, {"src/app.py": "order_state = {}\n"})
    # 单文件只写：write_only_state + 场景3 加深 schema_field_unread
    assert patterns_for(tmp_path) == {
        ("write_only_state", "info"),
        ("schema_field_unread", "gap"),
    }


def test_state_in_parallel_files_detected(tmp_path):
    # 两个生产文件都在改这份状态：一处首次绑定，一处原地改写 → 真源不明
    build(tmp_path, {
        "src/app.py": "order_state = {}\n",
        "src/report.py": "from app import order_state\n\n\ndef mark(k):\n    order_state[k] = 'seen'\n",
    })
    assert patterns_for(tmp_path) == {("state_in_parallel_files", "gap")}


def test_layered_state_not_flagged(tmp_path):
    """一处定义、一处读取是规则要求的单一真源，不得当成双处维护。

    过度告警和漏报同罪：把正确分层报成 gap，用户就会开始绕过控制器。
    """
    build(tmp_path, {
        "src/app.py": "order_state = {}\n",
        "src/report.py": "from app import order_state\n\n\ndef view():\n    return dict(order_state)\n",
    })
    assert patterns_for(tmp_path) == set()


def test_mutation_counts_as_maintenance(tmp_path):
    """列表/字典方法调用也是维护——`d.setdefault(...).append(...)` 在 AST 里是 Load。

    少了这一条，双处维护只要不用裸赋值就能躲过检测（漏报方向的反例）。
    """
    build(tmp_path, {
        "src/app.py": "order_state = {}\n",
        "src/report.py": (
            "from app import order_state\n\n\n"
            "def note(k):\n    order_state.setdefault(k, []).append(1)\n"
        ),
    })
    assert patterns_for(tmp_path) == {("state_in_parallel_files", "gap")}


def test_state_marker_absent_detected(tmp_path):
    build(tmp_path, {"src/app.py": "x = 1\n"})
    assert patterns_for(tmp_path) == {("state_marker_absent", "info")}


def test_healthy_state_not_flagged(tmp_path):
    # 生产 + 测试都消费 → 三种状态模式都不触发（正向对照）
    build(tmp_path, {
        "src/app.py": "order_state = {}\n",
        "tests/test_state.py": "from app import order_state\n\ndef test_s():\n    assert order_state == {}\n",
    })
    assert patterns_for(tmp_path) == set()
