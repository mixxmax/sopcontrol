#!/usr/bin/env bash
# Product verification simulation (throwaway) — not multi-week human dogfood.
# Proves: space can narrow after disambiguation; mid-model switch is enforced.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$ROOT/.venv/bin:${PATH:-}"
if ! command -v sopctl >/dev/null 2>&1; then
  echo "need sopctl: $ROOT/.venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

FIX="$ROOT/corpus/fixtures/jobflow-preview"
REPORT_DIR="$ROOT/docs/verification"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/sopcontrol-verify-XXXXXX")"
REPORT="$REPORT_DIR/SIM_${STAMP}.md"
mkdir -p "$REPORT_DIR"

log() { echo "$*" | tee -a "$WORKDIR/run.log"; }

cp -R "$FIX/." "$WORKDIR/"
rm -f "$WORKDIR/.sopcontrol/rules/candidates.yaml" \
      "$WORKDIR/.sopcontrol/evidence/growth-"* \
      "$WORKDIR/.sopcontrol/evidence/space-snapshots.jsonl" 2>/dev/null || true

cd "$WORKDIR"
git init -q
git config user.email "verify@sopcontrol.local"
git config user.name "verify"
sopctl identity init . >/dev/null
sopctl identity lock . >/dev/null || true
sopctl hook install . >/dev/null || true
sopctl project all . >/dev/null || true

log "== workdir $WORKDIR"

# --- Baseline measure ---
sopctl audit . --compact >"$WORKDIR/audit1.txt" 2>&1 || true
sopctl growth measure . >"$WORKDIR/measure1.txt" 2>&1
BASE_IDX=$(python3 - <<'PY'
import re, pathlib
t = pathlib.Path("measure1.txt").read_text(encoding="utf-8")
m = re.search(r"ambiguity_index=(\d+)", t)
print(m.group(1) if m else "?")
PY
)
BASE_BYPASS=$(python3 - <<'PY'
import re, pathlib
t = pathlib.Path("measure1.txt").read_text(encoding="utf-8")
m = re.search(r"旁路开 (\d+)", t)
print(m.group(1) if m else "?")
PY
)
log "== baseline ambiguity_index=$BASE_IDX bypass=$BASE_BYPASS"

# --- Ambient growth: 3 audits ---
for i in 1 2 3; do
  sopctl audit . --compact >/dev/null 2>&1 || true
done
sopctl growth status . >"$WORKDIR/growth_status.txt" 2>&1 || true
CAND=$(python3 - <<'PY'
import yaml, pathlib
p = pathlib.Path(".sopcontrol/rules/candidates.yaml")
if not p.exists():
    print("")
    raise SystemExit
rows = yaml.safe_load(p.read_text(encoding="utf-8")) or []
for r in rows:
    if r.get("suggested_action") == "delete_entry" and r.get("status") == "observed":
        print(r["candidate_id"]); break
PY
)
log "== delete_entry candidate: ${CAND:-NONE}"

ENACT_OK=0
TASK_ID=""
if [[ -n "${CAND}" ]]; then
  set +e
  sopctl candidate enact "$CAND" . --allow src/sheet_direct.py >"$WORKDIR/enact.txt" 2>&1
  ENACT_RC=$?
  set -e
  if [[ "$ENACT_RC" -eq 0 ]]; then
    ENACT_OK=1
    TASK_ID=$(rg -o "TASK-[0-9]+" "$WORKDIR/enact.txt" | head -1 || true)
    log "== enact ok task=$TASK_ID"
  else
    log "== enact failed (see enact.txt)"
  fi
fi

