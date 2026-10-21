"""AI pre-review for collection-review-tool queues, with a mandatory human step.

  1. pull undecided items from a reviewer queue
  2. inspect each source's website        (inspector.py)
  3. LLM applies the queue's guidelines  -> keep / remove / skip + confidence + reasons
  4. store as a *suggestion* (status=pending)        <- nothing is written to the tool yet
  5. a human approves or overrides in the dashboard  -> only then POST .../decide
"""
import json
import logging
import threading

from .. import llm
from ..config import settings
from ..db import rows, session
from . import inspector
from .crt_client import get_client

log = logging.getLogger("review-agent")

SYSTEM = """You assist human reviewers who curate Media Cloud news-source collections.
Apply the collection's review guidelines to ONE source, using only the evidence provided
(signals collected by a crawler from its homepage and About page). Do not guess beyond it.

Return JSON:
{"decision": "keep" | "remove" | "skip",
 "confidence": number 0-1,
 "reasons": [2-4 short evidence-based bullet strings],
 "removal_reason": short reason a reviewer would record (required when decision is "remove", else null),
 "guideline_rule": the guideline line that decided it}

Use "skip" when the evidence is thin, contradictory, or the site could not be loaded for a
reason that may be temporary (timeouts). A DNS failure or long inactivity counts as "not active"."""


def _heuristic(sig: dict) -> dict:
    if not sig.get("reachable"):
        err = (sig.get("error") or "").lower()
        if "dns" in err or "nxdomain" in err or sig.get("http_status") in (404, 410):
            return {"decision": "remove", "confidence": 0.78, "removal_reason": "Site no longer active",
                    "reasons": [f"Homepage could not be loaded: {sig.get('error') or sig.get('http_status')}"],
                    "guideline_rule": "Remove if the site is no longer active"}
        return {"decision": "skip", "confidence": 0.4, "removal_reason": None,
                "reasons": [f"Temporary fetch problem: {sig.get('error')}"], "guideline_rule": "Skip if unsure"}
    if sig["satire_phrases"]:
        return {"decision": "remove", "confidence": 0.88, "removal_reason": "Satirical content",
                "reasons": [f"Site describes itself with: {', '.join(sig['satire_phrases'])}"],
                "guideline_rule": "Remove if content is satirical or unreliable"}
    if len(sig["pr_or_company_phrases"]) >= 2 and sig["bylines_found"] == 0:
        return {"decision": "remove", "confidence": 0.84, "removal_reason": "Company / PR website without editorial function",
                "reasons": [f"Commercial signals: {', '.join(sig['pr_or_company_phrases'][:4])}", "No bylines found"],
                "guideline_rule": "Remove if it is a blog, PR site, or company website"}
    if (sig.get("external_link_ratio") or 0) > 0.6 or len(sig["aggregator_phrases"]) >= 2:
        return {"decision": "remove", "confidence": 0.82, "removal_reason": "Aggregator: republishes other outlets",
                "reasons": [f"{sig['external_article_links']} of {sig['external_article_links'] + sig['internal_article_links']}"
                            " article links point to other sites", f"Phrases: {', '.join(sig['aggregator_phrases'][:3])}"],
                "guideline_rule": "Remove if the site is an aggregator"}
    days = sig.get("days_since_latest")
    if days is not None and days > 365:
        return {"decision": "remove", "confidence": 0.74, "removal_reason": "Inactive: no content in the last year",
                "reasons": [f"Most recent date on homepage is {days} days old"], "guideline_rule": "Remove if no longer active"}
    if "blog" in (sig.get("title") or "").lower() and sig["bylines_found"] <= 1:
        return {"decision": "remove", "confidence": 0.66, "removal_reason": "Personal blog",
                "reasons": ["Title identifies the site as a personal blog", "Single author"],
                "guideline_rule": "Remove if it is a blog"}
    recent = days is not None and days <= 30
    if recent and sig["bylines_found"] >= 2 and sig["about_page_found"]:
        return {"decision": "keep", "confidence": 0.87, "removal_reason": None,
                "reasons": [f"{sig['bylines_found']} bylines on homepage", "About page lists editorial team",
                            f"Updated {days} day(s) ago"], "guideline_rule": "Keep: original reporting, editorial team"}
    if recent and sig["bylines_found"] >= 2:
        return {"decision": "keep", "confidence": 0.72, "removal_reason": None,
                "reasons": [f"{sig['bylines_found']} bylines, updated {days} day(s) ago", "No About page found"],
                "guideline_rule": "Keep: original reporting"}
    return {"decision": "skip", "confidence": 0.5, "removal_reason": None,
            "reasons": ["Evidence is mixed (few bylines or little text news)"], "guideline_rule": "Skip if unsure"}


