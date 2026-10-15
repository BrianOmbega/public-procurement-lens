#!/usr/bin/env bash
# Regenerate evidence/offline-run/ — the audit trail, the artifacts it produced,
# and the verifier's verdict over both, committed so a judge can inspect a real
# gated run without executing anything.
#
# Deterministic on purpose: the demo runs the ScriptedModel, so the pack is
# byte-reproducible apart from timestamps and the artifact filename. It proves
# the MACHINERY (planned checks, retrieval, citation validation, the human
# gate, audit completeness), not model quality — see EVALS.md for the
# open-weights run.
#
# Exits non-zero if the run does not verify, so a broken pack can never be
# committed by accident.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=evidence/offline-run
APPROVER="${1:-Njoki Mwangi}"

rm -rf "$OUT"
mkdir -p "$OUT"

echo "==> running the gated offline demo (approver: $APPROVER)"
LENS_AUDIT="$OUT/audit.jsonl" LENS_OUTPUT="$OUT" \
  uv run lens-demo --approve "$APPROVER" >"$OUT/demo.log" 2>&1

echo "==> verifying the trail it produced"
{
  uv run lens-audit verify  --audit "$OUT/audit.jsonl"
  echo
  uv run lens-audit summary --audit "$OUT/audit.jsonl"
} > "$OUT/verify.txt" 2>&1   # non-zero here aborts under set -e: no broken pack

cat "$OUT/verify.txt" | tail -n +1 | grep -E '^(  \[|VERIFY|events)' || true

echo
echo "==> pack contents"
ls -1 "$OUT"
echo
echo "Regenerated. Commit with: git add evidence && git commit"
