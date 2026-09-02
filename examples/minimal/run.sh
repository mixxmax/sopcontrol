#!/usr/bin/env bash
# Minimal throwaway demo: fixture copy → init → audit → growth → gate
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if ! command -v sopctl >/dev/null 2>&1; then
  if [[ -x "$ROOT/.venv/bin/sopctl" ]]; then
    export PATH="$ROOT/.venv/bin:$PATH"
  else
    echo "sopctl not on PATH. From repo root: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
  fi
fi

FIX="$ROOT/corpus/fixtures/jobflow-preview"
if [[ ! -d "$FIX" ]]; then
  echo "missing fixture: $FIX" >&2
  exit 1
fi

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/sopcontrol-minimal-XXXXXX")"
echo "==> workdir: $WORKDIR"
cp -R "$FIX/." "$WORKDIR/"
# ignore local growth residue if any
rm -f "$WORKDIR/.sopcontrol/rules/candidates.yaml"
rm -f "$WORKDIR/.sopcontrol/evidence/growth-observations.jsonl"
rm -f "$WORKDIR/.sopcontrol/evidence/growth-state.yaml"
rm -f "$WORKDIR/.sopcontrol/evidence/space-snapshots.jsonl"

cd "$WORKDIR"
echo "==> git init (for hook) + identity + projection"
git init -q
git config user.email "demo@sopcontrol.local"
git config user.name "sopcontrol-demo"
sopctl identity init . >/dev/null || true
sopctl identity lock . >/dev/null || true
sopctl hook install . >/dev/null || true
sopctl project all . >/dev/null || true

echo "==> audit (observe; ambient growth on persist)"
sopctl audit . --compact || true

echo "==> growth status / measure"
sopctl growth status . || true
sopctl growth measure . || true

echo "==> gate (non-zero exit is expected if fixture has fail rules)"
set +e
sopctl gate .
gate_code=$?
set -e
echo "gate exit code: $gate_code"

echo ""
echo "Demo done. Inspect: $WORKDIR"
echo "Remove when finished: rm -rf '$WORKDIR'"
