"""Web server for both demos. Run on the DGX Spark, reach it over Tailscale.

    uvicorn app.main:app --host 0.0.0.0 --port 8080
"""
import logging
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm
from .cdkg import ingest, pipeline, queries
from .config import settings
from .db import init_db, rows, session
from .review import agent
from .review.crt_client import MockCRT, get_client
from .review.fixtures import MOCK_QUEUE_GUID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
init_db()
app = FastAPI(title="CDKG + Collection Review demo (DGX Spark)", version="0.1")
STATIC = Path(__file__).parent / "static"


def write_guard(x_app_token: str | None = Header(default=None)):
    if settings.APP_TOKEN and x_app_token != settings.APP_TOKEN:
        raise HTTPException(401, "Missing or wrong X-App-Token header")


def tailnet_user(request: Request) -> str | None:
    # `tailscale serve` injects the caller's tailnet identity into proxied requests.
    return request.headers.get("Tailscale-User-Login") or request.headers.get("Tailscale-User-Name")


@app.get("/api/health")
def health(request: Request):
    return {"llm": llm.health(), "mediacloud_key": bool(settings.MEDIACLOUD_API_KEY),
            "crt_mode": settings.CRT_MODE, "crt_base_url": settings.CRT_BASE_URL if settings.CRT_MODE == "live" else None,
            "inspector": f"{settings.INSPECTOR_MODE}/{settings.INSPECTOR_BACKEND}",
            "review_min_confidence": settings.REVIEW_MIN_CONFIDENCE,
            "data_dir": str(settings.DATA_DIR), "tailnet_user": tailnet_user(request),
            "token_required": bool(settings.APP_TOKEN)}


# =============================================================== Task 1: CDKG
CDKG_JOB = {"running": False, "step": None, "result": None, "error": None}


def _bg(fn, label):
    def run():
        CDKG_JOB.update(running=True, step=label, result=None, error=None)
        try:
            CDKG_JOB["result"] = fn()
        except Exception as e:
            CDKG_JOB["error"] = str(e)
        finally:
            CDKG_JOB["running"] = False
    if CDKG_JOB["running"]:
        raise HTTPException(409, f"Busy with: {CDKG_JOB['step']}")
    threading.Thread(target=run, daemon=True).start()
    return {"started": label}


class IngestReq(BaseModel):
    source: str = "random"           # random | text | sample | mediacloud
    country: str | None = "Sudan"    # for text: applied to articles without their own country
    n: int = 60                      # random: number of articles
    seed: int | None = None          # random: same seed -> same articles
    text: str | None = None          # text: pasted text or uploaded file content
    filename: str | None = None      # text: decides the parser (.txt .jsonl .json .csv)
    days: int = 3
    query: str | None = None
    collection_ids: list[int] | None = None
    max_stories: int = 300
    run_pipeline: bool = True


@app.post("/api/cdkg/ingest", dependencies=[Depends(write_guard)])
def cdkg_ingest(req: IngestReq):
    if req.source == "text" and len(req.text or "") > 5_000_000:
        raise HTTPException(413, "Text is larger than 5 MB; use `python -m app.cli ingest-file` instead.")
    def job():
        if req.source == "mediacloud":
            out = {"ingest": ingest.ingest_mediacloud(req.country, req.days, req.query, req.collection_ids,
                                                      req.max_stories)}
        elif req.source == "text":
            out = {"ingest": ingest.ingest_text(req.text or "", req.filename or "", req.country)}
        elif req.source == "random":
            out = {"ingest": ingest.ingest_random(min(req.n, 5000), [req.country] if req.country else None,
                                                  req.days, req.seed)}
        else:
            out = {"ingest": ingest.ingest_sample()}
        if req.run_pipeline:
            out.update(pipeline.run_all())
        return out
    return _bg(job, f"ingest:{req.source}")


@app.post("/api/cdkg/pipeline", dependencies=[Depends(write_guard)])
def cdkg_pipeline():
    return _bg(pipeline.run_all, "pipeline")


@app.post("/api/cdkg/reset", dependencies=[Depends(write_guard)])
def cdkg_reset():
    with session() as c:
        for t in ("event_mentions", "event_clusters", "articles", "ingest_runs"):
            c.execute(f"DELETE FROM {t}")
    return {"ok": True}


