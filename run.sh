#!/usr/bin/env bash
# One command: install deps, run the citation-validator negative test, then a
# full offline demo (scripted model + stub corpus) through the human gate.
#
# Real open-weights run (after ./scripts/setup_ollama.sh):
#   MODEL=ollama/qwen3:1.7b ./run.sh -- --task price_reasonableness --approve "Your Name"
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null 2>&1 || {
  echo "uv is required: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
}

uv sync --quiet

echo "== citation validator negative test (must reject uncited + hallucinated findings) =="
uv run lens-demo --validator-test

echo
echo "== full offline demo: plan → retrieve → analyze → synthesize → self-check → gate → approve → finalize =="
uv run lens-demo --approve "${APPROVER:-Demo Reviewer}" "$@"

echo
echo "Done. Artifacts: output/brief-*.md + output/flags.jsonl · Audit trail: logs/audit.jsonl"
