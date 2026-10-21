"""Step 3 — get the data back out.

Implements a subset of the canonical query set (proposal §6.5) over the
SQLite store. Responses contain derived facts + minimal provenance only;
article text never leaves the Spark (proposal §3.5).
"""
import datetime as dt
import statistics
from collections import defaultdict

from ..db import rows, session


def _since(days: int | None) -> str:
    return (dt.date.today() - dt.timedelta(days=days or 36500)).isoformat()


def events(country=None, event_types=None, sector=None, since_days=None, min_sources=1,
           sort="last_date", limit=200) -> list[dict]:
    q = ["SELECT * FROM event_clusters WHERE last_date >= ? AND source_count >= ?"]
    args: list = [_since(since_days), min_sources]
    if country:
        q.append("AND country = ?"); args.append(country)
    if event_types:
        q.append(f"AND event_type IN ({','.join('?' * len(event_types))})"); args += list(event_types)
    if sector:
        q.append("AND sector = ?"); args.append(sector)
    order = {"source_count": "source_count DESC, last_date DESC",
             "confidence": "confidence DESC"}.get(sort, "last_date DESC")
    q.append(f"ORDER BY {order} LIMIT ?"); args.append(limit)
    with session() as c:
        return rows(c.execute(" ".join(q), args))


def cluster_detail(cluster_id: int) -> dict | None:
    with session() as c:
        cl = rows(c.execute("SELECT * FROM event_clusters WHERE id=?", (cluster_id,)))
        if not cl:
            return None
        cl = cl[0]
        mentions = rows(c.execute(
            """SELECT m.id, m.event_type, m.sector, m.report_date, m.event_start, m.admin1, m.admin2,
                      m.location_text, m.admin_level, m.geo_confidence, m.killed, m.injured, m.displaced,
                      m.affected, m.actors, m.summary, m.confidence, m.model_version, m.extracted_at,
                      a.id AS document_id, a.url, a.media_name AS outlet, a.publish_date, a.language
               FROM event_mentions m JOIN articles a ON a.id = m.article_id
               WHERE m.cluster_id = ? ORDER BY a.publish_date""", (cluster_id,)))
    if cl["sensitive"]:   # protection events: no fine location text, no actor attribution (§5.10)
        for m in mentions:
            m["location_text"] = None
            m["actors"] = []
    cl["mentions"] = mentions
    return cl


# ---- canonical queries ------------------------------------------------------
def q_flash_triage(country: str, days: int = 14):
    """§6.5 #1: conflict + displacement clusters, last 14 days, ≥2 sources, by source count."""
    return events(country, ["armed_conflict", "displacement"], since_days=days, min_sources=2,
                  sort="source_count")


def q_monthly_trend(country: str, months: int = 36):
    """§6.5 #3: monthly event-cluster count by type and sector."""
    with session() as c:
        return rows(c.execute(
            """SELECT substr(first_date,1,7) AS month, event_type, sector, COUNT(*) AS clusters
               FROM event_clusters WHERE country=? AND first_date >= ?
               GROUP BY month, event_type, sector ORDER BY month""",
            (country, _since(months * 31))))