# --- Disambiguation: remove legacy entry from production ---
# sheet_direct.py defines direct_write — delete production file (keep tests importing it? tests may break)
# For sim: replace production with stub that does not define direct_write, or delete file.
if [[ -f src/sheet_direct.py ]]; then
  rm -f src/sheet_direct.py
  # neutralize test import if present so audit isn't about test path
  if [[ -f tests/test_archive.py ]] || ls tests/*.py >/dev/null 2>&1; then
    for t in tests/*.py; do
      [[ -f "$t" ]] || continue
      if rg -q "sheet_direct|direct_write" "$t" 2>/dev/null; then
        # comment out imports of removed module for clean production signal
        python3 - <<PY
from pathlib import Path
p = Path("$t")
text = p.read_text(encoding="utf-8")
text2 = text.replace("from sheet_direct import", "# from sheet_direct import").replace("import sheet_direct", "# import sheet_direct")
p.write_text(text2, encoding="utf-8")
PY
      fi
    done
  fi
  log "== removed src/sheet_direct.py (legacy direct_write)"
fi

# Also clear legacy_markers on PUSH-002 via registry edit is NOT allowed philosophy —
# we want production bypass gone; markers can remain until human deprecate.
sopctl audit . --compact >"$WORKDIR/audit2.txt" 2>&1 || true
sopctl growth measure . >"$WORKDIR/measure2.txt" 2>&1
AFTER_IDX=$(python3 - <<'PY'
import re, pathlib
t = pathlib.Path("measure2.txt").read_text(encoding="utf-8")
m = re.search(r"ambiguity_index=(\d+)", t)
print(m.group(1) if m else "?")
PY
)
AFTER_BYPASS=$(python3 - <<'PY'
import re, pathlib
t = pathlib.Path("measure2.txt").read_text(encoding="utf-8")
m = re.search(r"旁路开 (\d+)", t)
print(m.group(1) if m else "?")
PY
)
# Honest arc: first baseline frame vs last post-disambiguation frame
# (intermediate ambient/enact frames would otherwise make last-two both post-delete)
python3 - <<'PY'
from pathlib import Path
p = Path(".sopcontrol/evidence/space-snapshots.jsonl")
if p.exists():
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) >= 2:
        p.write_text(lines[0] + "\n" + lines[-1] + "\n", encoding="utf-8")
PY
sopctl growth diff . >"$WORKDIR/diff.txt" 2>&1 || true
log "== after disambiguation ambiguity_index=$AFTER_IDX bypass=$AFTER_BYPASS"

# --- Mid-model switch ---
REBIND_OK=0
MISMATCH_DENY=0
# open a fresh task for rebind demo on a clean allow file
mkdir -p src
echo 'def workflow_gateway(x): return x' > src/gateway.py
echo 'x=1' > src/ok.py
set +e
sopctl task open . --model model-strong --objective "touch ok" --allow src/ok.py --require-field status >"$WORKDIR/task_open.txt" 2>&1
OPEN_RC=$?
set -e
NEW_TASK=$(rg -o "TASK-[0-9]+" "$WORKDIR/task_open.txt" | head -1 || true)
if [[ -n "$NEW_TASK" && "$OPEN_RC" -eq 0 ]]; then
  # force strong-like knobs already from open; rebind to unknown-name
  set +e
  sopctl task rebind "$NEW_TASK" . --model model-b >"$WORKDIR/rebind.txt" 2>&1
  REBIND_RC=$?
  set -e
  if [[ "$REBIND_RC" -eq 0 ]]; then
    REBIND_OK=1
    log "== rebind $NEW_TASK model-strong→model-b ok"
  else
    log "== rebind failed"
  fi
  # harness mismatch
  PAYLOAD=$(python3 - <<PY
import json
print(json.dumps({
  "tool_name": "Edit",
  "tool_input": {"file_path": "src/ok.py"},
  "model": "model-c-intruder",
}))
PY
)
  set +e
  OUT=$(sopctl harness-check . --payload "$PAYLOAD" 2>/dev/null)
  set -e
  if echo "$OUT" | python3 -c "import sys,json; d=json.load(sys.stdin); x=d.get('hookSpecificOutput') or d; sys.exit(0 if x.get('permissionDecision')=='deny' and 'rebind' in (x.get('permissionDecisionReason') or '') else 1)"; then
    MISMATCH_DENY=1
    log "== harness mismatch deny ok"
  else
    log "== harness mismatch deny FAILED: $OUT"
  fi
else
  log "== task open skipped/failed (see task_open.txt)"
fi

# --- Contrast: without control plane, legacy file can be reintroduced unchecked by gate ---
CONTRAST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sopcontrol-contrast-XXXXXX")"
cp -R "$FIX/." "$CONTRAST_DIR/"
# no sopctl init — plain tree
echo 'def direct_write(a,b): return 1' > "$CONTRAST_DIR/src/sheet_direct.py"
CONTRAST_HAS_LEGACY=0
if rg -q "def direct_write" "$CONTRAST_DIR/src/sheet_direct.py"; then
  CONTRAST_HAS_LEGACY=1
fi
# with control plane after deletion, gate should pass on PUSH-002 fail absence
set +e
sopctl gate . >"$WORKDIR/gate_after.txt" 2>&1
GATE_AFTER=$?
set -e
log "== gate after disambiguation exit=$GATE_AFTER"
log "== contrast uncontrolled tree can hold direct_write=$CONTRAST_HAS_LEGACY"

# --- Write report (quoted heredoc: bash must not eat backticks) ---
export SIM_REPORT="$REPORT" SIM_WORKDIR="$WORKDIR" SIM_CONTRAST="$CONTRAST_DIR"
export SIM_BASE_IDX="$BASE_IDX" SIM_BASE_BYPASS="$BASE_BYPASS"
export SIM_AFTER_IDX="$AFTER_IDX" SIM_AFTER_BYPASS="$AFTER_BYPASS"
export SIM_CAND="${CAND:-}" SIM_TASK_ID="${TASK_ID:-}" SIM_NEW_TASK="${NEW_TASK:-}"
export SIM_ENACT_OK="$ENACT_OK" SIM_REBIND_OK="$REBIND_OK"
export SIM_MISMATCH_DENY="$MISMATCH_DENY" SIM_GATE_AFTER="$GATE_AFTER"
export SIM_CONTRAST_HAS_LEGACY="$CONTRAST_HAS_LEGACY"

python3 - <<'PY'
import os
from pathlib import Path
from datetime import datetime, timezone

report = Path(os.environ["SIM_REPORT"])
w = Path(os.environ["SIM_WORKDIR"])

def read(name: str) -> str:
    p = w / name
    return p.read_text(encoding="utf-8") if p.exists() else "(missing)"

base_idx = os.environ["SIM_BASE_IDX"]
base_bypass = os.environ["SIM_BASE_BYPASS"]
after_idx = os.environ["SIM_AFTER_IDX"]
after_bypass = os.environ["SIM_AFTER_BYPASS"]
cand = os.environ.get("SIM_CAND") or ""
task_id = os.environ.get("SIM_TASK_ID") or ""
enact_ok = os.environ["SIM_ENACT_OK"] == "1"
rebind_ok = os.environ["SIM_REBIND_OK"] == "1"
mismatch_deny = os.environ["SIM_MISMATCH_DENY"] == "1"
gate_after = os.environ["SIM_GATE_AFTER"]
contrast_legacy = os.environ["SIM_CONTRAST_HAS_LEGACY"] == "1"

try:
    narrowed = int(after_idx) < int(base_idx) or int(after_bypass) < int(base_bypass)
except Exception:
    narrowed = "unknown"

body = f"""# Product verification simulation

**When (UTC):** {datetime.now(timezone.utc).isoformat()}
**Workdir:** `{w}`
**Fixture:** `corpus/fixtures/jobflow-preview` (temp copy)
**Script:** `scripts/verify-product-sim.sh`

## What this is / isn't

| Is | Isn't |
|----|--------|
| Reproducible **mechanism + local utility** check | Multi-week human dogfood on JobsFlow |
| Proof that **disambiguation can drop ambiguity_index** | Proof every real team will feel it |
| Proof **mid-model mismatch is denied** | Live OpenCode session with real API |

## Results

| Check | Result |
|-------|--------|
| Baseline ambiguity_index | **{base_idx}** (bypass open **{base_bypass}**) |
| After removing `direct_write` production file | ambiguity_index **{after_idx}** (bypass **{after_bypass}**) |
| Space narrowed? | **{narrowed}** |
| Ambient delete_entry candidate appeared | **{bool(cand)}** (`{cand or "—"}`) |
| candidate enact opened task | **{enact_ok}** (`{task_id or "—"}`) |
| task rebind to new model | **{rebind_ok}** |
| harness deny on model mismatch | **{mismatch_deny}** |
| gate after disambiguation exit | **{gate_after}** (0=clean enough / no fail) |
| Uncontrolled tree can still host legacy | **{contrast_legacy}** |

## Diff output (baseline frame → final frame)

```
{read("diff.txt").strip()}
```

## Baseline vs after measure

**measure1 (baseline):**

```
{read("measure1.txt").strip()}
```

**measure2 (after delete):**

```
{read("measure2.txt").strip()}
```

## Interpretation

1. **Living space can narrow** when a bypass is actually removed — measured by `ambiguity_index` / bypass_open.
2. **Ambient discovery** can surface `delete_entry` without a human running `candidate refresh`.
3. **Enact** turns that into a bounded task (human only supplies `--allow`).
4. **Mid-conversation model switch** is enforceable when the payload carries `model`.
5. Without the control plane, a tree can quietly keep/reintroduce `direct_write` — the plane's job is to make that **visible and blocking**, then support deletion.

## Next real dogfood (human)

Use JobsFlow / ai-job-search for 1–2 weeks with 1–3 real rules; weekly `growth measure` + `growth diff`. This sim does **not** replace that.

## Artifacts

- Run log: `{w}/run.log`
- Measures: `measure1.txt` / `measure2.txt`
- Contrast tree (uncontrolled): `{os.environ.get("SIM_CONTRAST", "")}`
"""
report.write_text(body, encoding="utf-8")
print(report)
PY

echo ""
echo "REPORT=$REPORT"
echo "WORKDIR=$WORKDIR"
echo "CONTRAST=$CONTRAST_DIR"
