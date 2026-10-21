# CDKG + Collection Review demo (DGX Spark / Tailscale)

One small web app that demonstrates the two project tasks:

| Task | What it does | Based on |
|---|---|---|
| **1. CDKG** | Take news articles → structure them on the Spark (filter, LLM extraction, event clustering) → query the event record | CDKG proposal §3.7, §3.8, §6.5, Annex A |
| **2. Collection review automation** | AI visits each source's website in a collection-review-tool queue and proposes keep / remove / skip → **a person must confirm** before anything is written back | [mediacloud/collection-review-tool](https://github.com/mediacloud/collection-review-tool) |

Everything runs on the DGX Spark. The LLM is a local server on the Spark (Ollama or vLLM). Article text never leaves the machine through the API (proposal §3.5).

---

## 1. Quick start on the Spark

```bash
# Copy the code to the Spark (using its Tailscale name)
scp cdkg-spark-demo.zip <user>@<spark-hostname>:~
ssh <user>@<spark-hostname>
unzip cdkg-spark-demo.zip && cd cdkg-spark-demo

./scripts/setup_spark.sh     # venv, packages, .env, pulls the Ollama model
./scripts/smoke_test.sh      # checks both tasks offline (no GPU, keys or internet needed)
./scripts/run.sh             # serves on http://0.0.0.0:8080
```

To look at the screens before the LLM is ready, set `LLM_PROVIDER=mock` in `.env`. Results are then made by simple heuristics and labelled `model_version=heuristic`, so they are never mistaken for LLM output.

### Set up the LLM (pick one)

```bash
# A) Ollama: simplest, supports the DGX Spark (ARM64)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:14b          # default: good multilingual extraction at reasonable speed
# Larger options: gpt-oss:20b or qwen2.5:32b, then change LLM_MODEL in .env

# B) An existing vLLM or NVIDIA NIM server
LLM_BASE_URL=http://localhost:8000/v1
LLM_MODEL=<model name served there>

# C) A hosted OpenAI-compatible API, e.g. OpenAI (uses your API credits)
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-5.4-mini           # any chat model your key can use
```

When the `LLM:` indicator at the top right of the page is green, the model is connected. If it says *model not available for this key*, hover over it or open `/api/health`: the `available` list shows the model names your key can use.

**About option C.** Article text is sent to OpenAI, which is fine for generated or made-up demo texts but conflicts with the project's rule that Media Cloud text stays on the Spark (proposal §3.5), so use A or B for real Media Cloud data. Each article and each reviewed source is one API call; with a small model such as `gpt-5.4-mini`, the 60 generated demo articles plus the 8 demo sources cost well under a dollar. Some newer models only accept their default temperature; the app notices this and retries without it.

**No silent fallback.** If the LLM fails (wrong key, no credits, server down), the failure is shown in the UI and extraction stops after 3 consecutive errors. You never get heuristic results while thinking they came from the LLM. Set `LLM_FALLBACK=true` only if you prefer the old behaviour; those results are labelled `heuristic-fallback`.

---

## 2. Demo input: your own texts or generated articles

Full Media Cloud text access is not needed for the demo. Step 1 of the **Event record** tab offers four sources:

| Source | Use it for |
|---|---|
| **Random generated articles** (default) | Quick, realistic-looking volume. Fake events in Sudan and Bangladesh, each "reported" by 1–3 fake outlets with slightly different numbers, plus ~20% irrelevant stories. Set a **seed** to get the same articles again. |
| **My own texts** | Paste text or upload a file. Any text works, including random sentences. Text with no crisis content is simply dropped by the filter, and the filter log shows why. |
| **Built-in example set** | 13 hand-written example articles, including an Arabic one. |
| **Media Cloud API** | Real data, once you have access (section 5). |

### Formats for your own texts

**Plain text** (paste or `.txt`). Separate articles with a line containing only `---`. If an article's first line is short, it becomes the title.
```
Floods in Sunamganj
Heavy rain flooded Sunamganj district in Sylhet. About 20,000 people moved to shelters.
---
Clashes near El Fasher
At least 12 people were killed in fighting near El Fasher, North Darfur.
```

**CSV.** A `text` column is required. Optional columns: `title`, `outlet`, `date` (YYYY-MM-DD), `country`, `language`, `url`.

**JSONL / JSON.** One object per line (or a list) with the same field names.

Ready-made examples are in `examples/`. Missing fields get defaults: outlet "Demo input", today's date, and the language guessed from the script. Leave the country on **Any / detect** to let the place names decide.

