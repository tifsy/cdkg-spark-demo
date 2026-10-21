#!/usr/bin/env bash
# Offline end-to-end check of both tasks (no GPU, no API keys, no internet).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; elif [ -f .venv/Scripts/activate ]; then . .venv/Scripts/activate; fi   # Linux / Windows venv
export DATA_DIR=$(mktemp -d) LLM_PROVIDER=mock CRT_MODE=mock INSPECTOR_MODE=fixture
summary="import json,sys; d=json.load(sys.stdin); i=d['ingest']; print('  %-7s fetched=%-4s filter=%s clusters=%s' % (i['source'], i['fetched'], d['filter'], d['cluster']['clusters']))"
echo "Task 1"
python -m app.cli generate --n 100 --seed 1 | python -c "$summary"
for f in examples/my_texts.txt examples/my_texts.csv examples/my_texts.jsonl; do
  python -m app.cli ingest-file "$f" | python -c "$summary"
done
python -m app.cli query flash_triage --country Sudan | python -c "import json,sys; d=json.load(sys.stdin); assert d, 'no rows'; print('  flash_triage rows:', len(d))"
echo "Task 2"
python -m app.cli review --queue demo-queue-sudan-national | python -c "import json,sys; d=json.load(sys.stdin); print('  AI proposals:', d['metrics']['total'])"
echo "OK (temporary data in $DATA_DIR)"
