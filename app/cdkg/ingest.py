"""Step 1 — pull raw article data from Media Cloud and land it on the Spark.

Two outputs per run:
  data/raw/<YYYY-MM-DD>/run-<id>-<country>.jsonl   untouched API payload (replayable)
  articles table in data/cdkg.db                  normalised rows for the pipeline
"""
import datetime as dt
import hashlib
import json
import logging
import re
from pathlib import Path

from ..config import settings
from ..db import session
from .ontology import EVENT_TYPES
from . import custom_input
from .sample_data import SAMPLE_STORIES

log = logging.getLogger("ingest")

# Media Cloud "<Country> - National" geographic collection ids (tags_id).
# Full list: data/country-collections.json (downloaded by scripts/setup_spark.sh from
# mediacloud/collection-review-tool). These two are the fallback for the demo.
FALLBACK_COLLECTIONS = {"Sudan": [34412379], "Bangladesh": [34412132]}


def country_collections(country: str, include_local: bool = True) -> list[int]:
    path = settings.DATA_DIR / "country-collections.json"
    if path.exists():
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if entry.get("country", {}).get("name", "").lower() == country.lower():
                ids = [entry["country"]["national_tags_id"]]
                if include_local:
                    ids += [c["tags_id"] for c in entry.get("collections", [])
                            if "State & Local" in c.get("label", "") and c["label"].startswith(country)]
                return sorted(set(ids))
    return FALLBACK_COLLECTIONS.get(country, [])


def default_query() -> str:
    """Broad recall-oriented English query built from the ontology keywords."""
    terms = []
    for t in EVENT_TYPES.values():
        terms += [k for k in t["keywords"][:6] if k.isascii()]
    return " OR ".join(f'"{t}"' if " " in t else t for t in dict.fromkeys(terms))


def _text_hash(title: str, text: str) -> str:
    norm = re.sub(r"\W+", " ", f"{title} {text[:600]}".lower()).strip()
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


def _jsonable(story: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v) for k, v in story.items()}


def _store(stories: list[dict], run_id: int, country: str | None) -> int:
    new = 0
    with session() as c:
        for s in stories:
            s = _jsonable(s)
            text = s.get("text") or ""
            cur = c.execute(
                """INSERT OR IGNORE INTO articles
                   (id, title, url, media_name, media_url, language, publish_date, indexed_date,
                    text, text_hash, country_hint, ingest_run_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(s["id"]), s.get("title"), s.get("url"), s.get("media_name"), s.get("media_url"),
                 s.get("language"), (s.get("publish_date") or "")[:10], s.get("indexed_date"),
                 text, _text_hash(s.get("title") or "", text), s.get("country") or country, run_id))
            new += cur.rowcount
    return new


def _start_run(**kw) -> int:
    with session() as c:
        cur = c.execute(
            "INSERT INTO ingest_runs (source, query, collection_ids, start_date, end_date) VALUES (?,?,?,?,?)",
            (kw["source"], kw.get("query"), json.dumps(kw.get("collection_ids", [])),
             kw.get("start_date"), kw.get("end_date")))
        return cur.lastrowid


def _finish_run(run_id: int, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    with session() as c:
        c.execute(f"UPDATE ingest_runs SET {sets}, finished_at=datetime('now') WHERE id=?", (*kw.values(), run_id))


def _raw_file(run_id: int, label: str) -> Path:
    day_dir = settings.RAW_DIR / dt.date.today().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"run-{run_id}-{re.sub(r'[^A-Za-z0-9]+', '_', label)}.jsonl"


def ingest_stories(stories: list[dict], source: str, label: str, country: str | None = None) -> dict:
    """Store already-built story dicts (sample set, your own texts, random generator)."""
    run_id = _start_run(source=source, query=label)
    raw = _raw_file(run_id, source)
    with raw.open("w", encoding="utf-8") as f:
        for s in stories:
            f.write(json.dumps(_jsonable(s), ensure_ascii=False) + "\n")
    new = _store(stories, run_id, country)
    _finish_run(run_id, status="done", fetched=len(stories), new_articles=new, raw_path=str(raw))
    return {"run_id": run_id, "source": source, "fetched": len(stories), "new_articles": new, "raw_path": str(raw)}


def ingest_sample() -> dict:
    return ingest_stories(SAMPLE_STORIES, "sample", "(built-in synthetic demo set)")


def ingest_text(blob: str, filename: str = "", country: str | None = None) -> dict:
    stories = custom_input.parse_blob(blob, filename, country)
    if not stories:
        raise ValueError("No articles found in the text. Separate articles with a line containing only ---.")
    return ingest_stories(stories, "text", f"(your texts{': ' + filename if filename else ''})", country)


def ingest_random(n: int = 60, countries: list[str] | None = None, days: int = 30, seed: int | None = None) -> dict:
    stories = custom_input.generate_random(n, countries, days, seed)
    return ingest_stories(stories, "random", f"(random generator n={n} seed={seed})")


def ingest_mediacloud(country: str, days: int = 7, query: str | None = None,
                      collection_ids: list[int] | None = None, max_stories: int = 500) -> dict:
    """Fetch stories with full text (expanded=True) for one reference country.

    Full text requires a Media Cloud account with text access; without it the
    `text` field is empty and the pipeline falls back to title-only extraction.
    """
    if not settings.MEDIACLOUD_API_KEY:
        raise RuntimeError("MEDIACLOUD_API_KEY is not set (.env). Use the sample ingest for an offline demo.")
    import mediacloud.api  # imported lazily so the demo runs without the package

    query = query or default_query()
    collection_ids = collection_ids or country_collections(country)
    if not collection_ids:
        raise RuntimeError(f"No Media Cloud collection found for {country!r}; pass collection_ids.")
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    run_id = _start_run(source="mediacloud", query=query, collection_ids=collection_ids,
                        start_date=start.isoformat(), end_date=end.isoformat())
    raw = _raw_file(run_id, country)
    api = mediacloud.api.SearchApi(settings.MEDIACLOUD_API_KEY)
    fetched, new, token = 0, 0, None
    try:
        with raw.open("w", encoding="utf-8") as f:
            while fetched < max_stories:
                page, token = api.story_list(query, start, end, collection_ids=collection_ids,
                                             expanded=True, pagination_token=token,
                                             page_size=min(100, max_stories - fetched))
                for s in page:
                    f.write(json.dumps(_jsonable(s), ensure_ascii=False) + "\n")
                new += _store(page, run_id, country)
                fetched += len(page)
                log.info("run %s: %s stories", run_id, fetched)
                if not token or not page:
                    break
        _finish_run(run_id, status="done", fetched=fetched, new_articles=new, raw_path=str(raw))
    except Exception as e:
        _finish_run(run_id, status="error", fetched=fetched, new_articles=new, raw_path=str(raw), error=str(e))
        raise
    return {"run_id": run_id, "country": country, "collection_ids": collection_ids,
            "fetched": fetched, "new_articles": new, "raw_path": str(raw)}