> **Tips for meaningful demo texts.** Place names are only recognised if they are in the demo gazetteer (`app/cdkg/ontology.py`, `GAZETTEER`): Sudan states and towns such as El Fasher, Nyala, Kosti and Kadugli, and Bangladesh divisions and districts such as Sylhet, Sunamganj, Cox's Bazar and Ukhia. Add your own places there. To show clustering, write the same event two or three times with different outlets, dates within two days of each other, and slightly different numbers.

### From the command line

```bash
python -m app.cli generate --n 200 --days 30 --seed 42             # random articles + pipeline
python -m app.cli generate --n 100 --countries Sudan
python -m app.cli ingest-file examples/my_texts.txt                # your texts + pipeline
python -m app.cli ingest-file my_data.csv --country Bangladesh     # country used when the file has none
python -m app.cli sample                                           # built-in example set
```

---

## 3. Configuration (`.env`)

| Variable | Meaning |
|---|---|
| `MEDIACLOUD_API_KEY` | Optional for the demo. Needed only for the Media Cloud source. |
| `LLM_PROVIDER` | `openai` (any OpenAI-compatible local server) or `mock` (heuristics) |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | LLM server address, model name and key (any value for Ollama; your `sk-...` key for OpenAI) |
| `LLM_TEMPERATURE` | `0` by default for repeatable extraction; dropped automatically if the model rejects it |
| `LLM_FALLBACK` | `false` (default): LLM errors are reported. `true`: fall back to labelled heuristics |
| `CRT_MODE` | `mock` (built-in demo queue) or `live` (a running collection-review-tool) |
| `CRT_BASE_URL` | The review tool's address in live mode. Use its Tailscale name if it runs elsewhere, e.g. `http://crt-server:5000` |
| `INSPECTOR_MODE` | `fixture` (offline snapshots of fake sites) or `live` (visit real websites) |
| `INSPECTOR_BACKEND` | `requests` (default) or `crawl4ai` for JavaScript-heavy sites (`pip install crawl4ai && crawl4ai-setup`) |
| `REVIEW_MIN_CONFIDENCE` | Below this, the AI proposes skip instead of keep/remove (default 0.70) |
| `APP_TOKEN` | If set, write actions require this token: an extra layer on top of Tailscale |

---

## 4. Access over Tailscale

This assumes the Spark is already on your tailnet (check with `tailscale status`).

**Option 1: plain port.** Run `./scripts/run.sh`, then open `http://<spark-hostname>:8080` from any device on the tailnet.

**Option 2: HTTPS inside the tailnet (recommended).**
```bash
./scripts/tailscale_serve.sh 8080
# -> https://<spark-hostname>.<tailnet>.ts.net
```
With `tailscale serve`, Tailscale passes the visitor's identity (`Tailscale-User-Login`) to the app. **Task 2 then records who confirmed each decision automatically**, so nobody has to type a name.

> Do not use `tailscale funnel` (public internet). This demo is meant for use inside the tailnet only.

---

## 5. Task 1: CDKG

**In the browser:** open the **Event record** tab.

1. **Get articles.** Choose a source (section 2) and run it.
2. **Structure on the Spark.** This runs automatically after step 1: filter, then LLM extraction, then clustering.
3. **Query the record.** Choose a canonical query and a country. Click a row to see its provenance.

**Where the data lives on the Spark**
```
data/
├─ raw/2026-10-12/run-3-random.jsonl   untouched input of every run (replayable)
├─ cdkg.db                             SQLite, tables below
└─ country-collections.json            country -> Media Cloud collection id
```

| Table | Contents |
|---|---|
| `ingest_runs` | Every ingest: source, query, period, counts, errors |
| `articles` | Articles plus the filter score and reason (auditable) |
| `event_mentions` | Events extracted from one article (§3.7 schema, with model version) |
| `event_clusters` | Mentions linked as the same real-world event. Numbers are kept as ranges, never averaged, and QA flags are attached |

**API** (interactive docs at `/docs`):
- `GET /api/cdkg/events?country=Sudan&event_type=displacement&since_days=30&min_sources=2`
- `GET /api/cdkg/events/{id}`: one cluster with its provenance list
- `GET /api/cdkg/queries/{flash_triage|monthly_trend|early_warning|source_gap|wash_30d|displacement_90d}?country=Sudan`
- `GET /api/cdkg/graph`: nodes and edges, for moving to Neo4j or similar later
- `POST /api/cdkg/ingest` with `{"source": "random", "n": 100, "seed": 1}` or `{"source": "text", "text": "...", "filename": "x.csv"}`

