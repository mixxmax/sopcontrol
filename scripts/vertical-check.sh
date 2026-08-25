#!/usr/bin/env bash
# 垂直骨干役用检查：武装身份/投影/钩子，跑 doctor/audit/gate/self-test/pytest
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SOPCTL="${ROOT}/.venv/bin/sopctl"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$SOPCTL" ]]; then
  echo "缺少 .venv/bin/sopctl；先: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 2
fi

echo "== identity =="
"$SOPCTL" identity init .
echo "== project projection =="
"$SOPCTL" project all .
echo "== pre-push hook =="
"$SOPCTL" hook install .
echo "== capability profile (offline fixture) =="
"$SOPCTL" capability-eval --model vertical-backbone --fixture strong . || true
echo "== doctor =="
"$SOPCTL" doctor .
echo "== audit =="
"$SOPCTL" audit .
echo "== gate =="
"$SOPCTL" gate .
echo "== self-test =="
"$SOPCTL" self-test
echo "== pytest =="
"$PY" -m pytest -q
echo
echo "vertical-check.sh: 全部通过（含 pytest；比 sopctl vertical-check 更严）。日用见 PLAYBOOK.md"