def _apply_policy(out: dict) -> dict:
    d = out.get("decision")
    if d not in ("keep", "remove", "skip"):
        d = "skip"
    conf = max(0.0, min(1.0, float(out.get("confidence") or 0)))
    reasons = [str(r) for r in (out.get("reasons") or [])][:5]
    if d != "skip" and conf < settings.REVIEW_MIN_CONFIDENCE:
        reasons.append(f"AI leaned '{d}' at {conf:.2f}, below the {settings.REVIEW_MIN_CONFIDENCE:.2f} "
                       "threshold, so it is proposed as skip")
        d = "skip"
    rr = (out.get("removal_reason") or "").strip() or None
    if d == "remove" and not rr:
        rr = "; ".join(reasons[:1]) or "Does not meet collection guidelines"
    return {"decision": d, "confidence": round(conf, 3), "reasons": reasons,
            "removal_reason": rr if d == "remove" else None, "guideline_rule": out.get("guideline_rule")}


def review_item(guid: str, item: dict, guidelines: str) -> dict:
    url = item.get("source_homepage") or item.get("source_label") or ""
    sig = inspector.inspect(url)
    user = (f"GUIDELINES:\n{guidelines}\n\nSOURCE: {item.get('source_label')} ({url})\n"
            f"MEDIA CLOUD METADATA: {json.dumps(item.get('source_metadata') or {})}\n"
            f"CRAWLER SIGNALS:\n{json.dumps(sig, ensure_ascii=False, indent=1)}")
    raw, mv = llm.chat_json(SYSTEM, user, fallback=lambda: _heuristic(sig))
    out = _apply_policy(raw)
    with session() as c:
        c.execute(
            """INSERT INTO review_suggestions (queue_guid, item_id, source_id, source_label, source_homepage,
                   signals, ai_decision, ai_confidence, ai_reasons, ai_removal_reason, model_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(queue_guid, item_id) DO UPDATE SET signals=excluded.signals,
                   ai_decision=excluded.ai_decision, ai_confidence=excluded.ai_confidence,
                   ai_reasons=excluded.ai_reasons, ai_removal_reason=excluded.ai_removal_reason,
                   model_version=excluded.model_version, created_at=datetime('now'), status='pending',
                   human_decision=NULL, human_note=NULL, reviewer=NULL, reviewed_at=NULL, push_error=NULL""",
            (guid, item["id"], item.get("source_id"), item.get("source_label"), url,
             json.dumps(sig, ensure_ascii=False), out["decision"], out["confidence"],
             json.dumps(out["reasons"] + ([f"Rule: {out['guideline_rule']}"] if out["guideline_rule"] else []),
                        ensure_ascii=False), out["removal_reason"], mv))
    return out


# ------------------------------------------------------------------ background job
JOB = {"running": False, "queue_guid": None, "done": 0, "total": 0, "failed": 0, "error": None}
_lock = threading.Lock()


