"""harness eval 测试：注入假 runner（不跑真实模型），验证画像归档与失败判定。"""
import yaml

from sopcontrol.evals import build_canary, run_harness_eval


def test_canary_has_fail_rule(tmp_path):
    canary = build_canary(tmp_path / "canary")
    registry = (canary / ".sopcontrol" / "rules" / "registry.yaml").read_text(encoding="utf-8")
    assert "old_ship" in registry  # legacy 存活 → gate 必 fail → 演习可断言阻断
    assert (canary / "src" / "legacy_path.py").exists()


def fake_runner(passed: bool):
    def run(canary, python):
        return {"drill": "fake:drill", "passed": passed, "exit_code": 0 if passed else 1,
                "evidence": "fake evidence"}
    return run


def test_eval_results_archived_to_profile(tmp_path):
    profile = tmp_path / "harness-profile.yaml"
    profile.write_text(yaml.safe_dump({"opencode": {"live_verified": False}}), encoding="utf-8")

    results = run_harness_eval("opencode", profile, runner=fake_runner(True))
    assert results[0]["passed"] and results[0]["at"]

    data = yaml.safe_load(profile.read_text(encoding="utf-8"))
    entry = data["opencode"]
    assert entry["live_verified"] is True
    assert entry["eval_history"][-1]["drill"] == "fake:drill"

    # 失败演习不点亮 live_verified，历史如实累积
    run_harness_eval("opencode", profile, runner=fake_runner(False))
    data = yaml.safe_load(profile.read_text(encoding="utf-8"))
    assert data["opencode"]["live_verified"] is True  # 历史成功保持
    assert len(data["opencode"]["eval_history"]) == 2
    assert data["opencode"]["eval_history"][-1]["passed"] is False
