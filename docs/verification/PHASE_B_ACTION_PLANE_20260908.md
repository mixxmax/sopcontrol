# Phase B — Action Plane + full tool ingest (2026-09-08)

Implements Phase B of the universal attach handbook.

## What landed

| Piece | Role |
| --- | --- |
| `sopcontrol/action_model.py` | ActionEnvelope / ActionDecision / ActionResult |
| `sopcontrol/action_classifier.py` | Claude/OpenCode/MCP tool → surface+operation |
| `sopcontrol/action_plane.py` | `build_envelope`, `evaluate_action` (pure), `commit_action_result` |
| `sopcontrol/harness.check_tool_call` | Compatibility wrapper → Action Plane; `observe` maps to wire `allow` |
| `sopctl harness-check` | Commits digest-only ControlEvent for every tool, including unknown |

## Surfaces

`filesystem_write` · `filesystem_read` · `shell` · `search` · `browser` · `network` · `mcp` · `unknown`

Read / search / browser / network / mcp / unknown → **observe** (visible event, not blocked).  
Write / shell keep existing GUARD IDs and fail-closed semantics.

## Privacy

Receipts store digests, target path/command prefix, and field **sizes** — never file bodies, cookies, or tokens.

## Tests

`tests/harness/test_action_plane.py` plus existing harness guard suites.
