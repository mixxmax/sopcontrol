# Changelog

## Unreleased

### Added

- **下一刀（中途接入）**: `sopctl doctor` 末尾最多 3 步可执行下一步（武装 / 真规则 / enact·吸收·退场）
- **deliver 空间帧**: `task deliver` 成功后自动 `growth` 全量快照 + 对照上一帧变窄叙事（编年 `growth.deliver_measure`）
- **久悬 gap**: `documented_rule_no_consumer` 等 → `improve_entry`；约 6 轮仍缺消费者 → 额外 `retire_rule` 候选（仅建议 `rule suspend` / `deprecate`，不自动退场）

## 0.2.0 — 2026-09-02

First public-facing packaging of the living-project control plane.

### Added

- Living project loop: projection slices, chronicle, ambient growth, space measure (`growth measure|diff`)
- Mid-conversation model switch: `task rebind`, harness executor identity guard
- Disambiguation: `redundant_entry_point`, `candidate enact` → bounded delete-entry tasks
- Public shell: README quickstart, LIMITATIONS, examples/minimal, MIT LICENSE

### Notes

- Still **experimental**. Authority stays in `.sopcontrol/`; candidates never auto-promote.
- Not published to PyPI yet; install from git (see README).

## 0.1.0 — 2026-08

Vertical backbone: Rule / Evidence / Verdict, audit, gate, hooks, task machine, repair, multi-harness adapters, corpus + mutations.