@app.get("/api/cdkg/job")
def cdkg_job():
    return CDKG_JOB


@app.get("/api/cdkg/stats")
def cdkg_stats(run_id: int | None = None):
    return queries.stats(run_id)


@app.get("/api/cdkg/events")
def cdkg_events(country: str | None = None, event_type: str | None = None, sector: str | None = None,
                since_days: int | None = None, min_sources: int = 1, sort: str = "last_date"):
    return queries.events(country, [event_type] if event_type else None, sector, since_days, min_sources, sort)


@app.get("/api/cdkg/events/{cluster_id}")
def cdkg_event(cluster_id: int):
    d = queries.cluster_detail(cluster_id)
    if not d:
        raise HTTPException(404)
    return d


@app.get("/api/cdkg/queries")
def cdkg_query_list():
    return [{"name": k, "label": v[0]} for k, v in queries.CANONICAL.items()]


@app.get("/api/cdkg/queries/{name}")
def cdkg_query(name: str, country: str):
    if name not in queries.CANONICAL:
        raise HTTPException(404, "unknown query")
    return {"query": name, "label": queries.CANONICAL[name][0], "country": country,
            "results": queries.CANONICAL[name][1](country)}


@app.get("/api/cdkg/articles")
def cdkg_articles(passed: int | None = None, limit: int = 100):
    cols = ("id, title, url, media_name, language, publish_date, country_hint, filter_score, filter_passed, "
            "filter_reason, extracted_at, extraction_error" + ("" if settings.HIDE_FULLTEXT else ", text"))
    q, args = f"SELECT {cols} FROM articles", []
    if passed is not None:
        q += " WHERE filter_passed=?"; args.append(passed)
    q += " ORDER BY publish_date DESC LIMIT ?"; args.append(limit)
    with session() as c:
        return rows(c.execute(q, args))


@app.get("/api/cdkg/graph")
def cdkg_graph(country: str | None = None):
    return queries.graph(country)


# =============================================================== Task 2: review
@app.get("/api/review/config")
def review_config():
    return {"mode": settings.CRT_MODE, "default_queue": MOCK_QUEUE_GUID if settings.CRT_MODE == "mock" else "",
            "min_confidence": settings.REVIEW_MIN_CONFIDENCE}


@app.get("/api/review/queues/{guid}")
def review_queue(guid: str):
    try:
        q = get_client().queue(guid)
    except Exception as e:
        raise HTTPException(502, f"Could not reach the collection review tool: {e}")
    return {"queue": q, "metrics": agent.metrics(guid), "job": agent.JOB}


class RunReq(BaseModel):
    limit: int = 200
    redo: bool = False


@app.post("/api/review/queues/{guid}/run", dependencies=[Depends(write_guard)])
def review_run(guid: str, req: RunReq):
    if not agent.start_background(guid, req.limit, req.redo):
        raise HTTPException(409, "An AI review run is already in progress")
    return {"started": True}


@app.get("/api/review/job")
def review_job():
    return agent.JOB


@app.get("/api/review/queues/{guid}/suggestions")
def review_suggestions(guid: str, status: str | None = None):
    return agent.suggestions(guid, status)


class ConfirmReq(BaseModel):
    decision: str
    reviewer: str | None = None
    note: str | None = None
    removal_reason: str | None = None


@app.post("/api/review/suggestions/{sid}/confirm", dependencies=[Depends(write_guard)])
def review_confirm(sid: int, req: ConfirmReq, request: Request):
    reviewer = tailnet_user(request) or req.reviewer
    try:
        return agent.confirm(sid, req.decision, reviewer, req.note, req.removal_reason)
    except KeyError:
        raise HTTPException(404)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/review/mock/reset", dependencies=[Depends(write_guard)])
def review_mock_reset():
    if settings.CRT_MODE != "mock":
        raise HTTPException(400, "Only available in mock mode")
    MockCRT().reset()
    with session() as c:
        c.execute("DELETE FROM review_suggestions WHERE queue_guid=?", (MOCK_QUEUE_GUID,))
    return {"ok": True}


# =============================================================== UI
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
