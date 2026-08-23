"""state_health 检测器单元测试（同时构成 SELF-001/SELF-002 规则的回归证据）。"""
from pathlib import Path

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit

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
    assert patterns_for(tmp_path) == {("write_only_state", "info")}


def test_state_in_parallel_files_detected(tmp_path):
    build(tmp_path, {
        "src/app.py": "order_state = {}\n",
        "src/report.py": "from app import order_state\n",
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
