# SOP Control

**[English](README.md)** · **[中文](README_ZH-CN.md)**

<p align="center">
  <img src="docs/assets/sopcontrol-living-boundary.gif" alt="Living project boundary — a finite ring whose edge keeps changing" width="960" />
</p>

**Experimental but real** — a **model-neutral control plane** that lives *in your project*, not in a chat transcript.

> Make product intent **executable, verifiable, and recoverable across model switches** — by growing a **finite, editable space of determined facts**, not by stacking more “please don’t” prompts.

**Status:** v0.2.0 · living-project loop · [LIMITATIONS](LIMITATIONS.md) · [CHANGELOG](CHANGELOG.md) · [PLAYBOOK](PLAYBOOK.md)

---

## The pain (why this philosophy exists)

Without a project-local SOP / control plane, a capable model does not merely “make mistakes.” It executes inside an **unbounded ambiguity space**:

| What happens | Consequence |
|--------------|-------------|
| Intent lives only in chat | New session / new model **forgets**; the same MUST is re-negotiated or dropped |
| Many paths still “work” | Preview skipped, legacy writer, parallel state files — delivery **looks done** while product invariants rot |
| You add more prompts & guards | Error surface shrinks on paper; **bypass surface stays open** — the model walks around the fence |
| Mid-task model switch | Reachable actions often **widen**; prior tightenings do not travel with the new executor |
| No absorption check | “We said preview-before-write” never becomes a **consumer in code** — docs and reality diverge |

That failure mode is the starting point of the design: **not** “make the model obey harder,” but **make the wanderable space finite, visible, and editable in the repo** — so the next model inherits the same world.

Most “AI coding control” then fails in one of two ways *after* noticing the pain:

1. **Prompt theater** — longer system prompts and Skills that evaporate when you switch chat, model, or machine.
2. **Guard inflation** — more MUST_NOT / blockers while **old entry points and parallel states stay alive**. The model still has somewhere else to go; you just taught it more sentences to ignore.

SOP Control takes a different bet:

| Principle | Meaning in practice |
|-----------|---------------------|
| **Eliminate ambiguity first** | Prefer **deleting** redundant paths over adding another forbid-rule. Maturity = fewer open bypasses, not more rules. |
| **Authority lives in the project** | Truth is `.sopcontrol/` (rules, tasks, evidence, chronicle) — not the model’s memory. |
| **Ambient discovery, human authorization** | Audits/denials can *observe* and propose Candidates; **only you** accept rules, enact deletes, or deprecate. |
| **Space is measurable and two-way** | `ambiguity_index` (open bypasses + parallel state) can **narrow** after disambiguation or **widen** if mess accumulates. |
| **Spine uses zero LLM** | Verdict / harness decisions are deterministic. The control plane must not burn your tokens to “manage” itself. |
| **Cooperating operator** | Default trust: you on your machine. Known bypasses are listed honestly in [RESIDUAL_RISKS](RESIDUAL_RISKS.md), not papered over. |

**Thinking logic in one line:** shrink the *decision space* the model can wander in — so the next session, and the next model, inherit the same world.

---

## What it is / isn’t

| Is | Isn’t |
|----|--------|
| Project-local Rule / Evidence / Verdict bus | A guarantee that models never err |
| Ambient discovery of gaps & bypasses | Auto-writing permanent rules without you |
| Cross-session / cross-model recovery | Cloud policy SaaS / SSO admin console |
| Human-gated authorize & prune | Another prompt Skill that “remembers” for you |
| Mid-adoption friendly (`doctor` next moves) | Greenfield-only scaffolding |

---

## Distinctive control features

| Capability | What you get |
|------------|----------------|
| **Rule lifecycle** | add → accept → suspend / narrow / deprecate (two-phase for permanent exit) |
| **Absorption audit** | Did the MUST actually get a **production consumer** (and tests)? gap vs pass is visible |
| **Gate + pre-push** | Fail blocks; gap warns — same door for local hook and CI |
| **Task contracts** | Bounded writes, required fields/rules, verify/deliver; repair budget from capability tier |
| **Ambient growth** | Findings & harness denials accumulate Candidates without you “pushing discovery” |
| **Disambiguation enact** | `candidate enact … --allow …` → bounded **delete-bypass** task (not another guard) |
| **Space measure** | `growth measure` / `diff` — did the space *narrow*? |
| **Chronicle** | “How we got here” for the next model/session |
| **Thin projection** | AGENTS.md / CLAUDE.md slices with token/line budgets (energy) |
| **Light doctor** | Default next-3-steps **without** re-scanning the whole tree; `--full` when needed |
| **Executor identity** | Mid-task model mismatch on Write/Edit/Bash → deny + `task rebind` |

---

## Model switches stay effective

Switching models mid-work usually **widens** reachable actions (new model, old loose context). SOP Control counters that:

1. **Project state does not move** — rules/tasks/chronicle stay on disk.
2. **`task rebind --model <NEW>`** — knobs only **tighten** (intersection with the more conservative profile); never inherit the previous executor’s looseness.
3. **Harness check** — if the tool payload declares `model` and it ≠ the bound executor, write/bash is **denied** until rebind.
4. **Projection + chronicle** — the new model reads the same recovery protocol and “why we’re here,” not a stale chat.

