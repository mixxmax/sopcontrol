# SOP Control

**[English](README.md)** · **[中文](README_ZH-CN.md)**

<p align="center">
  <img src="docs/assets/sopcontrol-living-boundary.gif" alt="Living project boundary — a finite ring whose edge keeps changing" width="960" />
</p>

<p align="center">
  <a href="https://github.com/mixxmax/sopcontrol"><img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/Version-v0.2.0-blue.svg" alt="Version"></a>
</p>

**Stop constraining coding agents with ever-longer prompts. Put architectural discipline into your Git repository.**

> **SOP Control** is a **model-neutral local control plane** for coding agents (Claude Code, OpenCode, Codex, Cursor). It does not burn your tokens acting as a middleman. Instead, it uses deterministic local gates (Git Hooks / Tool interception) and objective code evidence to prevent models from bypassing architectural invariants across chat sessions, model switches, and legacy code traps.

**Status:** v0.2.0 · Living-project loop · [LIMITATIONS](LIMITATIONS.md) · [CHANGELOG](CHANGELOG.md) · [PLAYBOOK](PLAYBOOK.md)

---

## ⚡ The Pain: Drift vs Control (Before / After)

When capable models operate without physical repo constraints, the biggest risk isn't merely "syntax errors"—it is **freely wandering inside an unconstrained ambiguity space**:

### Real Scenario: All data mutations MUST go through `AuditLog`

* ❌ **Traditional Approach (Prompt-Only Constraints)**:
  * **Practice**: You fill the System Prompt with *"Must call safe_update(), never write directly to DB"*.
  * **The Drift**: When the agent encounters a complex bugfix or discovers an obsolete `raw_update()` function, it bypasses the safety wrapper or deletes assertions just to make tests green.
  * **Consequence**: Delivery *looks* successful on paper, but core product invariants quietly rot. Start a new session or switch models, and previous prompt agreements evaporate.

* ✅ **SOP Control Approach (Local Control Plane Takeover)**:
  1. **Rules live in Git**: Rule `RULE-001` is committed in `.sopcontrol/`, declaring required consumer markers;
  2. **Static absorption audit**: `sopctl audit` scans the AST (TS / Go / Rust / Python), flags unconstrained `raw_update()`, and raises a gap warning;
  3. **Deterministic physical gate**: `sopctl gate` blocks unauthorized changes in Pre-push / CI and Harness runtimes (zero token cost);
  4. **Disambiguation (Enact)**: Guides the model to run `sopctl candidate enact` to generate a bounded task that **physically deletes `raw_update()`**, permanently shrinking the model's error space.

---

## 🛠️ Architecture & Engineering Loop

```text
[ Developer / CI ]        [ Production & Legacy Code ]
       │                                │
       ▼                                ▼
.sopcontrol/ (Local Truth) ◄───  sopctl audit (Detect parallel states & bypasses)
       │                                │
       ├─► Compile Projections ──► Injected into AGENTS.md / CLAUDE.md (<1500 Tokens)
       │
       └─► Deterministic Gates ──► Git Hooks / Harness Interception (Zero Tokens)
                                        │
                                        ▼
                           Block unauthorized writes / Force deleting legacy paths
```

### 1. Task Contracts & Anti-Smuggling (Task Contract)
Agents must operate within bounded task contracts specifying `allowed_writes` (file write whitelist) and `require_rules`. Unauthorized file touches or missing verifications are rejected immediately.

### 2. Real Absorption Auditing (Absorption Audit)
Rules never stay merely on paper. The system uses AST parsers (TS / Go / Rust / Python) to independently verify whether a rule has real production callers (`consumer_markers`) and test coverage (`documented` → `wired` → `wired_and_tested`).

### 3. Model Switch Safety (`task rebind`)
Switching models mid-task often accidentally broadens permissions. SOP Control enforces `task rebind`: permissions for new models **only tighten, never loosen** (taking the most conservative intersection).

### 4. Ambiguity Space Measurement (Ambiguity Index)
Track repository ambiguity via `sopctl growth measure` (active bypasses + parallel states). Verify that refactoring truly **narrowed** the model's wanderable decision space using `sopctl growth diff`.

---

## 📖 Terminology Mapping

To make adoption seamless, here is how SOP Control concepts map to standard engineering terms:

