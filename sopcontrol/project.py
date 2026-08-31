"""平台投影（B4 / Phase 6）：把权威规则投影到各 harness 的指导文件。

投影不是权威（手册 8.2）：只替换带标记的自身小节，不碰文件其余内容。
同一内容可同步到 AGENTS.md（Codex/OpenCode）与 CLAUDE.md（Claude Code）。
"""
from __future__ import annotations

from pathlib import Path

from .model import Rule, active_rules
from .registry import Registry
from .task import LEGAL_ACTIONS

SECTION_START = "<!-- sopcontrol:v1 -->"
SECTION_END = "<!-- /sopcontrol:v1 -->"

# 目标文件 → 刷新提示里写的子命令名
PROJECTION_TARGETS = {
    "codex": ("AGENTS.md", "sopctl project codex"),
    "opencode": ("AGENTS.md", "sopctl project opencode"),  # OpenCode 优先读 AGENTS.md
    "claude": ("CLAUDE.md", "sopctl project claude"),
}

_HARD = {"MUST", "MUST_NOT"}


def render_projection(
    rules: list[Rule],
    tasks: list | None = None,
    *,
    refresh_hint: str = "sopctl project codex",
    maturity=None,
) -> str:
    """maturity 是 bootstrap.MaturityReport 或 None。

    为什么要进投影：模型看不见控制器内部状态，只看这一节。项目站在 L1 还是 L4
    决定了「没被拦下」意味着什么——L1 时门只会建议，此时把沉默当许可就是误读。
    只写等级与下一级缺口两行；五项秩序明细留给 `sopctl bootstrap`，投影是
    上下文预算，不是报告。
    """
    lines = [
        SECTION_START,
        "# SOP Control 规则投影（自动生成，勿手改）",
        "",
        f"权威源: `.sopcontrol/rules/registry.yaml`；规则变更后运行 `{refresh_hint}` 刷新本节。",
        "本节只是指导——真正的拦截在 git pre-push 钩子、CI gate、运行时 hook 与 `sopctl gate`。",
        "",
    ]
    if maturity is not None:
        lines.append(f"## 控制成熟度：{maturity.level} {maturity.level_desc}")
        lines.append(
            f"- 未达下一级 {maturity.next_rung}：{maturity.next_action}"
            if maturity.next_rung
            else "- 五项基本秩序全部有机制。"
        )
        lines.append("- 明细与依据: `sopctl bootstrap`。低于 L3 时门以建议为主，"
                     "沉默不等于许可。")
        lines.append("")
    hard = [r for r in active_rules(rules) if r.modality.value in _HARD]
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
        lines.append(
            "## 任务状态（换会话/换模型先看这里；以下即全量信息，无需再用命令查询任务）"
        )
        for t in tasks:
            action = LEGAL_ACTIONS[t.status][0]
            lines.append(f"- {t.task_id} [{t.status.value}] {t.contract.objective[:60]}")
            lines.append(
                f"  完成定义: {', '.join(t.contract.required_rules) or '（无）'} 全部 pass；"
                f"修复预算: {t.repair_count}/{t.contract.max_repairs}；合法动作: {action}"
            )
            if t.status.value == "delivered":
                lines.append("  ⚠ 此任务已完成并经完成门独立验证——不得重复执行其副作用，勿改相关文件")
        lines.append("")
    lines += [
        "## 硬约束",
        "- 不得直接读写或修改 `.sopcontrol/` 内任何文件；一切经 `sopctl` 子命令。",
        "- 完成任务前运行 `sopctl gate`（若不在 PATH：`python -m sopcontrol.cli gate`）；"
        "fail 判定或账本篡改会阻断推送。",
        "- 用户若说「只讨论不修改」，不得改任何文件（会话意图 discuss_only）。",
        "",
        "## 与控制器配合（SKILL 要点）",
        "- 先读本投影；规则/账本/任务变更只经 `sopctl`，禁止手改 `.sopcontrol/`。",
        "- `task submit` 若契约有 MUST 字段，必须带齐 `--field key=value`（漏字段会被拒）。",
        "- 不要用自报「已完成」代替 `task verify` / `gate`；已 `delivered` 的任务勿重做副作用。",
        "- 不要卸 hook/插件（提权，需人工）。日用全序见仓库 `PLAYBOOK.md` / `SKILL.md`。",
        SECTION_END,
    ]
    return "\n".join(lines) + "\n"