**Switching to Media Cloud later.** Add `MEDIACLOUD_API_KEY` to `.env`, then choose **Media Cloud API** in step 1, or run:
```bash
python -m app.cli ingest --country Sudan --days 1
python -m app.cli ingest --country Bangladesh --days 3 --query 'flood OR cyclone OR displaced'
```
Without full-text access, Media Cloud still returns titles and metadata, so the pipeline runs on titles only. `scripts/daily.cron` shows a daily schedule. Nothing else in the pipeline changes, because every source produces the same article shape.

---

## 6. Task 2: Collection review automation

**Try it offline:** open the **Source review** tab. The demo queue of eight fake sites is preloaded. Click **Run AI pre-review**.

### Connect to the real review tool

1. Run collection-review-tool, on the same Spark or another machine:
   ```bash
   git clone https://github.com/mediacloud/collection-review-tool && cd collection-review-tool/backend
   pip install -r requirements.txt && echo "MEDIACLOUD_API_KEY=..." > ../.env
   python app.py        # :5000
   ```
2. Create a project and its queues in the review tool. Copy the **queue GUID** from the end of a reviewer URL.
3. In this demo's `.env`, set `CRT_MODE=live`, `CRT_BASE_URL=http://<host>:5000` and `INSPECTOR_MODE=live`, then restart.
4. Paste the GUID into the **Source review** tab and click **Run AI pre-review**.

### How it works

```
Review tool queue (undecided items)
   |  GET /api/review-queues/<guid>/items
   v
Crawler visits the homepage and About page and collects evidence ("signals"):
   bylines, most recent date, share of links to other sites,
   PR or satire wording, whether the site loads at all
   v
Local LLM applies the queue's own guidelines
   -> keep / remove / skip, with a confidence score and reasons
   (confidence below 0.70 -> proposed as skip)
   v
Stored as a proposal only; nothing is written to the review tool yet   (dashed in the UI)
   |
   v  A person accepts or changes it
      (Enter = accept AI, 1 / 2 / 3 = keep / remove / skip)
POST /api/review-queues/<guid>/items/<id>/decide                        (solid in the UI)
   An audit tag is appended to removal_reason / skip_note:
   "[AI remove 0.82, human agreed: kim@org]"
```

The **people agreed with AI** figure at the top shows how often reviewers accepted the AI's proposal. Use it to decide which kinds of proposal can be trusted more.

---

## 7. Project layout

```
app/
├─ main.py              FastAPI: API and web page
├─ cli.py               commands for the shell and cron
├─ config.py, db.py     settings, SQLite schema
├─ llm.py               client for a local OpenAI-compatible LLM; falls back to heuristics, labelled as such
├─ cdkg/
│  ├─ ontology.py       MVO v1: 6 event types, 6 sectors, demo gazetteer (Sudan, Bangladesh)
│  ├─ ingest.py         every input source -> raw JSONL + articles table
│  ├─ custom_input.py   parser for your texts (txt/csv/json/jsonl) and the random article generator
│  ├─ pipeline.py       filter -> extraction -> clustering
│  ├─ queries.py        canonical queries, graph export
│  └─ sample_data.py    built-in example articles (not real news)
├─ review/
│  ├─ crt_client.py     collection-review-tool API client (plus mock)
│  ├─ inspector.py      site visits and evidence (requests or Crawl4AI)
│  ├─ agent.py          AI proposal, human confirmation, write-back, agreement rate
│  └─ fixtures.py       eight fake sites for the offline demo
└─ static/              web page (HTML/CSS/JS)
examples/               sample input files for "My own texts"
scripts/                setup, run, Tailscale, cron, smoke test
```

---

## 8. Demo limitations (what changes in the real project)

- **Filter:** keyword-based. The proposal assumes a small fine-tuned classifier running inside Media Cloud (§A.3).
- **Places:** a small demo gazetteer for Sudan and Bangladesh only. The real pipeline needs GADM / HDX COD-AB boundaries.
- **Storage:** SQLite. The graph database is chosen in inception; `/api/cdkg/graph` makes migration straightforward.
- **Evaluation:** no gold-set evaluation or calibration (ECE) yet. Confidence scores are uncalibrated.
- **Demo data:** generated and example articles, and the review-demo sites, are all fictional (`.example` domains). Do not present results from them as findings.
- **Crawling:** when visiting real sites, respect robots.txt and request limits. The default is two requests per site (homepage and About page).
- **Throughput:** articles are processed one at a time. Beyond about 2,000 per day, use vLLM batching or concurrent requests.

**Suggested next steps:** run one day of real Media Cloud data once access arrives; hand-check about 50 extracted events for quality; measure the AI–human agreement rate on one real review queue.
