#!/usr/bin/env bash
# One-time setup on the DGX Spark (Ubuntu / DGX OS, ARM64).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Python venv"
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

echo "==> .env"
[ -f .env ] || cp .env.example .env

echo "==> Media Cloud country collection list (for country -> collection id lookup)"
mkdir -p data
curl -fsSL -o data/country-collections.json \
  https://raw.githubusercontent.com/mediacloud/collection-review-tool/main/backend/data/country-collections.json \
  || echo "   (download failed; built-in Sudan/Bangladesh ids will be used)"

echo "==> Local LLM"
if command -v ollama >/dev/null 2>&1; then
  MODEL=$(grep -E '^LLM_MODEL=' .env | cut -d= -f2 | cut -d' ' -f1)
  ollama pull "${MODEL:-qwen2.5:14b}"
else
  echo "   Ollama not found. Install:  curl -fsSL https://ollama.com/install.sh | sh"
  echo "   or point LLM_BASE_URL at a vLLM / NIM server, or set LLM_PROVIDER=mock."
fi

echo "Done. Next: edit .env, then ./scripts/run.sh"
