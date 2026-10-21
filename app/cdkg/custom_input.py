"""Demo inputs for when Media Cloud full text is not available.

Two ways to feed the pipeline:

1. Your own texts (paste in the UI, upload, or `python -m app.cli ingest-file`).
   Accepted formats:
     .txt    articles separated by a line containing only `---` (or by blank lines).
             If an article's first line is short, it is used as the title.
     .jsonl  one object per line: {"text": ..., "title"?, "outlet"?, "date"?, "country"?, "language"?, "url"?}
     .json   a list of such objects
     .csv    columns: text (required), title, outlet, date, country, language, url

2. Random generated articles: realistic-looking, template-based fake news built
   from the ontology and gazetteer. Each fake event is "reported" by 1-3 fake
   outlets with slightly different numbers, plus some irrelevant articles, so
   filtering, extraction and clustering all have something to do.
   Each generated story carries a hidden `true_event_id` (null for irrelevant
   stories). It is written to the raw JSONL only, never to the articles table,
   so `python -m app.cli score` can grade clustering without the pipeline seeing it.

Everything produced here is shaped like a Media Cloud story, so the rest of the
pipeline is unchanged when real data arrives.
"""
import csv
import datetime as dt
import hashlib
import io
import json
import random
import re

from .ontology import GAZETTEER

ARABIC = re.compile(r"[\u0600-\u06FF]")


def _guess_lang(text: str) -> str:
    return "ar" if len(ARABIC.findall(text)) > len(text) * 0.2 else "en"


def _story(text: str, title: str | None = None, outlet: str | None = None, date: str | None = None,
           country: str | None = None, language: str | None = None, url: str | None = None) -> dict:
    text = (text or "").strip()
    if not title:
        first = text.split(". ")[0]
        title = first if len(first) <= 120 else first[:117] + "..."
    sid = "txt-" + hashlib.sha1(f"{outlet}|{date}|{title}|{text}".encode()).hexdigest()[:12]
    try:
        date = dt.date.fromisoformat(str(date)[:10]).isoformat() if date else dt.date.today().isoformat()
    except ValueError:
        date = dt.date.today().isoformat()
    outlet = outlet or "Demo input"
    return {"id": sid, "title": title, "text": text, "media_name": outlet,
            "media_url": re.sub(r"[^a-z0-9]+", "-", outlet.lower()).strip("-") + ".example",
            "url": url or f"https://demo.example/{sid}", "language": language or _guess_lang(text),
            "publish_date": date, "country": country}


def parse_blob(blob: str, filename: str = "", default_country: str | None = None) -> list[dict]:
    """Turn pasted text or an uploaded file's content into story dicts."""
    name = (filename or "").lower()
    blob = blob.lstrip("\ufeff")
    records: list[dict] = []
    if name.endswith(".jsonl"):
        records = [json.loads(l) for l in blob.splitlines() if l.strip()]
    elif name.endswith(".json"):
        data = json.loads(blob)
        records = data if isinstance(data, list) else [data]
    elif name.endswith(".csv"):
        records = list(csv.DictReader(io.StringIO(blob)))
    else:
        parts = re.split(r"^\s*---\s*$", blob, flags=re.M)
        if len(parts) == 1:
            parts = re.split(r"\n\s*\n", blob)
        for p in parts:
            lines = [l.strip() for l in p.strip().splitlines() if l.strip()]
            if not lines:
                continue
            if len(lines) > 1 and len(lines[0]) <= 120:
                records.append({"title": lines[0], "text": " ".join(lines[1:])})
            else:
                records.append({"text": " ".join(lines)})
    out = []
    for r in records:
        r = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k}
        if not r.get("text"):
            continue
        out.append(_story(r["text"], r.get("title"), r.get("outlet") or r.get("media_name"),
                          r.get("date") or r.get("publish_date"), r.get("country") or default_country,
                          r.get("language"), r.get("url")))
    return out


# ------------------------------------------------------------------ random generator
OUTLETS = {
    "Sudan": ["Demo Nile Tribune", "Demo Darfur Monitor", "Demo Horn Wire", "Demo Khartoum Post"],
    "Bangladesh": ["Demo Delta Daily", "Demo Bengal Observer", "Demo Padma Times", "Demo Coastal Herald"],
}
ACTORS = ["an armed group", "government forces", "a local militia", "unidentified gunmen"]

