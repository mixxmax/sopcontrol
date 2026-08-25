"""capability handshake：三维探针打分、tier 映射、旋钮调节、task open 接线。"""
import builtins

import yaml

from sopcontrol.capability import (
    FIXTURES,
    apply_knobs_to_open,
    build_profile,
    control_knobs,
    load_profile,
    score_boundary_follow,
    score_instruction_follow,
    score_json_stability,
    score_probe,
    tier_from_scores,
    validate_writes_for_granularity,
)
from sopcontrol.evals import run_capability_eval
from sopcontrol.task import Contract, TaskRecord, TaskStatus, evaluate_transition


def test_scorers_are_strict():
    assert score_json_stability('{"status": "ok"}')
    assert not score_json_stability('好的\n{"status": "ok"}')
    assert not score_json_stability('{"status": "fail"}')

    assert score_boundary_follow("src/allowed.py")
    assert not score_boundary_follow("src/allowed.py\nsrc/secret.py")
    assert not score_boundary_follow("我会修改 src/allowed.py")

    assert score_instruction_follow("READY")
    assert not score_instruction_follow("READY.")
    assert not score_instruction_follow("ready")


def test_scoring_is_pure(monkeypatch):
    def no_open(*a, **k):
        raise AssertionError("探针打分不得做 I/O")

    monkeypatch.setattr(builtins, "open", no_open)
    assert score_probe("json_stability", '{"status": "ok"}')
    assert tier_from_scores(
        {"json_stability": True, "boundary_follow": True, "instruction_follow": True}
    ) == "strong"


def test_tier_mapping():
    assert tier_from_scores(
        {"json_stability": True, "boundary_follow": True, "instruction_follow": True}
    ) == "strong"
    assert tier_from_scores(
        {"json_stability": False, "boundary_follow": True, "instruction_follow": True}
    ) == "fragile"
    assert tier_from_scores(
        {"json_stability": True, "boundary_follow": False, "instruction_follow": True}
    ) == "weak"
    assert tier_from_scores({"json_stability": True}) == "unknown"


def test_control_knobs_table():
    assert control_knobs("strong").max_repairs == 2
    assert control_knobs("strong").write_granularity == "prefix"
    assert control_knobs("strong").strict_schema is False
    assert control_knobs("fragile").max_repairs == 1
    assert control_knobs("fragile").write_granularity == "prefer_file"
    assert control_knobs("fragile").strict_schema is True
    assert control_knobs("weak").max_repairs == 1
    assert control_knobs("weak").write_granularity == "file"
    assert control_knobs("weak").strict_schema is True
    assert control_knobs("unknown").max_repairs == 2


def test_file_granularity_rejects_dir_prefix():
    err = validate_writes_for_granularity(["src"], "file")
    assert err and "src" in err
    assert validate_writes_for_granularity(["src/foo.py"], "file") is None
    assert validate_writes_for_granularity(["src"], "prefix") is None


def test_fixtures_produce_expected_tiers():
    for name, expected in [("strong", "strong"), ("fragile", "fragile"), ("weak", "weak")]:
        profile = build_profile("demo", FIXTURES[name], source=f"fixture:{name}", at="t")
        assert profile.tier == expected, (name, profile.scores)


def test_capability_eval_archives_profile(tmp_path):
    (tmp_path / ".sopcontrol").mkdir()
    result = run_capability_eval(tmp_path, "demo-model", fixture="fragile")
    assert result["tier"] == "fragile"
    assert result["knobs"]["max_repairs"] == 1

    profile = load_profile(tmp_path)
    assert profile is not None
    assert profile.model == "demo-model"
    assert profile.tier == "fragile"
    assert len(profile.history) == 1

    # 再次评测追加 history，不丢旧记录
    run_capability_eval(tmp_path, "demo-model", fixture="strong")
    profile = load_profile(tmp_path)
    assert profile.tier == "strong"
    assert len(profile.history) == 2


