"""capability handshake：三维探针打分、tier 映射、旋钮调节、task open 接线。"""
import builtins

import yaml

from sopcontrol.capability import (
    FIXTURES,
    ModelProfile,
    apply_knobs_to_open,
    build_profile,
    control_knobs,
    effective_control_knobs,
    load_profile,
    score_boundary_follow,
    score_instruction_follow,
    score_json_stability,
    score_probe,
    tier_from_scores,
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
    assert control_knobs("unknown").max_repairs == 1
    assert control_knobs("unknown").write_granularity == "file"
    assert control_knobs("unknown").strict_schema is True


def test_effective_knobs_require_matching_model_and_complete_profile():
    strong = build_profile("model-a", FIXTURES["strong"], source="fixture:strong", at="t")
    assert effective_control_knobs(strong, current_model="model-a").tier == "strong"
    assert effective_control_knobs(strong).tier == "unknown"
    assert effective_control_knobs(strong, current_model="model-b").tier == "unknown"

    incomplete = ModelProfile(
        model="model-a",
        tier="strong",
        scores={"json_stability": True},
        knobs=control_knobs("strong"),
    )
    knobs = effective_control_knobs(incomplete, current_model="model-a")
    assert knobs.tier == "unknown"
    assert knobs.max_repairs == 1
    assert knobs.write_granularity == "file"
    assert knobs.strict_schema is True


def test_effective_knobs_downgrade_tier_score_conflict():
    conflicting = ModelProfile(
        model="conflicting-model",
        tier="weak",
        scores={
            "json_stability": True,
            "boundary_follow": True,
            "instruction_follow": True,
        },
        knobs=control_knobs("strong"),
    )

    knobs = effective_control_knobs(conflicting, current_model="conflicting-model")

    assert knobs.tier == "unknown"
    assert knobs.write_granularity == "file"
    assert knobs.strict_schema is True


def test_no_profile_applies_unknown_boundary():
    repairs, knobs, note = apply_knobs_to_open(
        max_repairs=9,
        max_repairs_explicit=True,
        profile=None,
    )

    assert repairs == 1
    assert knobs.write_granularity == "file"
    assert knobs.strict_schema is True
    assert "unknown" in note


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


def test_explicit_budget_cannot_exceed_tier_limit(tmp_path):
    (tmp_path / ".sopcontrol").mkdir()
    run_capability_eval(tmp_path, "m", fixture="weak")
    profile = load_profile(tmp_path)

    repairs, knobs, note = apply_knobs_to_open(
        max_repairs=5,
        max_repairs_explicit=True,
        profile=profile,
        current_model="m",
    )
    assert repairs == 1 and knobs.tier == "weak" and "weak" in note

    strong = build_profile("s", FIXTURES["strong"], source="fixture:strong", at="t")
    repairs, knobs, _ = apply_knobs_to_open(
        max_repairs=1,
        max_repairs_explicit=True,
        profile=strong,
        current_model="s",
    )
    assert repairs == 1 and knobs.tier == "strong"


def test_file_granularity_is_enforced_by_exact_submit_paths():
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
    assert decision.allowed and decision.to_status == TaskStatus.executing

    task.status = TaskStatus.executing
    rejected = evaluate_transition(task, "submit", changed_paths=["src/a.py"])
    assert not rejected.allowed
    assert "范围走私" in rejected.reason

    accepted = evaluate_transition(task, "submit", changed_paths=["src"])
    assert accepted.allowed and accepted.to_status == TaskStatus.verification_pending


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


def test_capability_compare_archives(tmp_path):
    (tmp_path / ".sopcontrol").mkdir()
    from sopcontrol.evals import run_capability_compare

    def fake_live(pid, prompt, root):
        return {
            "json_stability": '{"status": "ok"}',
            "boundary_follow": "src/allowed.py",
            "instruction_follow": "READY",
        }[pid]

    result = run_capability_compare(
        tmp_path, live="opencode", baseline_fixture="strong",
        live_model="demo", live_runner=fake_live,
    )
    assert result["entry"]["tier_match"] is True
    path = tmp_path / ".sopcontrol" / "capability-compare.yaml"
    assert path.exists() and "runs:" in path.read_text(encoding="utf-8")


def _write_test_registry(root):
    (root / ".sopcontrol" / "rules").mkdir(parents=True)
    (root / ".sopcontrol" / "rules" / "registry.yaml").write_text(
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


def test_cli_task_open_without_profile_persists_unknown_boundary(tmp_path):
    from sopcontrol.cli import main

    _write_test_registry(tmp_path)

    assert main([
        "task", "open", str(tmp_path),
        "--objective", "无画像任务",
        "--allow", "src/a.py",
        "--require-rule", "R-1",
        "--require-field", "status",
        "--max-repairs", "4",
    ]) == 0

    task_file = next((tmp_path / ".sopcontrol" / "tasks").glob("TASK-*.yaml"))
    data = yaml.safe_load(task_file.read_text(encoding="utf-8"))
    contract = data["contract"]
    assert contract["max_repairs"] == 1
    assert contract["write_granularity"] == "file"
    assert contract["strict_schema"] is True
    assert "无模型画像 tier=unknown" in contract["capability_note"]

    assert main(["task", "accept", "TASK-0001", str(tmp_path)]) == 0
    assert main([
        "task", "submit", "TASK-0001", str(tmp_path),
        "--changed", "src/a.py", "--field", "status=ok",
    ]) == 0

    (tmp_path / "src").mkdir()
    assert main([
        "task", "open", str(tmp_path),
        "--objective", "目录越界",
        "--allow", "src",
        "--require-rule", "R-1",
        "--require-field", "status",
    ]) == 2


def test_cli_capability_eval_and_task_open(tmp_path):
    from sopcontrol.cli import main

    _write_test_registry(tmp_path)
    (tmp_path / "src").mkdir()

    assert main(["capability-eval", "--model", "m", "--fixture", "fragile", str(tmp_path)]) == 0
    assert main([
        "task", "open", str(tmp_path),
        "--model", "m",
        "--objective", "接线 R-1",
        "--allow", "src",
        "--require-rule", "R-1",
    ]) == 0

    task_file = next((tmp_path / ".sopcontrol" / "tasks").glob("TASK-*.yaml"))
    data = yaml.safe_load(task_file.read_text(encoding="utf-8"))
    assert data["contract"]["max_repairs"] == 1
    assert data["contract"]["write_granularity"] == "prefer_file"

    assert main([
        "task", "open", str(tmp_path),
        "--model", "m",
        "--objective", "接线 R-1",
        "--allow", "src",
        "--require-rule", "R-1",
        "--max-repairs", "3",
    ]) == 0
    task_file2 = sorted((tmp_path / ".sopcontrol" / "tasks").glob("TASK-*.yaml"))[-1]
    data2 = yaml.safe_load(task_file2.read_text(encoding="utf-8"))
    assert data2["contract"]["max_repairs"] == 1

    assert main(["capability-eval", "--model", "m", "--fixture", "strong", str(tmp_path)]) == 0
    assert main([
        "task", "open", str(tmp_path),
        "--model", "other-model",
        "--objective", "换模不得继承 strong",
        "--allow", "src",
        "--require-rule", "R-1",
        "--require-field", "status",
    ]) == 2

    assert main(["capability-eval", "--model", "m", "--fixture", "weak", str(tmp_path)]) == 0
    assert main([
        "task", "open", str(tmp_path),
        "--model", "m",
        "--objective", "接线 R-1",
        "--allow", "src",
        "--require-rule", "R-1",
        "--require-field", "status",
    ]) == 2