def _load_maturity(root: Path):
    """读当前成熟度；读不出来就返回 None（投影退化为无该节，而不是报错）。

    写入与校验必须走同一个函数，否则 check_projections 会把「写的时候带了等级、
    校验的时候没带」永久报成 stale。
    """
    from .bootstrap import assess_maturity

    try:
        return assess_maturity(Path(root))
    except OSError:
        return None


def merge_section(path: Path, section: str) -> Path:
    """把投影小节合并进目标文件：只替换自身标记区间。"""
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if SECTION_START in content:
            if SECTION_END not in content:
                raise ValueError(f"{path} 含 {SECTION_START} 但缺少 {SECTION_END}，拒绝合并")
            start = content.index(SECTION_START)
            end = content.index(SECTION_END) + len(SECTION_END)
            content = content[:start] + section.rstrip("\n") + content[end:]
        else:
            content = content.rstrip("\n") + "\n\n" + section
        path.write_text(content, encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(section, encoding="utf-8")
    return path


def _projection_inputs(root: Path):
    """投影的全部输入源。写和查必须走同一条路径，否则 check 会报永久漂移。"""
    rules = Registry(Path(root) / ".sopcontrol" / "rules" / "registry.yaml").load()
    from .bootstrap import assess_maturity
    from .task import TaskStore

    try:
        tasks = TaskStore(root).list_all()
    except Exception:
        tasks = None
    return rules, tasks, assess_maturity(root, rules)


def write_projection(root: Path, target: str = "codex") -> Path:
    """按 harness 目标写入投影文件。"""
    if target not in PROJECTION_TARGETS:
        raise ValueError(f"未知投影目标 {target!r}；可选: {', '.join(PROJECTION_TARGETS)}")
    filename, hint = PROJECTION_TARGETS[target]
    rules, tasks, maturity = _projection_inputs(root)
    section = render_projection(rules, tasks, refresh_hint=hint, maturity=maturity)
    return merge_section(Path(root) / filename, section)


def write_all_projections(root: Path) -> list[Path]:
    """同步写入 AGENTS.md 与 CLAUDE.md（codex/opencode 共用 AGENTS.md，只写一次）。"""
    written: list[Path] = []
    seen: set[str] = set()
    rules, tasks, maturity = _projection_inputs(root)
    section = render_projection(
        rules, tasks, refresh_hint="sopctl project all", maturity=maturity
    )
    for _name, (filename, _hint) in PROJECTION_TARGETS.items():
        if filename in seen:
            continue
        seen.add(filename)
        written.append(merge_section(Path(root) / filename, section))
    return written


def _expected_section(root: Path, refresh_hint: str) -> str:
    rules, tasks, maturity = _projection_inputs(root)
    return render_projection(rules, tasks, refresh_hint=refresh_hint, maturity=maturity)


def _disk_section(path: Path) -> str | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    if SECTION_START not in content or SECTION_END not in content:
        return None
    start = content.index(SECTION_START)
    end = content.index(SECTION_END) + len(SECTION_END)
    return content[start:end]


def check_projections(root: Path) -> list[dict]:
    """对比磁盘投影小节与当前 registry/任务应生成的内容；漂移则回报。"""
    # AGENTS.md 用 project all 提示；CLAUDE.md 同
    targets = [
        (Path(root) / "AGENTS.md", "sopctl project all"),
        (Path(root) / "CLAUDE.md", "sopctl project all"),
    ]
    # 去重文件
    seen: set[str] = set()
    reports: list[dict] = []
    for path, hint in targets:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        expected = _expected_section(root, hint).rstrip() + "\n"
        disk = _disk_section(path)
        if disk is None:
            reports.append({
                "path": path.name,
                "status": "missing",
                "detail": "无投影小节或文件不存在",
            })
            continue
        # 规范化尾空白再比
        ok = disk.rstrip() + "\n" == expected
        reports.append({
            "path": path.name,
            "status": "ok" if ok else "stale",
            "detail": "与 registry 一致" if ok else "已过期：请运行 sopctl project all",
        })
    return reports
