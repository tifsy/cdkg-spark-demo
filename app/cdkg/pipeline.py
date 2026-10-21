"""Step 2 — structure the raw articles on the Spark.

  filter    stage-1 recall filter (proposal §A.3)      -> articles.filter_*
  extract   ontology-guided LLM extraction (§3.7, §A.4) -> event_mentions
  cluster   probabilistic event clusters (§3.8)         -> event_clusters
"""
import datetime as dt
import json
import logging
import re

from .. import llm
from ..config import settings
from ..db import rows, session
from .ontology import (EVENT_TYPES, ONTOLOGY_VERSION, SECTORS, SENSITIVE_TYPES, geocode,
                       schema_for_prompt)

log = logging.getLogger("pipeline")

DEFAULT_SECTOR = {"armed_conflict": "protection", "natural_hazard": "emergency_shelter",
                  "displacement": "emergency_shelter", "epidemic": "health",
                  "food_insecurity": "food_security", "protection_incident": "protection"}


# --------------------------------------------------------------------------- filter
def _kw_match(kw: str, low: str) -> bool:
    # word-start boundary for Latin keywords ("ration" must not match "administration");
    # plain substring for Arabic etc.
    return re.search(rf"\b{re.escape(kw)}", low) is not None if kw.isascii() else kw in low


def _keyword_hits(text: str) -> dict[str, list[str]]:
    low = text.lower()
    out = {}
    for t, spec in EVENT_TYPES.items():
        found = [k for k in spec["keywords"] if _kw_match(k, low)]
        if found:
            out[t] = found
    return out


def run_filter(threshold: int = 1) -> dict:
    """Cheap keyword filter. On the real system this is a small fine-tuned
    classifier running inside Media Cloud; decisions are logged either way."""
    passed = dropped = 0
    seen_hashes: set[str] = set()
    with session() as c:
        arts = c.execute("SELECT id, title, text, text_hash FROM articles "
                         "WHERE filter_passed IS NULL ORDER BY publish_date").fetchall()
        for h in c.execute("SELECT text_hash FROM articles WHERE filter_passed=1"):
            seen_hashes.add(h[0])
        for a in arts:
            hits = _keyword_hits(f"{a['title']} {a['text'] or ''}")
            score = sum(len(v) for v in hits.values())
            if a["text_hash"] in seen_hashes:
                ok, reason = 0, "near-duplicate of an already-passed article"
            elif score >= threshold:
                ok, reason = 1, "keywords: " + "; ".join(f"{t}={','.join(v[:3])}" for t, v in hits.items())
                seen_hashes.add(a["text_hash"])
            else:
                ok, reason = 0, "no priority-event keywords"
            c.execute("UPDATE articles SET filter_score=?, filter_passed=?, filter_reason=? WHERE id=?",
                      (score, ok, reason, a["id"]))
            passed += ok
            dropped += 1 - ok
    return {"passed": passed, "dropped": dropped}


# --------------------------------------------------------------------------- extract
# Bump when SYSTEM_PROMPT changes; appended to LLM model_version so mentions from
# different prompts stay distinguishable.
PROMPT_VERSION = "extract-v3"
LATE_REPORT_DAYS = 30   # event_start this long before the report date -> QA flag on the cluster

SYSTEM_PROMPT = f"""You are an information-extraction system for the Crisis–Development Knowledge Graph
(ontology {ONTOLOGY_VERSION}). Read one news article (any language) and extract every distinct
real-world crisis event that matches the allowed event types.

Rules:
- Only report numbers that are explicitly stated in the article. Never infer, sum or average.
- Never output names of individual people (victims, witnesses, perpetrators). Use categories.
- Actors are "as reported in source"; do not judge who is responsible.
- Actors are only the parties to the event (armed groups, forces, militias, authorities carrying
  out an action). Never list victims or affected people, aid workers or agencies, health
  facilities, officials or outlets that report the event, or hazards (floods, cyclones, shelling).
  If no party is named, return [].
- event_start / event_end: only when the article states a date or a specific relative day.
  Resolve "today", "yesterday", "on Monday" etc. against the Published date given above the
  article ("today" = the Published date). Vague time phrases ("this week", "recently",
  "in recent days", "last month") and no time reference at all give null. Never guess a date.
- One article can contain several events (e.g. an attack AND the displacement it caused).
- If nothing matches, return {{"events": []}}.

{schema_for_prompt()}"""

