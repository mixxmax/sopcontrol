# SOP Control

**Experimental but real** — a **model-neutral control plane** that lives *in your project*, not in a chat transcript.

> Make product intent executable, verifiable, and recoverable across model switches — by growing a finite, editable space of determined facts, not by stacking more “please don’t” prompts.

**Status:** v0.2.0 · vertical backbone + living-project loop · [LIMITATIONS](LIMITATIONS.md) · [CHANGELOG](CHANGELOG.md)


---

## What it is / isn’t

| Is | Isn’t |
|----|--------|
| Project-local Rule / Evidence / Verdict bus | A guarantee that models never err |
| Ambient discovery of gaps & bypasses | Auto-writing permanent rules without you |
| Cross-session / cross-model recovery | Cloud policy SaaS / SSO admin console |
| Human-gated authorize & prune | Another prompt Skill that “remembers” for you |

Philosophy (short): **eliminate ambiguity** (prefer deleting old entry points) over squeezing error with more guards; **authority lives in the project**; growth can be ambient, **authorization stays human**.

---

## 5-minute quickstart

```bash
# Python >= 3.10
git clone https://github.com/mixxmax/sopcontrol.git && cd sopcontrol
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
sopctl --help

# Self-check (this repo)
sopctl vertical-check .
# Full suite (includes pytest):
./scripts/vertical-check.sh
```

**On any other project:**

```bash
pip install -e /path/to/sopcontrol
# or: pip install "git+https://github.com/mixxmax/sopcontrol.git"
cd /path/to/your-app
sopctl init .
sopctl identity init .
sopctl hook install .                  # pre-push → same gate as CI
sopctl project all .                  # project AGENTS.md / CLAUDE.md (advisory)

sopctl rule add --id DEMO-001 \
  --statement "变更必须经统一入口" \
  --modality MUST --status proposed \
  --source-ref README.md --source-type document \
  --consumer-marker demo_gate
sopctl rule accept DEMO-001 .

sopctl audit .                        # observe gaps; ambient growth runs on persist
sopctl gate .                         # fail blocks; gap warns
sopctl growth status .                # pending candidates (discovery is ambient)
sopctl growth measure .               # ambiguity_index snapshot
```

Minimal scripted demo (temp copy of a fixture): [`examples/minimal`](examples/minimal).

---

## How the plane works (one picture)

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

Day-to-day ops: [`PLAYBOOK.md`](PLAYBOOK.md) · Agent card: [`SKILL.md`](SKILL.md)

---

## Harness compatibility

| Harness | Interception | Live status |
|---------|--------------|-------------|
| **OpenCode** | Runtime plugin | Live-verified |
| **Codex** | Projection + `sopctl wrap` post-gate | Live-verified |
| **Claude Code** | PreToolUse protocol | Adapted; live depends on API key |

```bash
sopctl hook opencode .
sopctl project codex .
sopctl wrap codex . -- <your codex args>
sopctl hook claude .
```

Mid-conversation model switch: `sopctl task rebind TASK-xxxx --model <NEW>`  
(Harness denies Write/Edit/Bash when payload `model` ≠ bound executor.)

---

## Core commands

| Command | Role |
|---------|------|
| `sopctl audit` / `gate` / `self-test` | Observe · end gate · penetration drill |
| `sopctl rule …` | Lifecycle: add/accept/suspend/narrow/deprecate |
| `sopctl task …` | Contract → submit → verify → deliver · `rebind` |
| `sopctl growth status\|measure\|diff` | Ambient growth + whether space *narrowed* |
| `sopctl candidate enact … --allow …` | Turn `delete_entry` into a bounded removal task |
| `sopctl chronicle` | How we got here (for the next model) |
| `sopctl inventory` | Controlled vs legacy vs parallel state |

---

## Design docs (deep)

| Doc | Content |
|-----|---------|
| [`DESIGN.md`](DESIGN.md) | Why the code is shaped this way |
| [`docs/SOP_Control_活在项目里的可进化规则空间技术手册_2026-08-31.md`](docs/SOP_Control_活在项目里的可进化规则空间技术手册_2026-08-31.md) | Living-space philosophy |
| [`docs/SOP_Control_产品与技术架构手册_2026-08-23.md`](docs/SOP_Control_产品与技术架构手册_2026-08-23.md) | Product architecture |
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

**Dogfood note:** this repository’s own `.sopcontrol/tasks/` may contain in-progress local tasks from self-application. Treat fixtures under `corpus/fixtures/` as the clean demos; run `examples/minimal` for a throwaway walkthrough.

---

## License

MIT — see [`LICENSE`](LICENSE).