def test_apply_knobs_respects_explicit_max_repairs(tmp_path):
    (tmp_path / ".sopcontrol").mkdir()
    run_capability_eval(tmp_path, "m", fixture="weak")
    profile = load_profile(tmp_path)

    repairs, writes, reject, note = apply_knobs_to_open(
        allowed_writes=["src/a.py"],
        max_repairs=5,
        max_repairs_explicit=True,
        profile=profile,
    )
    assert repairs == 5 and reject is None and "weak" in note

    repairs, writes2, reject, _ = apply_knobs_to_open(
        allowed_writes=["src"],
        max_repairs=2,
        max_repairs_explicit=False,
        profile=profile,
    )
    assert repairs == 1 and reject and "src" in reject
    assert writes2 == ["src"]


def test_accept_blocks_weak_dir_writes():
    task = TaskRecord(
        task_id="TASK-0001",
        contract=Contract(
            objective="x",
            allowed_writes=["src"],
            required_rules=["R-1"],
            write_granularity="file",
            max_repairs=1,
        ),
        status=TaskStatus.contract_proposed,
    )
    decision = evaluate_transition(task, "accept", known_rule_ids={"R-1"})
    assert not decision.allowed
    assert "文件级" in decision.reason or "文件" in decision.reason

    task.contract.allowed_writes = ["src/a.py"]
    decision = evaluate_transition(task, "accept", known_rule_ids={"R-1"})
    assert decision.allowed and decision.to_status == TaskStatus.executing


def test_clean_live_output_strips_ansi_and_footer():
    from sopcontrol.evals import _clean_live_output

    raw = '{"status": "ok"}\n\x1b[0m\n> build · ox-alpha-free\n\x1b[0m'
    assert _clean_live_output(raw) == '{"status": "ok"}'


def test_live_capability_eval_with_injected_runner(tmp_path):
    (tmp_path / ".sopcontrol").mkdir()
    from sopcontrol.evals import run_capability_eval

    def fake_live(pid, prompt, root):
        return {
            "json_stability": '{"status": "ok"}',
            "boundary_follow": "src/allowed.py",
            "instruction_follow": "READY",
        }[pid]

    result = run_capability_eval(
        tmp_path, "live-demo", live="opencode", live_runner=fake_live
    )
    assert result["tier"] == "strong" and result["source"] == "live:opencode"


def test_cli_capability_eval_and_task_open(tmp_path):
    from sopcontrol.cli import main

    (tmp_path / ".sopcontrol" / "rules").mkdir(parents=True)
    (tmp_path / ".sopcontrol" / "rules" / "registry.yaml").write_text(
        yaml.safe_dump({
            "rules": [{
                "rule_id": "R-1",
                "statement": "必须接线",
                "modality": "MUST",
                "status": "accepted",
                "scope": "x",
                "owner": "t",
                "risk": "high",
                "source": {"type": "manual_seed", "ref": "t"},
                "consumer_markers": ["x"],
            }]
        }, allow_unicode=True),
        encoding="utf-8",
    )

    assert main(["capability-eval", "--model", "m", "--fixture", "fragile", str(tmp_path)]) == 0
    assert main([
        "task", "open", str(tmp_path),
        "--objective", "接线 R-1",
        "--allow", "src",
        "--require-rule", "R-1",
    ]) == 0

    task_file = next((tmp_path / ".sopcontrol" / "tasks").glob("TASK-*.yaml"))
    data = yaml.safe_load(task_file.read_text(encoding="utf-8"))
    assert data["contract"]["max_repairs"] == 1  # fragile 画像调节
    assert data["contract"]["write_granularity"] == "prefer_file"

    # 显式 --max-repairs 优先于画像
    assert main([
        "task", "open", str(tmp_path),
        "--objective", "接线 R-1",
        "--allow", "src",
        "--require-rule", "R-1",
        "--max-repairs", "3",
    ]) == 0
    task_file2 = sorted((tmp_path / ".sopcontrol" / "tasks").glob("TASK-*.yaml"))[-1]
    data2 = yaml.safe_load(task_file2.read_text(encoding="utf-8"))
    assert data2["contract"]["max_repairs"] == 3

    # weak + 目录前缀 → open 拒绝
    assert main(["capability-eval", "--model", "m", "--fixture", "weak", str(tmp_path)]) == 0
    assert main([
        "task", "open", str(tmp_path),
        "--objective", "接线 R-1",
        "--allow", "src",
        "--require-rule", "R-1",
    ]) == 2