_NUM = r"(\d{1,3}(?:,\d{3})+|\d+)"
_PATTERNS = {
    "killed": [rf"{_NUM}\s+(?:\w+\s+){{0,3}}(?:were\s+)?(?:killed|dead|died|deaths|drowned)",
               rf"(?:killed|deaths of)\s+{_NUM}", rf"{_NUM}\s+have died", rf"(?:مقتل)\s+{_NUM}"],
    "injured": [rf"{_NUM}\s+(?:\w+\s+){{0,3}}(?:were\s+)?(?:injured|wounded)"],
    "displaced": [rf"{_NUM}\s+(?:\w+\s+){{0,3}}(?:fled|displaced|homeless|moved to shelters|in shelters)",
                  rf"{_NUM}\s+(?:are|have)\s+(?:in|moved to)\s+shelters", rf"(?:نزوح\s+نحو)\s+{_NUM}"],
    "affected": [rf"{_NUM}\s+(?:\w+\s+){{0,3}}(?:affected|stranded|cases|hospitali[sz]ations|patients)"],
}
_NUMBERS_FOR = {"armed_conflict": ["killed", "injured"], "displacement": ["displaced"],
                "natural_hazard": ["killed", "affected", "displaced"], "epidemic": ["killed", "affected"],
                "food_insecurity": ["affected"], "protection_incident": ["affected"]}


def _grab(text: str, key: str) -> int | None:
    vals = []
    for p in _PATTERNS[key]:
        vals += [int(m.group(1).replace(",", "")) for m in re.finditer(p, text, re.I)]
    return max(vals) if vals else None


def _heuristic_extract(article: dict) -> dict:
    text = f"{article['title']}. {article['text'] or ''}"
    events = []
    for etype, kws in _keyword_hits(text).items():
        ev = {"event_type": etype, "sector": DEFAULT_SECTOR[etype], "country": article["country_hint"],
              "location_text": None, "event_start": None, "actors": [],
              "summary": f"{EVENT_TYPES[etype]['label']} reported by {article['media_name']}.",
              "confidence": min(0.8, 0.45 + 0.1 * len(kws))}
        for k in _NUMBERS_FOR[etype]:
            ev[k] = _grab(text, k)
        events.append(ev)
    return {"events": events}


def _int(v):
    try:
        return int(str(v).replace(",", "")) if v not in (None, "", "null") else None
    except ValueError:
        return None


def _date(v, report_date: str) -> str | None:
    """ISO date or None: drop dates that don't parse or lie after the report date."""
    try:
        d = dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None
    try:
        if d > dt.date.fromisoformat(report_date[:10]):
            return None
    except (TypeError, ValueError):
        pass
    return d.isoformat()


