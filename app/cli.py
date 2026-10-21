"""Command line entry points (cron-friendly).

  python -m app.cli sample                         # built-in synthetic set + pipeline
  python -m app.cli generate --n 200 --days 30     # random fake articles + pipeline
  python -m app.cli ingest-file my_texts.txt --country Sudan   # your own texts + pipeline
  python -m app.cli ingest --country Sudan --days 1
  python -m app.cli pipeline
  python -m app.cli query flash_triage --country Sudan
  python -m app.cli score [--run 3]                # clustering vs the generator's ground truth
  python -m app.cli review --queue <queue_guid>    # AI pre-review only; humans confirm in the UI
"""
import argparse
import json

from .cdkg import evaluate, ingest, pipeline, queries
from .db import init_db
from .review import agent


def main():
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    g = sub.add_parser("generate")
    g.add_argument("--n", type=int, default=60)
    g.add_argument("--countries", help="comma-separated, default: all in the gazetteer")
    g.add_argument("--days", type=int, default=30)
    g.add_argument("--seed", type=int)
    f = sub.add_parser("ingest-file")
    f.add_argument("path")
    f.add_argument("--country")
    i = sub.add_parser("ingest")
    i.add_argument("--country", required=True)
    i.add_argument("--days", type=int, default=1)
    i.add_argument("--query")
    i.add_argument("--collections", help="comma-separated Media Cloud collection ids")
    i.add_argument("--max", type=int, default=500)
    i.add_argument("--no-pipeline", action="store_true")
    sub.add_parser("pipeline")
    q = sub.add_parser("query")
    q.add_argument("name", choices=list(queries.CANONICAL))
    q.add_argument("--country", required=True)
    s = sub.add_parser("score")
    s.add_argument("--run", type=int, help="ingest run id, default: latest random-generator run")
    r = sub.add_parser("review")
    r.add_argument("--queue", required=True)
    r.add_argument("--limit", type=int, default=200)
    r.add_argument("--redo", action="store_true")
    a = p.parse_args()

    init_db()
    if a.cmd == "sample":
        out = {"ingest": ingest.ingest_sample(), **pipeline.run_all()}
    elif a.cmd == "generate":
        countries = a.countries.split(",") if a.countries else None
        out = {"ingest": ingest.ingest_random(a.n, countries, a.days, a.seed), **pipeline.run_all()}
    elif a.cmd == "ingest-file":
        from pathlib import Path
        p = Path(a.path)
        out = {"ingest": ingest.ingest_text(p.read_text(encoding="utf-8"), p.name, a.country), **pipeline.run_all()}
    elif a.cmd == "ingest":
        cols = [int(x) for x in a.collections.split(",")] if a.collections else None
        out = {"ingest": ingest.ingest_mediacloud(a.country, a.days, a.query, cols, a.max)}
        if not a.no_pipeline:
            out.update(pipeline.run_all())
    elif a.cmd == "pipeline":
        out = pipeline.run_all()
    elif a.cmd == "query":
        out = queries.CANONICAL[a.name][1](a.country)
    elif a.cmd == "score":
        out = evaluate.score(a.run)
    else:
        agent.run_queue(a.queue, a.limit, a.redo)
        out = {"job": agent.JOB, "metrics": agent.metrics(a.queue)}
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