Harness depth differs (honestly):

| Harness | Interception | Live status |
|---------|--------------|-------------|
| **OpenCode** | Runtime plugin | Live-verified |
| **Codex** | Projection + `sopctl wrap` post-gate | Live-verified |
| **Claude Code** | PreToolUse protocol | Adapted; live depends on API key |

Same **world**; not always the same **hook depth**.

---

## What “working” looks like (effects)

These are **mechanism + dogfood** results, not marketing SLAs:

| Evidence | Outcome |
|----------|---------|
| Product sim (`scripts/verify-product-sim.sh`) | After removing a legacy bypass: `ambiguity_index` **1→0**; enact + rebind + harness mismatch deny all hold |
| JobsFlow mid-adoption | Rule `JF-PREVIEW-001` moved from **gap/documented** → **pass / wired_and_tested** by wiring real `require_preview` on the push write boundary |
| Energy | `doctor` light ≪ `--full` (often ~4–10× on large trees); projection section budgeted ~≤1500 tokens |
| Regression | `self-test` penetration + corpus mutations + full pytest suite |

Reports: [`docs/verification/`](docs/verification/) (SIM_*, REDTEAM_*).

**Still human:** multi-week “does my team feel less chaos?” — use the plane on a real repo; weekly `growth measure` / `diff`.

---

## Quickstart

```bash
# Python >= 3.10
git clone https://github.com/mixxmax/sopcontrol.git && cd sopcontrol
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
sopctl --help

# Self-check on this repo
sopctl vertical-check .
./scripts/vertical-check.sh          # stricter (includes pytest)
bash scripts/verify-product-sim.sh   # throwaway narrow-space sim
```

**On any other project (including mature ones):**

```bash
pip install -e /path/to/sopcontrol
# or: pip install "git+https://github.com/mixxmax/sopcontrol.git"
cd /path/to/your-app
sopctl init .
sopctl identity init .
sopctl hook install .
sopctl project all .
sopctl doctor .                      # light: next 3 moves, no full-tree audit

sopctl rule add --id DEMO-001 \
  --statement "Changes must go through the unified entry" \
  --modality MUST --status proposed \
  --source-ref README.md --source-type document \
  --consumer-marker demo_gate
sopctl rule accept DEMO-001 .

sopctl audit . --compact             # observe; ambient growth on persist
sopctl growth measure .              # ambiguity_index snapshot
sopctl growth diff .
sopctl candidate enact CAND-… . --allow path/to/bypass.py   # when delete_entry appears
sopctl gate .
```

Day-to-day order: [`PLAYBOOK.md`](PLAYBOOK.md). Minimal fixture walkthrough: [`examples/minimal`](examples/minimal).

```text
docs / conversation / runtime denials
        ↓  observe (ambient)
   Candidates (no authority)
        ↓  human authorize / enact / prune
   Rules + tasks in .sopcontrol/
        ↓  compile
   projection · harness check · gate · chronicle
        ↓
   new session / new model restores the same world
```

---

## Core commands

| Command | Role |
|---------|------|
| `sopctl doctor` / `--full` | Health + **next moves** (light by default) |
| `sopctl audit` / `gate` / `self-test` | Observe · end gate · penetration drill |
| `sopctl rule …` | Lifecycle: add/accept/suspend/narrow/deprecate |
| `sopctl task …` | Contract → submit → verify → deliver · **`rebind`** |
| `sopctl growth status\|measure\|diff` | Ambient growth + whether space *narrowed* |
| `sopctl candidate enact … --allow …` | Bounded delete-bypass task |
| `sopctl chronicle` | How we got here |
| `sopctl inventory` | Controlled vs legacy vs parallel state |

Product adversarial checklist (not external attacker red-team): [`docs/verification/REDTEAM_CHECKLIST.md`](docs/verification/REDTEAM_CHECKLIST.md).

---

## Design docs (deep)

| Doc | Content |
|-----|---------|
| [`DESIGN.md`](DESIGN.md) | Why the code is shaped this way |
| [`docs/SOP_Control_活在项目里的可进化规则空间技术手册_2026-08-31.md`](docs/SOP_Control_活在项目里的可进化规则空间技术手册_2026-08-31.md) | Living-space philosophy (ZH) |
| [`docs/SOP_Control_产品与技术架构手册_2026-08-23.md`](docs/SOP_Control_产品与技术架构手册_2026-08-23.md) | Product architecture (ZH) |
| [`RESIDUAL_RISKS.md`](RESIDUAL_RISKS.md) | Known bypass families |
| [`ROADMAP.md`](ROADMAP.md) | Authoritative progress log |

---

## Develop

```bash
pip install -e ".[dev]"
pytest -q
./scripts/vertical-check.sh
```

CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) · [`.github/workflows/gate.yml`](.github/workflows/gate.yml)

**Dogfood note:** this repo’s `.sopcontrol/tasks/` may contain local self-application noise. Prefer `corpus/fixtures/` and `examples/minimal` for clean demos.

---

## License

MIT — see [`LICENSE`](LICENSE).