def _normalise(ev: dict, article: dict, model_version: str) -> dict | None:
    etype = ev.get("event_type")
    if etype not in EVENT_TYPES:
        return None
    sector = ev.get("sector") if ev.get("sector") in SECTORS else DEFAULT_SECTOR[etype]
    country = ev.get("country") or article["country_hint"]
    text = f"{article['title']} {article['text'] or ''}"
    geo = geocode(country, ev.get("admin2"), ev.get("admin1"), ev.get("location_text"))
    if geo["admin_level"] == 0:            # model gave nothing usable: fall back to article text
        geo = geocode(country, text)
    actors = [a for a in (ev.get("actors") or []) if isinstance(a, str)][:5]
    pop = ev.get("population_group")
    start = _date(ev.get("event_start"), article["publish_date"])
    end = _date(ev.get("event_end"), article["publish_date"])
    if start and end and end < start:
        end = None
    for k, v in (("event_start", start), ("event_end", end)):
        if ev.get(k) and not v:
            log.info("dropped %s=%r for %s (unparseable or after publish date %s)",
                     k, ev.get(k), article["id"], article["publish_date"])
    return {
        "article_id": article["id"], "event_type": etype, "sector": sector,
        "report_date": article["publish_date"], "event_start": start,
        "event_end": end, "country": geo.get("country", country),
        "admin1": geo["admin1"], "admin2": geo["admin2"],
        "location_text": ev.get("location_text") or geo["admin2"] or geo["admin1"],
        "admin_level": geo["admin_level"], "geo_confidence": geo["geo_confidence"],
        "population_group": pop, "population_not_reported": int(not pop),
        "killed": _int(ev.get("killed")), "injured": _int(ev.get("injured")),
        "displaced": _int(ev.get("displaced")), "affected": _int(ev.get("affected")),
        "actors": json.dumps(actors, ensure_ascii=False),
        "summary": (ev.get("summary") or "")[:400],
        "confidence": round(float(ev.get("confidence") or 0.5), 3),
        "sensitive": int(etype in SENSITIVE_TYPES), "model_version": model_version,
    }


def run_extract(limit: int = 200) -> dict:
    with session() as c:
        arts = rows(c.execute(
            "SELECT * FROM articles WHERE filter_passed=1 AND extracted_at IS NULL LIMIT ?", (limit,)))
    n_events, errors, versions, streak, stopped = 0, 0, set(), 0, None
    for a in arts:
        if streak >= 3:     # e.g. wrong API key or server down: don't hammer it for every article
            stopped = f"stopped after 3 consecutive LLM errors: {last_error}"
            break
        body = (a["text"] or "")[:8000]
        user = (f"Outlet: {a['media_name']}\nPublished: {a['publish_date']}\nLanguage: {a['language']}\n"
                f"Reference country: {a['country_hint']}\nTitle: {a['title']}\n\n{body}")
        try:
            out, mv = llm.chat_json(SYSTEM_PROMPT, user, fallback=lambda a=a: _heuristic_extract(a))
            if not mv.startswith("heuristic"):
                mv = f"{mv}+{PROMPT_VERSION}"
            versions.add(mv)
            evs = [e for e in (_normalise(ev, a, mv) for ev in out.get("events", [])) if e]
            with session() as c:
                c.execute("DELETE FROM event_mentions WHERE article_id=?", (a["id"],))
                for e in evs:
                    c.execute(f"INSERT INTO event_mentions ({','.join(e)}) VALUES ({','.join('?' * len(e))})",
                              tuple(e.values()))
                c.execute("UPDATE articles SET extracted_at=datetime('now'), extraction_error=NULL WHERE id=?",
                          (a["id"],))
            n_events += len(evs)
            streak = 0
        except Exception as ex:
            errors += 1
            streak += 1
            last_error = str(ex)[:300]
            log.exception("extraction failed for %s", a["id"])
            with session() as c:
                c.execute("UPDATE articles SET extraction_error=? WHERE id=?", (str(ex)[:500], a["id"]))
    out = {"articles": len(arts), "event_mentions": n_events, "errors": errors,
           "model_versions": sorted(versions)}
    if stopped:
        out["stopped"] = stopped
    return out


# --------------------------------------------------------------------------- cluster
def _day(m: dict) -> dt.date:
    s = m.get("event_start") or m.get("report_date")
    try:
        return dt.date.fromisoformat(s[:10])
    except Exception:
        return dt.date.today()


def _rng(vals: list[int]) -> str | None:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return str(vals[0]) if vals[0] == vals[-1] else f"{vals[0]}-{vals[-1]}"


