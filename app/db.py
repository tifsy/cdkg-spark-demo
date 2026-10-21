"""SQLite store on the DGX Spark.

One file (data/cdkg.db) holds both tasks. SQLite in WAL mode is plenty for a
single-box demo; the schema is graph-shaped (articles -> mentions -> clusters ->
places/sectors) so it can be exported to Neo4j/GraphML later.
"""
import json
import sqlite3
from contextlib import contextmanager

from .config import settings

SCHEMA = """
PRAGMA journal_mode=WAL;

-- ===================== Task 1: CDKG =====================
CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    source TEXT,              -- 'mediacloud' | 'sample'
    query TEXT,
    collection_ids TEXT,
    start_date TEXT,
    end_date TEXT,
    raw_path TEXT,            -- JSONL file with the untouched API payload
    fetched INTEGER DEFAULT 0,
    new_articles INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',
    error TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,      -- Media Cloud story id
    title TEXT,
    url TEXT,
    media_name TEXT,
    media_url TEXT,
    language TEXT,
    publish_date TEXT,
    indexed_date TEXT,
    text TEXT,                -- full text, stays on the Spark
    text_hash TEXT,           -- near-duplicate detection
    country_hint TEXT,        -- reference country this article was pulled for
    ingest_run_id INTEGER,
    filter_score REAL,        -- stage-1 filter (proposal §A.3)
    filter_passed INTEGER,
    filter_reason TEXT,
    extracted_at TEXT,
    extraction_error TEXT
);
CREATE INDEX IF NOT EXISTS ix_articles_country ON articles(country_hint);
CREATE INDEX IF NOT EXISTS ix_articles_hash ON articles(text_hash);

-- one row per event mention extracted from one article (proposal §3.7)
CREATE TABLE IF NOT EXISTS event_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT REFERENCES articles(id),
    event_type TEXT NOT NULL,
    sector TEXT,
    report_date TEXT,
    event_start TEXT,
    event_end TEXT,
    country TEXT,
    admin1 TEXT,
    admin2 TEXT,
    location_text TEXT,
    admin_level INTEGER,
    geo_confidence REAL,
    population_group TEXT,
    population_not_reported INTEGER DEFAULT 0,
    killed INTEGER, injured INTEGER, displaced INTEGER, affected INTEGER,
    actors TEXT,              -- JSON list, "as reported in source"
    summary TEXT,             -- model-written paraphrase, never source text
    confidence REAL,
    sensitive INTEGER DEFAULT 0,
    model_version TEXT,
    extracted_at TEXT DEFAULT (datetime('now')),
    cluster_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_mentions_type ON event_mentions(event_type, country);

-- probabilistic event clusters (proposal §3.8)
CREATE TABLE IF NOT EXISTS event_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT,
    sector TEXT,
    country TEXT,
    admin1 TEXT,
    admin2 TEXT,
    first_date TEXT,
    last_date TEXT,
    source_count INTEGER,     -- independent outlets
    mention_count INTEGER,
    killed_range TEXT, injured_range TEXT, displaced_range TEXT, affected_range TEXT,
    linkage_score REAL,
    confidence REAL,
    qa_flags TEXT,            -- JSON list
    summary TEXT,
    sensitive INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ===================== Task 2: collection review =====================
CREATE TABLE IF NOT EXISTS review_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_guid TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    source_id INTEGER,
    source_label TEXT,
    source_homepage TEXT,
    signals TEXT,             -- JSON from the site inspector
    ai_decision TEXT,         -- keep | remove | skip
    ai_confidence REAL,
    ai_reasons TEXT,          -- JSON list
    ai_removal_reason TEXT,
    model_version TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'pending',   -- pending | approved | overridden | pushed | push_failed
    human_decision TEXT,
    human_note TEXT,
    reviewer TEXT,
    reviewed_at TEXT,
    pushed_at TEXT,
    push_error TEXT,
    UNIQUE(queue_guid, item_id)
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with session() as c:
        c.executescript(SCHEMA)


def rows(cur) -> list[dict]:
    out = []
    for r in cur.fetchall():
        d = dict(r)
        for k in ("actors", "qa_flags", "signals", "ai_reasons"):
            if k in d and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        out.append(d)
    return out
