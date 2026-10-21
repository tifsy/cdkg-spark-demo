"""Visit a source's homepage and turn it into evidence for the guidelines.

Backends:
  fixture   bundled snapshots (offline demo)
  requests  plain HTTP + BeautifulSoup (default, works on ARM64 / DGX Spark)
  crawl4ai  open-source headless-browser crawler for JS-heavy sites
            (`pip install crawl4ai && crawl4ai-setup`)

Output is a compact `signals` dict; the LLM sees only this, never raw HTML.
"""
import datetime as dt
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..config import settings
from .fixtures import SNAPSHOTS

UA = "Mozilla/5.0 (X11; Linux aarch64) CDKG-CollectionReviewAgent/0.1 (+research; contact via Media Cloud)"
ABOUT_HINTS = ("about", "who-we-are", "our-team", "staff", "editorial", "masthead", "من-نحن", "contact")
AGG_PHRASES = ("read more at", "via ", "source:", "collected from", "headlines from", "all news in one place",
               "news aggregator", "sponsored")
PR_PHRASES = ("press release", "our products", "request a quote", "investor relations", "shop", "add to cart",
              "careers", "our services")
SATIRE_PHRASES = ("satire", "parody", "made up", "not real", "humour", "humor")

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE_RES = [
    (re.compile(rf"\b({_MONTHS}) (\d{{1,2}}), (20\d\d)\b"), lambda m: dt.datetime.strptime(m.group(0), "%B %d, %Y")),
    (re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b"), lambda m: dt.datetime.strptime(m.group(0), "%Y-%m-%d")),
]


def _latest_date(text: str) -> str | None:
    found = []
    for rx, conv in _DATE_RES:
        for m in rx.finditer(text):
            try:
                d = conv(m).date()
                if d <= dt.date.today():
                    found.append(d)
            except ValueError:
                pass
    return max(found).isoformat() if found else None


def _count(text: str, phrases) -> list[str]:
    low = text.lower()
    return [p.strip() for p in phrases if p in low]


def _signals(url: str, snap: dict) -> dict:
    if not snap.get("status") or snap["status"] >= 400:
        return {"url": url, "reachable": False, "http_status": snap.get("status"),
                "error": snap.get("error") or f"HTTP {snap.get('status')}"}
    text = " ".join(filter(None, [snap.get("title"), snap.get("description"), snap.get("text")]))
    about = snap.get("about") or {}
    full = text + " " + (about.get("text") or "")
    last = _latest_date(text)
    ia, ea = snap.get("internal_article_links", 0), snap.get("external_article_links", 0)
    return {
        "url": url, "reachable": True, "http_status": snap["status"],
        "title": snap.get("title"), "description": snap.get("description"),
        "homepage_excerpt": (snap.get("text") or "")[:700],
        "about_page_found": bool(about), "about_excerpt": (about.get("text") or "")[:500] or None,
        "bylines_found": snap.get("bylines", 0),
        "latest_date_seen": last,
        "days_since_latest": (dt.date.today() - dt.date.fromisoformat(last)).days if last else None,
        "internal_article_links": ia, "external_article_links": ea,
        "external_link_ratio": round(ea / (ia + ea), 2) if (ia + ea) else None,
        "has_rss": snap.get("has_rss"),
        "aggregator_phrases": _count(text, AGG_PHRASES),
        "pr_or_company_phrases": _count(full, PR_PHRASES),
        "satire_phrases": _count(full, SATIRE_PHRASES),
    }


# ---------------------------------------------------------------- live backends
def _parse_html(base_url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    host = urlparse(base_url).netloc.replace("www.", "")
    internal = external = 0
    about_url = None
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        p = urlparse(href)
        if p.scheme not in ("http", "https"):
            continue
        is_article = len(p.path.strip("/").split("/")) >= 2 or re.search(r"\d{4}|-\w+-\w+", p.path)
        if p.netloc.replace("www.", "") == host:
            internal += bool(is_article)
            label = (a.get_text(" ", strip=True) + " " + p.path).lower()
            if not about_url and any(h in label for h in ABOUT_HINTS):
                about_url = href
        elif is_article:
            external += 1
    text = soup.get_text(" ", strip=True)
    desc = soup.find("meta", attrs={"name": "description"})
    return {
        "title": soup.title.get_text(strip=True) if soup.title else None,
        "description": desc.get("content") if desc else None,
        "text": text[:4000],
        "internal_article_links": internal, "external_article_links": external,
        "bylines": len(re.findall(r"\bBy [A-Z][a-z]+|\bبقلم\b|\bauthor\b", html)),
        "has_rss": bool(soup.find("link", attrs={"type": re.compile("rss|atom")})),
        "_about_url": about_url,
    }


def _fetch_requests(url: str) -> dict:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
    except requests.RequestException as e:
        return {"status": None, "error": type(e).__name__ + ": " + str(e)[:200]}
    if r.status_code >= 400:
        return {"status": r.status_code}
    snap = {"status": r.status_code, **_parse_html(r.url, r.text)}
    about_url = snap.pop("_about_url")
    if about_url:
        try:
            ar = requests.get(about_url, headers={"User-Agent": UA}, timeout=15)
            if ar.ok:
                snap["about"] = {"url": about_url, "text": _parse_html(about_url, ar.text)["text"][:1500]}
        except requests.RequestException:
            pass
    return snap


def _fetch_crawl4ai(url: str) -> dict:
    import asyncio

    from crawl4ai import AsyncWebCrawler   # optional dependency

    async def go():
        async with AsyncWebCrawler() as crawler:
            res = await crawler.arun(url=url)
            if not res.success:
                return {"status": res.status_code, "error": res.error_message}
            snap = {"status": res.status_code or 200, **_parse_html(url, res.html)}
            about_url = snap.pop("_about_url")
            if about_url:
                ab = await crawler.arun(url=about_url)
                if ab.success:
                    snap["about"] = {"url": about_url, "text": (ab.markdown or "")[:1500]}
            return snap

    return asyncio.run(go())


def inspect(url: str) -> dict:
    url = url if url.startswith("http") else f"https://{url}"
    if settings.INSPECTOR_MODE == "fixture":
        snap = SNAPSHOTS.get(url) or SNAPSHOTS.get(url.rstrip("/") + "/") or {"status": None,
                                                                              "error": "no fixture snapshot"}
    elif settings.INSPECTOR_BACKEND == "crawl4ai":
        snap = _fetch_crawl4ai(url)
    else:
        snap = _fetch_requests(url)
    return _signals(url, snap)