def q_early_warning(country: str):
    """§6.5 #5: event types whose 30-day count exceeds the 12-month monthly mean by >2 SD."""
    with session() as c:
        data = rows(c.execute(
            "SELECT event_type, first_date FROM event_clusters WHERE country=? AND first_date >= ?",
            (country, _since(365))))
    today = dt.date.today()
    by_type: dict[str, list[int]] = defaultdict(lambda: [0] * 12)
    for r in data:
        age = (today - dt.date.fromisoformat(r["first_date"])).days
        by_type[r["event_type"]][min(11, age // 30)] += 1
    out = []
    for t, buckets in by_type.items():
        hist = buckets[1:]
        mean, sd = statistics.mean(hist), statistics.pstdev(hist)
        out.append({"event_type": t, "last_30d": buckets[0], "monthly_mean_12m": round(mean, 2),
                    "sd": round(sd, 2), "alert": buckets[0] > mean + 2 * sd and buckets[0] >= 2,
                    "note": "baseline < 3 months: alert not meaningful" if sum(hist) < 3 else None})
    return sorted(out, key=lambda r: -r["last_30d"])


def q_source_gap(country: str):
    """§6.5 #6: coverage confidence by Admin1 (outlets and mentions per unit)."""
    with session() as c:
        return rows(c.execute(
            """SELECT COALESCE(m.admin1,'(unresolved)') AS admin1,
                      COUNT(DISTINCT a.media_name) AS outlets, COUNT(*) AS mentions,
                      ROUND(AVG(m.geo_confidence),2) AS avg_geo_conf,
                      ROUND(MIN(1.0, COUNT(DISTINCT a.media_name) / 3.0), 2) AS coverage_confidence
               FROM event_mentions m JOIN articles a ON a.id=m.article_id
               WHERE m.country=? GROUP BY 1 ORDER BY coverage_confidence, mentions""", (country,)))


def q_sector(country: str, sector: str = "wash", days: int = 30):
    """§6.5 #8: events tagged to a sector with affected population where available."""
    return events(country, sector=sector, since_days=days)


def q_displacement(country: str, days: int = 90):
    """§6.5 #9: displacement clusters with population figures, source count and confidence."""
    return [e for e in events(country, ["displacement", "natural_hazard"], since_days=days)
            if e["displaced_range"]]


CANONICAL = {
    "flash_triage": ("Flash appeal triage: conflict & displacement, last 14 days, ≥2 sources", q_flash_triage),
    "monthly_trend": ("Monthly event count by type and sector", q_monthly_trend),
    "early_warning": ("Early-warning: 30-day spike vs 12-month baseline", q_early_warning),
    "source_gap": ("Source gap: coverage confidence by Admin1", q_source_gap),
    "wash_30d": ("Cluster coordination: WASH events, last 30 days", q_sector),
    "displacement_90d": ("Displacement with population figures, last 90 days", q_displacement),
}


def stats(run_id: int | None = None) -> dict:
    """Counts for the whole database, or for one ingest run's articles. Clustering always
    spans the whole database; with run_id, clusters = clusters containing that run's mentions."""
    with session() as c:
        arts = "SELECT * FROM articles" + (" WHERE ingest_run_id=:run" if run_id is not None else "")
        one = lambda sql: c.execute(sql.replace("{arts}", arts), {"run": run_id}).fetchone()[0]
        return {
            "run_id": run_id,
            "articles": one("SELECT COUNT(*) FROM ({arts})"),
            "filter_passed": one("SELECT COUNT(*) FROM ({arts}) WHERE filter_passed=1"),
            "filter_dropped": one("SELECT COUNT(*) FROM ({arts}) WHERE filter_passed=0"),
            "extracted": one("SELECT COUNT(*) FROM ({arts}) WHERE extracted_at IS NOT NULL"),
            "mentions": one("SELECT COUNT(*) FROM event_mentions m JOIN ({arts}) a ON a.id=m.article_id"),
            "clusters": one("""SELECT COUNT(DISTINCT m.cluster_id) FROM event_mentions m
                               JOIN ({arts}) a ON a.id=m.article_id""") if run_id is not None
                        else one("SELECT COUNT(*) FROM event_clusters"),
            "countries": [r[0] for r in c.execute(
                """SELECT country_hint FROM articles WHERE country_hint IS NOT NULL
                   UNION SELECT country FROM event_clusters WHERE country IS NOT NULL ORDER BY 1""")],
            "runs": rows(c.execute("SELECT * FROM ingest_runs ORDER BY id DESC LIMIT 5")),
        }


def graph(country: str | None = None) -> dict:
    """Nodes/edges view (event cluster -> place / sector / outlet) for a graph DB or viz."""
    nodes, edges = {}, []
    for cl in events(country, limit=1000):
        cid = f"event:{cl['id']}"
        nodes[cid] = {"id": cid, "kind": "EventCluster", "label": cl["event_type"], "confidence": cl["confidence"]}
        place = f"place:{cl['country']}/{cl['admin1']}/{cl['admin2'] or ''}"
        nodes[place] = {"id": place, "kind": "Place", "label": cl["admin2"] or cl["admin1"] or cl["country"]}
        nodes[f"sector:{cl['sector']}"] = {"id": f"sector:{cl['sector']}", "kind": "Sector", "label": cl["sector"]}
        edges += [{"source": cid, "target": place, "rel": "OCCURRED_IN"},
                  {"source": cid, "target": f"sector:{cl['sector']}", "rel": "AFFECTS_SECTOR"}]
        for m in (cluster_detail(cl["id"]) or {}).get("mentions", []):
            oid = f"outlet:{m['outlet']}"
            nodes[oid] = {"id": oid, "kind": "Outlet", "label": m["outlet"]}
            edges.append({"source": cid, "target": oid, "rel": "REPORTED_BY", "document_id": m["document_id"]})
    return {"nodes": list(nodes.values()), "edges": edges}
