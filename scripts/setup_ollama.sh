#!/usr/bin/env bash
# Open-weights setup (challenge requirement #2): install Ollama (user-level,
# no sudo) and pull the local model for the full-task run. Idempotent.
#
# Usage:   ./scripts/setup_ollama.sh [model]        # default: qwen3:1.7b
# Verify:  MODEL=ollama/qwen3:1.7b uv run lens-demo --task price_reasonableness --approve "<Full Name>"
#
# Machine note (learned the hard way on an 8 GB Intel i7 / Monterey):
#   - qwen3:1.7b (~1.9 GB runtime) fits even under background memory pressure.
#   - qwen3:4b (~3 GB runtime) needs the browsers/IDE closed, or it swap-thrashes.
#   - Homebrew on Intel/Monterey has NO ollama bottle: `brew install ollama`
#     source-builds LLVM + Rust + Go (hours). Default here is the prebuilt
#     universal zip. Opt into brew only with OLLAMA_VIA_BREW=1.
set -euo pipefail
MODEL="${1:-qwen3:1.7b}"
cd "$(dirname "$0")/.."          # run from repo root
mkdir -p logs

have() { command -v "$1" >/dev/null 2>&1; }

if ! have ollama && [ ! -x "$HOME/.local/bin/ollama" ]; then
  if [ "${OLLAMA_VIA_BREW:-0}" = "1" ] && have brew; then
    echo "→ installing ollama via Homebrew (OLLAMA_VIA_BREW=1; expect a source build on old Intel macOS)…"
    brew install ollama
  else
    echo "→ installing Ollama.app into ~/Applications (prebuilt zip, no sudo)…"
    mkdir -p ~/Applications ~/.local/bin
    TMP_ZIP="$(mktemp -t ollama-dl).zip"
    curl -fL --progress-bar -o "$TMP_ZIP" https://ollama.com/download/Ollama-darwin.zip
    ditto -x -k "$TMP_ZIP" ~/Applications/
    rm -f "$TMP_ZIP"
    ln -sf ~/Applications/Ollama.app/Contents/Resources/ollama ~/.local/bin/ollama
    echo "  note: add ~/.local/bin to PATH permanently if it isn't already"
  fi
fi
export PATH="$HOME/.local/bin:$PATH"

# ensure the daemon is up (headless; no GUI needed)
if ! curl -sf --max-time 2 http://127.0.0.1:11434/api/version >/dev/null; then
  echo "→ starting 'ollama serve' in background (log: logs/ollama-serve.log)…"
  nohup ollama serve >logs/ollama-serve.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf --max-time 1 http://127.0.0.1:11434/api/version >/dev/null && break
    sleep 0.5
  done
fi
echo -n "→ ollama version: "; curl -sf http://127.0.0.1:11434/api/version; echo

echo "→ pulling $MODEL (one-time download)…"
ollama pull "$MODEL"

echo "→ smoke test (models visible on the OpenAI-compat endpoint):"
curl -s http://127.0.0.1:11434/v1/models | head -c 300; echo

echo "✓ ready. Open-weights full-task run:"
echo "    MODEL=ollama/$MODEL uv run lens-demo --task price_reasonableness --approve \"<Full Name>\""
