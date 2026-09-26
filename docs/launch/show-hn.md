# Show HN draft

> Draft for review. The shell bypasses found before launch are fixed in the next release
> (see `prelaunch-checklist.md`); post after that release is tagged.

## Title (pick one, all ≤ 80 characters)

1. `Show HN: SOP Control – a local, zero-LLM rule boundary for coding agents` (72)
2. `Show HN: I made my coding agents stop reopening decisions I had already settled` (79)

Option 1 says what it is; option 2 says the pain. HN tends to reward the plain one.

## URL

https://github.com/mixxmax/sopcontrol

## Text

I build a fairly large side project with coding agents (Claude Code, Codex, OpenCode). The failures that cost me the most were not bad code. They were agents re-deciding things I had already settled:

- I say "let's just discuss this", and the agent starts editing files.
- A rule we agreed on last week gets reinterpreted after I switch models or sessions.
- "Done" is reported when the checks never actually ran.
- `git push --no-verify` shows up when a hook gets in the way.

Prompt files help, but they are suggestions. So I wrote SOP Control, a small control plane that lives in the repository:

- Rules live in `.sopcontrol/` next to the code, with provenance: which sentence they came from, who confirmed them, what they apply to, which revision. Nothing a model proposes becomes a rule until a human confirms it.
- Every tool call from the agent goes through a local check first (a Claude Code PreToolUse hook, an OpenCode plugin, or a wrapper). The hot path is deterministic Python: no LLM calls, no network.
- `git push` runs a gate that fails on a failed verdict or a tampered evidence ledger.
- Tasks separate "the model says it's done" from "verified".

There is a 60-second demo that needs no model and no API key. It feeds `sopctl` the exact payloads Claude Code sends to its hook and prints the real decisions:

    git clone https://github.com/mixxmax/sopcontrol && cd sopcontrol
    python3 -m venv .venv && . .venv/bin/activate && pip install -e .
    scripts/demo.sh --en

I run it inside JobsFlow, a job-search pipeline I built for Hong Kong: scans, tracker writes, application materials and apply checks all pass through it, with one-shot capability tickets for writes. The most useful lesson so far was about the control layer itself. My test suite ran with enforcement switched off, so a ticket bug that made one command fail under enforcement went unnoticed while every test stayed green. A control layer that is off in tests is not tested.

Before posting I tried to break it the obvious ways and fixed what I found: while a discuss-only lock is on, Bash only runs a read-only allow-list; an agent cannot lift the lock itself; and deleting the pre-push hook, `core.hooksPath`, or `git -C . push` no longer route around the gate. What it still does not do (Beta): Claude Code does not yet set the discuss lock from your messages automatically (you set it with one command), and out-of-scope writes are rejected when the task is submitted, not at write time. It constrains a cooperating agent; it is not a sandbox.

I would love feedback on two things: which rules you would actually want enforced for your agents, and whether the "rule space vs solution space" framing makes sense or just adds vocabulary.

---

## Notes for posting

- Post on a weekday morning US Eastern time. Stay around for the first two hours and answer every question.
- Lead replies with the demo command and the honest limits; do not argue about sandboxes, agree that it is not one.
- If someone finds a bypass, thank them and open an issue in public. That earns more trust than the launch itself.
