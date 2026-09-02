"""intake（意图编译器 v0）：候选提取确定性、强度建议、幂等、永不写注册表。"""
import shutil

import yaml

from sopcontrol.cli import main


def test_intake_extracts_candidates_without_touching_registry(tmp_path, capsys):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/jobflow-preview", work)
    # 夹具目录可能残留 gitignore 的生长候选；intake 测的是文档提取，不是 growth
    candidates_path = work / ".sopcontrol" / "rules" / "candidates.yaml"
    candidates_path.unlink(missing_ok=True)

    assert main(["intake", str(work)]) == 0
    candidates = yaml.safe_load(candidates_path.read_text(encoding="utf-8"))
    policy = [c for c in candidates if c.get("kind", "policy") == "policy"]
    assert len(policy) == 1  # "不得为仅预览的岗位分配材料编号"（PUSH-001 语句已登记，被去重）
    assert policy[0]["suggested_modality"] == "MUST_NOT"
    assert policy[0]["status"] == "observed"

    registry_text = (work / ".sopcontrol" / "rules" / "registry.yaml").read_text(encoding="utf-8")
    assert "不得为仅预览" not in registry_text  # Candidate 永不进注册表

    assert main(["intake", str(work)]) == 0  # 幂等
    out = capsys.readouterr().out
    assert "没有新的候选规则" in out