def run_cluster(window_days: int = 2) -> dict:
    """Greedy linkage: same type + country + admin1, compatible admin2, within ±window."""
    with session() as c:
        ms = rows(c.execute("""SELECT m.*, a.media_name FROM event_mentions m
                                JOIN articles a ON a.id=m.article_id"""))
    ms.sort(key=_day)
    clusters: list[dict] = []
    for m in ms:
        best, best_score = None, 0.0
        for cl in clusters:
            if (cl["event_type"], cl["country"], cl["admin1"]) != (m["event_type"], m["country"], m["admin1"]):
                continue
            gap = abs((_day(m) - cl["last"]).days)
            if gap > window_days:
                continue
            if m["admin2"] and cl["admin2"] and m["admin2"] != cl["admin2"]:
                continue
            geo = 1.0 if (m["admin2"] and m["admin2"] == cl["admin2"]) else 0.7
            score = 0.6 * geo + 0.4 * (1 - gap / (window_days + 1))
            if score > best_score:
                best, best_score = cl, score
        if best:
            best["members"].append(m)
            best["scores"].append(best_score)
            best["last"] = max(best["last"], _day(m))
            best["admin2"] = best["admin2"] or m["admin2"]
        else:
            clusters.append({"event_type": m["event_type"], "country": m["country"], "admin1": m["admin1"],
                             "admin2": m["admin2"], "first": _day(m), "last": _day(m),
                             "members": [m], "scores": []})

    with session() as c:
        c.execute("UPDATE event_mentions SET cluster_id=NULL")
        c.execute("DELETE FROM event_clusters")
        for cl in clusters:
            mem = cl["members"]
            outlets = {m["media_name"] for m in mem}
            flags = []
            if len(outlets) == 1:
                flags.append("single_source")
            if (cl["last"] - cl["first"]).days > 7:
                flags.append("temporal_span_gt_7d")
            if any(m["event_start"] and (dt.date.fromisoformat(m["report_date"][:10])
                                         - dt.date.fromisoformat(m["event_start"][:10])).days > LATE_REPORT_DAYS
                   for m in mem):
                flags.append(f"event_date_gt_{LATE_REPORT_DAYS}d_before_report")
            for k in ("killed", "displaced", "affected"):
                vals = [m[k] for m in mem if m[k]]
                if vals and max(vals) > 10 * min(vals):
                    flags.append(f"contradiction_{k}")
            link = round(sum(cl["scores"]) / len(cl["scores"]), 3) if cl["scores"] else 1.0
            if link < 0.75 and len(mem) > 1:
                flags.append("uncertain_coreference")
            conf = sum(m["confidence"] for m in mem) / len(mem)
            conf = round(min(0.99, conf * (0.6 + 0.4 * max(m["geo_confidence"] for m in mem))
                             + 0.08 * (len(outlets) - 1)), 3)
            sectors = [m["sector"] for m in mem]
            rep = max(mem, key=lambda m: m["confidence"])
            cur = c.execute(
                """INSERT INTO event_clusters (event_type, sector, country, admin1, admin2, first_date,
                   last_date, source_count, mention_count, killed_range, injured_range, displaced_range,
                   affected_range, linkage_score, confidence, qa_flags, summary, sensitive)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cl["event_type"], max(set(sectors), key=sectors.count), cl["country"], cl["admin1"],
                 cl["admin2"], cl["first"].isoformat(), cl["last"].isoformat(), len(outlets), len(mem),
                 _rng([m["killed"] for m in mem]), _rng([m["injured"] for m in mem]),
                 _rng([m["displaced"] for m in mem]), _rng([m["affected"] for m in mem]),
                 link, conf, json.dumps(flags), rep["summary"], int(any(m["sensitive"] for m in mem))))
            c.executemany("UPDATE event_mentions SET cluster_id=? WHERE id=?",
                          [(cur.lastrowid, m["id"]) for m in mem])
    return {"mentions": len(ms), "clusters": len(clusters)}


def run_all() -> dict:
    return {"filter": run_filter(), "extract": run_extract(), "cluster": run_cluster()}