| Project Term | Common Engineering Concept | What Problem It Solves |
| :--- | :--- | :--- |
| **Eliminate Ambiguity** | Physically deleting legacy dead code & bypasses | Leaves no physical loopholes for models to bypass rules |
| **Absorption Audit** | Static checks ensuring rules have real code callers | Prevents architectural guidelines from rotting into empty docs |
| **Task Rebind** | Re-aligning permissions to minimum intersection upon model switch | Prevents security degradation when switching models mid-task |
| **Task Contract** | Sandboxed ticket with strict file write whitelists & rules | Prevents agents from altering unrelated infrastructure files |
| **Chronicle** | Git-persisted decision log of rules and invariant changes | Explains "how we got here" to the next developer / model session |

---

## 🚀 Quickstart

### Option A: 2-Minute Minimal Demo

Experience a physical gate blocking an agent violation without setting up a full project:

```bash
git clone https://github.com/mixxmax/sopcontrol.git && cd sopcontrol
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
sopctl gate examples/minimal
```

---

### Option B: Progressive Adoption in Your Project (3 Steps)

#### Step 1. Zero-Intrusion Healthcheck (Diagnostic Tool Only)

```bash
pip install sopcontrol   # or: pip install "git+https://github.com/mixxmax/sopcontrol.git"
cd /path/to/your-app

sopctl init .
sopctl doctor .          # Diagnoses parallel states & open bypasses; outputs next moves
```

#### Step 2. Lock Down Your First Core Rule

```bash
sopctl rule add --id RULE-001 \
  --statement "Data mutations must go through unified preview_gate" \
  --modality MUST --status proposed \
  --source-ref README.md --consumer-marker preview_gate

sopctl rule accept RULE-001 .
```

#### Step 3. Mount Git Gate & Start Bounded Tasks

```bash
# 1. Install pre-push gate hook
sopctl hook install .

# 2. Open a bounded task for your agent (restricted to service.py)
sopctl task open . --model claude-3-7-sonnet --objective "Refactor billing logic" \
  --allow src/service.py --require-rule RULE-001

# 3. Agent submits changes upon completion
sopctl task submit <TASK-ID> . --changed src/service.py --model claude-3-7-sonnet
sopctl task verify <TASK-ID> .
sopctl task deliver <TASK-ID> .

# 4. Final verification gate (unified local hook and CI check)
sopctl gate .
```

---

## 🔌 Supported Agent Harnesses

| Harness | Interception Mechanism | Status |
| :--- | :--- | :--- |
| **OpenCode** | Runtime Plugin Interception | ✅ Live-verified |
| **Codex / Cursor** | Thin Projection + `sopctl wrap` Gate | ✅ Live-verified |
| **Claude Code** | PreToolUse Protocol Adapter | ✅ Adapted (Tool-level interception) |

---

## 📌 Core Command Cheat Sheet

| Command | Role & Description |
| :--- | :--- |
| `sopctl doctor .` | **Health check & next moves** (lightweight recommendations) |
| `sopctl audit .` | **Absorption audit** (checks if MUST rules are wired and tested) |
| `sopctl gate .` | **Final gate** (unified blocker for local pre-push and CI) |
| `sopctl rule ...` | Rule lifecycle (`add` / `accept` / `suspend` / `narrow` / `deprecate`) |
| `sopctl task ...` | Task contracts (`open` / `submit` / `verify` / `deliver` / `rebind`) |
| `sopctl growth measure / diff` | Space snapshot & ambiguity reduction diffs |
| `sopctl candidate enact ...` | One-command task creation to physically delete legacy bypasses |
| `sopctl chronicle` | Inspect architectural decision history & evolution |

---

## 📖 Deep-Dive Documentation

* 🏛️ [Design Decisions (DESIGN.md)](DESIGN.md) — Architectural rationale: three primitives and deterministic constitution
* 📘 [Playbook (PLAYBOOK.md)](PLAYBOOK.md) — Daily end-to-end operation SOP & advanced flows
* ⚠️ [Residual Risks (RESIDUAL_RISKS.md)](RESIDUAL_RISKS.md) — Honest disclosure of known bypass families & defense boundaries
* 🗺️ [Roadmap (ROADMAP.md)](ROADMAP.md) — Authoritative progress log & future milestones
* 🤖 [Agent Skill (SKILL.md)](SKILL.md) — Context card injected into coding agents
* 🚫 [Limitations (LIMITATIONS.md)](LIMITATIONS.md) — Explicitly states out-of-scope boundaries

---

## 💻 Development & Testing

```bash
git clone https://github.com/mixxmax/sopcontrol.git && cd sopcontrol
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run full test suite & self-checks
pytest -q
./scripts/vertical-check.sh
```

## 📄 License

Distributed under the [MIT License](LICENSE).