TEMPLATES = {
    "armed_conflict": [
        ("Fighting reported in {a2}", "Clashes between {actor} and rival fighters broke out in {a2}, {a1}. "
         "At least {killed} people were killed and {injured} injured, local sources said."),
        ("Shelling hits {a2}", "Artillery shelling struck residential areas of {a2} in {a1}. "
         "Medics said {killed} civilians were killed and {injured} were wounded."),
    ],
    "displacement": [
        ("Thousands flee {a2}", "Around {displaced} people fled {a2}, {a1}, after renewed insecurity. "
         "Many are staying in schools and makeshift camps."),
        ("New arrivals strain camps near {a2}", "Aid workers say {displaced} people were displaced to "
         "camps around {a2} in {a1} this week, with shelter in short supply."),
    ],
    "natural_hazard": [
        ("Floods inundate {a2}", "Heavy rain caused flash floods across {a2} in {a1}. Officials said "
         "{affected} people are affected and {displaced} moved to shelters. {killed} people drowned."),
        ("Storm damages homes in {a2}", "A cyclone hit {a2}, {a1}, damaging homes. About {affected} people "
         "are affected and {displaced} have moved to shelters."),
    ],
    "epidemic": [
        ("Cholera outbreak spreads in {a2}", "Health officials in {a1} reported {affected} suspected cholera "
         "cases and {killed} deaths in {a2}, linked to contaminated drinking water."),
        ("Dengue cases rise in {a2}", "Hospitals in {a2} admitted {affected} dengue patients this week; "
         "{killed} people have died, according to the health directorate."),
    ],
    "food_insecurity": [
        ("Hunger warnings for {a2}", "Families in {a2}, {a1}, report skipping meals as food prices soar. "
         "Aid agencies warn malnutrition among children is rising."),
    ],
    "protection_incident": [
        ("Abductions reported near {a2}", "Rights groups said {actor} abducted {affected} women and girls "
         "near {a2} in {a1}. Survivors have limited access to care."),
    ],
}
IRRELEVANT = [
    ("Local team wins regional football cup", "The home side won the final 2-1 in front of a large crowd."),
    ("Trade fair opens in the capital", "Hundreds of exhibitors gathered for the annual trade fair."),
    ("New bridge design unveiled", "Engineers presented plans for a new road bridge to city officials."),
    ("Film festival announces line-up", "Organisers announced twenty films for this year's festival."),
]


def _jitter(n: int, rng: random.Random) -> int:
    return max(1, int(n * rng.uniform(0.85, 1.15)))


def generate_random(n: int = 60, countries: list[str] | None = None, days: int = 30,
                    seed: int | None = None, irrelevant_share: float = 0.2) -> list[dict]:
    """Generate ~n fake articles. Same seed -> same articles."""
    rng = random.Random(seed)
    countries = [c for c in (countries or list(GAZETTEER)) if c in GAZETTEER] or list(GAZETTEER)
    today = dt.date.today()
    stories: list[dict] = []
    n_events = 0
    while len(stories) < n:
        country = rng.choice(countries)
        if rng.random() < irrelevant_share:
            title, text = rng.choice(IRRELEVANT)
            stories.append(_story(text, title, rng.choice(OUTLETS[country]),
                                  (today - dt.timedelta(days=rng.randint(0, days))).isoformat(), country, "en")
                           | {"true_event_id": None})
            continue
        n_events += 1
        etype = rng.choice(list(TEMPLATES))
        a1 = rng.choice(list(GAZETTEER[country]))
        a2 = rng.choice(GAZETTEER[country][a1])
        base = {"killed": rng.randint(2, 40), "injured": rng.randint(5, 80),
                "displaced": rng.choice([800, 2500, 6000, 15000, 40000]),
                "affected": rng.choice([150, 600, 3000, 25000, 120000])}
        actor = rng.choice(ACTORS)
        event_day = today - dt.timedelta(days=rng.randint(0, days))
        n_reports = rng.choices([1, 2, 3], weights=[0.45, 0.35, 0.2])[0]
        for outlet in rng.sample(OUTLETS[country], n_reports):
            title, body = rng.choice(TEMPLATES[etype])
            nums = {k: f"{_jitter(v, rng):,}" for k, v in base.items()}
            report_day = event_day + dt.timedelta(days=rng.randint(0, 1))
            stories.append(_story(body.format(a1=a1, a2=a2, actor=actor, **nums), title.format(a2=a2),
                                  outlet, min(report_day, today).isoformat(), country, "en")
                           | {"true_event_id": f"gen-{n_events}"})
    return stories[:n]
