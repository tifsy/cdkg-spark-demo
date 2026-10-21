# CLAUDE.md — project context for Claude Code

This repo was started in a claude.ai chat; this file carries that context over.
Read README.md for setup and usage. Keep everything (code, UI, docs) in **English**.

## What this is
A demo for the **Crisis–Development Knowledge Graph (CDKG)** project (ETH Zurich PI, OCHA,
UNDP, Media Cloud; IGAIP 2026 proposal dated 30 April 2026). It runs on an **NVIDIA DGX Spark**
(ARM64, Grace Blackwell) and is accessed over **Tailscale**. Two tasks:

1. **CDKG pipeline** — get articles → structure them on the Spark → query the event record.
   Follows the proposal's event schema (§3.7), event clusters (§3.8), canonical queries (§6.5),
   two-stage filter/extract architecture (Annex A).
2. **Collection review automation** for https://github.com/mediacloud/collection-review-tool —
   an AI crawls each *source* (news outlet) in a reviewer queue and proposes keep/remove/skip;
   **a human must confirm** before anything is written back via the tool's API.

## Current constraints (important)
- **No Media Cloud full-text access yet.** The user demos with random/own texts. Default ingest
  source is the random generator; "My own texts" accepts paste/upload (.txt with `---`
  separators, .csv/.json/.jsonl with a `text` field). Media Cloud ingest exists
  (`SearchApi.story_list(expanded=True)`) but is untested against the live API.
- LLM via any OpenAI-compatible endpoint: local Ollama/vLLM on the Spark (default `qwen2.5:14b`), or,
  for the user's laptop demo with made-up texts, the hosted OpenAI API (`gpt-5.4-mini`, user's credits).
  Never send real Media Cloud text to a hosted API (§3.5). `LLM_PROVIDER=mock` = labelled heuristics.
  `LLM_FALLBACK=false` by default: LLM errors surface in the UI; extraction/review stop after 3
  consecutive failures. Temperature is dropped automatically if a model rejects it.
- The original "jev / nimble / kev" request was ambiguous; it was interpreted as an open-source
  web crawling/browsing agent. Implemented with requests+BeautifulSoup, optional Crawl4AI
  (`INSPECTOR_BACKEND=crawl4ai`). Confirm with the user if they meant a specific framework.

## Design decisions to preserve
- Article full text never leaves the Spark through the API (`HIDE_FULLTEXT`, proposal §3.5).
- No individual names extracted; actors are "as reported"; protection events are flagged
  `sensitive` and their location text/actors are withheld in the API (§5.10).
- Conflicting figures are kept as ranges, never averaged (§3.8). QA flags: single_source,
  contradiction_*, temporal_span_gt_7d, uncertain_coreference.
- LLM mentions are labelled `<provider>:<model>+<PROMPT_VERSION>`; bump `PROMPT_VERSION` in
  pipeline.py when the prompt changes. Older rows without the suffix stay valid.
- Raw input of every run is kept untouched in `data/raw/<date>/*.jsonl` for replay.
- Task 2: the AI never calls `decide`. Suggestions are stored with status `pending`; only
  `agent.confirm()` (human) pushes. Confidence < `REVIEW_MIN_CONFIDENCE` (0.70) → proposed skip.
  The tool requires `removal_reason` for remove. An audit tag
  `[AI remove 0.82, human agreed: <reviewer>]` is appended to removal_reason / skip_note.
  Reviewer identity comes from `Tailscale-User-Login` when served via `tailscale serve`.
- UI: dashed amber = AI proposal (not yet written), solid = human-confirmed decision.

## Layout
```
app/main.py           FastAPI (API + static UI), app/cli.py (cron/CLI)
app/config.py, db.py  settings from .env; single SQLite file data/cdkg.db
app/llm.py            OpenAI-compatible client, JSON mode, strips <think> and code fences
app/cdkg/             ontology.py (MVO v1 + demo gazetteer Sudan/Bangladesh), ingest.py,
                      custom_input.py (text parser + random generator), pipeline.py
                      (filter → extract → cluster), queries.py (canonical queries, graph export)
app/review/           crt_client.py (Live + Mock), inspector.py (site signals),
                      agent.py (AI proposal, human confirm, metrics), fixtures.py (8 fake sites)
app/static/           index.html, app.js, style.css (vanilla JS, no build step)
examples/             sample input files; scripts/ setup, run, tailscale_serve, cron, smoke_test
```

## How to verify changes
```bash
./scripts/smoke_test.sh                      # offline end-to-end, both tasks (uses temp DATA_DIR)
LLM_PROVIDER=mock python -m uvicorn app.main:app --port 8080   # then open the UI
```
Verified so far: smoke test from a fresh unzip; browser click-through with no JS errors;
Task 2 end-to-end against a **real local collection-review-tool backend** (seeded queue,
decisions + removal_reason/skip_note written); LLM path against a stub OpenAI-compatible server.
**Not yet verified:** a real LLM on the Spark, the live Media Cloud API, live crawling of real sites.

## Known limitations / possible next steps
- Keyword stage-1 filter (proposal expects a small fine-tuned classifier inside Media Cloud).
- Tiny gazetteer; real pipeline needs GADM / HDX COD-AB. Unknown places get no location.
- SQLite store; graph DB chosen later (`/api/cdkg/graph` exports nodes/edges).
- No gold-set evaluation or confidence calibration (ECE); sequential extraction (no batching).
- Ideas: run with the real LLM on the Spark and compare against heuristics; add an evaluation
  page (hand-label ~50 events, precision/recall); concurrent LLM requests; Neo4j export;
  wire Media Cloud once access arrives.
