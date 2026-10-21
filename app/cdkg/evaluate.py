"""Score clustering against the random generator's hidden ground truth.

The generator writes `true_event_id` into the raw JSONL of a run (never into the
articles table). Pairwise metrics over the run's event mentions:

  precision  share of merged mention pairs that really are the same event
  recall     share of same-event mention pairs that were merged

Clusters span the whole database, so a pair counts as merged if both mentions
share a cluster_id, whichever run the other cluster members came from.
"""
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

from ..db import rows, session


def _truth(raw_path: str) -> dict[str, str | None]:
    truth = {}
    with Path(raw_path).open(encoding="utf-8") as f:
        for line in f:
            s = json.loads(line)
            if "true_event_id" not in s:
                raise ValueError(f"{raw_path} has no true_event_id; only random-generator runs can be scored")
            truth[str(s["id"])] = s["true_event_id"]
    return truth


def score(run_id: int | None = None) -> dict:
    with session() as c:
        if run_id is None:
            r = c.execute("SELECT id FROM ingest_runs WHERE source='random' ORDER BY id DESC LIMIT 1").fetchone()
            if not r:
                raise ValueError("no random-generator run to score")
            run_id = r[0]
        run = c.execute("SELECT raw_path FROM ingest_runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            raise ValueError(f"no ingest run {run_id}")
        truth = _truth(run["raw_path"])
        ms = rows(c.execute(f"""SELECT id, article_id, cluster_id, model_version FROM event_mentions
                                WHERE article_id IN ({','.join('?' * len(truth))})""", tuple(truth)))
    real = [m for m in ms if truth[m["article_id"]]]
    tp = fp = fn = 0
    for a, b in combinations(real, 2):
        same_true = truth[a["article_id"]] == truth[b["article_id"]]
        merged = a["cluster_id"] is not None and a["cluster_id"] == b["cluster_id"]
        tp += same_true and merged
        fp += merged and not same_true
        fn += same_true and not merged
    events = {t for t in truth.values() if t}
    per_article = Counter(m["article_id"] for m in real)
    return {
        "run_id": run_id,
        "articles": len(truth), "event_articles": sum(1 for t in truth.values() if t),
        "true_events": len(events),
        "mentions": len(real), "mentions_on_irrelevant_articles": len(ms) - len(real),
        "event_articles_without_mention": sum(1 for a, t in truth.items() if t and a not in per_article),
        "articles_with_gt1_mention": sum(1 for n in per_article.values() if n > 1),
        "clusters": len({m["cluster_id"] for m in real}),
        "pairwise_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "pairwise_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "pairs": {"merged_same_event": tp, "merged_different_events": fp, "split_same_event": fn},
        "model_versions": sorted({m["model_version"] for m in ms}),
    }
