"""平台投影（B4）：把权威规则投影到 harness 的指导文件。

AGENTS.md 是投影不是权威（手册 8.2）：只替换带标记的自身小节，
不碰文件其余内容；投影漂移由重跑刷新。
"""
from __future__ import annotations

from pathlib import Path

from .model import Rule, RuleStatus
from .registry import Registry

SECTION_START = "<!-- sopcontrol:v1 -->"
SECTION_END = "<!-- /sopcontrol:v1 -->"

_ACTIVE = {RuleStatus.accepted, RuleStatus.compiled, RuleStatus.activated, RuleStatus.monitored}
_HARD = {"MUST", "MUST_NOT"}


def render_projection(rules: list[Rule], tasks: list | None = None) -> str:
    lines = [
        SECTION_START,
        "# SOP Control 规则投影（自动生成，勿手改）",
        "",
        "权威源: `.sopcontrol/rules/registry.yaml`；规则变更后运行 `sopctl project codex` 刷新本节。",
        "本节只是指导——真正的拦截在 git pre-push 钩子、CI gate 与 `sopctl gate`。",
        "",
    ]
    hard = [r for r in rules if r.status in _ACTIVE and r.modality.value in _HARD]
    if hard:
        lines.append("## 必须遵守的规则")
        for r in hard:
            bits = [f"[{r.rule_id}][{r.modality.value}] {r.statement}"]
            if r.consumer_markers:
                bits.append(f"（生产消费者标记: {', '.join(r.consumer_markers)}）")
            if r.legacy_markers:
                bits.append(f"（旧入口不得存活: {', '.join(r.legacy_markers)}）")
            lines.append("- " + " ".join(bits))
        lines.append("")
    if tasks:
        lines.append("## 任务状态（换会话/换模型先看这里——已交付任务不得重复执行副作用）")
        for t in tasks:
            lines.append(
                f"- {t.task_id} [{t.status.value}] {t.contract.objective[:50]}"
                + ("——已完成并经完成门验证，勿重做" if t.status.value == "delivered" else "")
            )
        lines.append("")
    lines += [
        "## 硬约束",
        "- 不得直接读写或修改 `.sopcontrol/` 内任何文件；一切经 `sopctl` 子命令。",
        "- 完成任务前运行 `sopctl gate`（若不在 PATH：`python -m sopcontrol.cli gate`）；"
        "fail 判定或账本篡改会阻断推送。",
        SECTION_END,
    ]
    return "\n".join(lines) + "\n"


def write_projection(root: Path) -> Path:
    """把投影合并进 AGENTS.md：只替换自身带标记小节，保留其余内容。"""
    rules = Registry(Path(root) / ".sopcontrol" / "rules" / "registry.yaml").load()
    from .task import TaskStore

    tasks = None
    try:
        tasks = TaskStore(root).list_all()
    except Exception:
        tasks = None
    section = render_projection(rules, tasks)

    agents = Path(root) / "AGENTS.md"
    if agents.exists():
        content = agents.read_text(encoding="utf-8")
        if SECTION_START in content:
            start = content.index(SECTION_START)
            end = content.index(SECTION_END) + len(SECTION_END)
            content = content[:start] + section.rstrip("\n") + content[end:]
        else:
            content = content.rstrip("\n") + "\n\n" + section
        agents.write_text(content, encoding="utf-8")
    else:
        agents.write_text(section, encoding="utf-8")
    return agents