def run_queue(guid: str, limit: int = 200, redo: bool = False):
    client = get_client()
    with _lock:
        JOB.update(running=True, queue_guid=guid, done=0, total=0, failed=0, error=None)
    try:
        guidelines = client.guidelines(guid)
        items = client.items(guid, decision="undecided", limit=limit)
        if not redo:
            with session() as c:
                have = {r[0] for r in c.execute(
                    "SELECT item_id FROM review_suggestions WHERE queue_guid=? AND status IN ('pending','pushed')", (guid,))}
            items = [i for i in items if i["id"] not in have and not i.get("is_new_source")]
        JOB["total"] = len(items)
        streak = 0
        for it in items:
            try:
                review_item(guid, it, guidelines)
                streak = 0
            except Exception as e:
                log.exception("review failed for item %s", it.get("id"))
                JOB["failed"] += 1
                streak += 1
                JOB["error"] = f"{JOB['failed']} item(s) failed: {str(e)[:300]}"
                if streak >= 3:
                    JOB["error"] = f"Stopped after 3 consecutive failures: {str(e)[:300]}"
                    break
            JOB["done"] += 1
    except Exception as e:
        JOB["error"] = str(e)
        log.exception("queue run failed")
    finally:
        JOB["running"] = False


def start_background(guid: str, limit: int = 200, redo: bool = False) -> bool:
    if JOB["running"]:
        return False
    threading.Thread(target=run_queue, args=(guid, limit, redo), daemon=True).start()
    return True


# ------------------------------------------------------------------ human step
def suggestions(guid: str, status: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM review_suggestions WHERE queue_guid=?", [guid]
    if status:
        q += " AND status=?"; args.append(status)
    q += " ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'push_failed' THEN 1 ELSE 2 END, ai_confidence ASC"
    with session() as c:
        return rows(c.execute(q, args))


def confirm(suggestion_id: int, decision: str, reviewer: str, note: str | None = None,
            removal_reason: str | None = None) -> dict:
    """Human approves (same decision) or overrides; then the decision is pushed to the tool."""
    if decision not in ("keep", "remove", "skip"):
        raise ValueError("decision must be keep, remove or skip")
    if not reviewer:
        raise ValueError("reviewer name is required")
    with session() as c:
        s = rows(c.execute("SELECT * FROM review_suggestions WHERE id=?", (suggestion_id,)))
        if not s:
            raise KeyError(suggestion_id)
        s = s[0]
    agreed = decision == s["ai_decision"]
    rr = (removal_reason or s["ai_removal_reason"] or note or "").strip() if decision == "remove" else None
    if decision == "remove" and not rr:
        raise ValueError("removal_reason is required for remove")
    tag = f"[AI {s['ai_decision']} {s['ai_confidence']:.2f}, human {'agreed' if agreed else 'overrode'}: {reviewer}]"
    skip_note = f"{tag} {note or ''}".strip() if decision == "skip" else None
    try:
        get_client().decide(s["queue_guid"], s["item_id"], decision,
                            removal_reason=f"{rr} {tag}" if rr else None, skip_note=skip_note)
        status, err = "pushed", None
    except Exception as e:
        status, err = "push_failed", str(e)[:500]
    with session() as c:
        c.execute("""UPDATE review_suggestions SET human_decision=?, human_note=?, reviewer=?,
                     reviewed_at=datetime('now'), status=?, push_error=?,
                     pushed_at=CASE WHEN ?='pushed' THEN datetime('now') END WHERE id=?""",
                  (decision, note, reviewer, status, err, status, suggestion_id))
    return {"id": suggestion_id, "status": status, "agreed_with_ai": agreed, "error": err}


def metrics(guid: str) -> dict:
    with session() as c:
        r = c.execute("""SELECT COUNT(*) total,
                 SUM(status='pending') pending,
                 SUM(human_decision IS NOT NULL) reviewed,
                 SUM(human_decision = ai_decision) agreed,
                 SUM(status='push_failed') push_failed
               FROM review_suggestions WHERE queue_guid=?""", (guid,)).fetchone()
        by = rows(c.execute("""SELECT ai_decision, COUNT(*) n, SUM(human_decision=ai_decision) agreed,
                                      SUM(human_decision IS NOT NULL) reviewed
                               FROM review_suggestions WHERE queue_guid=? GROUP BY ai_decision""", (guid,)))
    d = dict(r)
    d["agreement_rate"] = round(d["agreed"] / d["reviewed"], 3) if d["reviewed"] else None
    d["by_ai_decision"] = by
    return d
