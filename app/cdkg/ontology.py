"""CDKG Minimum Viable Ontology (v1) as used by the demo.

Mirrors proposal §3.6 (6 event types, 6 sectors, basic impact signals) and
§3.7 (event schema). The real ontology will be an OWL file; here it is plain
Python so the extraction prompt and validator share one definition.
"""

ONTOLOGY_VERSION = "mvo-0.1-demo"

EVENT_TYPES = {
    "armed_conflict": {
        "label": "Armed conflict and political violence",
        "keywords": ["clash", "attack", "shelling", "airstrike", "drone strike", "militia", "fighting",
                     "rsf", "armed group", "gunmen", "killed in", "bombardment", "offensive", "ambush",
                     "قصف", "اشتباكات", "هجوم"],
    },
    "natural_hazard": {
        "label": "Natural hazard (flood, earthquake, cyclone, drought, wildfire, landslide)",
        "keywords": ["flood", "flash flood", "cyclone", "earthquake", "drought", "landslide", "wildfire",
                     "storm surge", "heavy rain", "monsoon", "inundat", "embankment"],
    },
    "displacement": {
        "label": "Displacement and population movement",
        "keywords": ["displaced", "displacement", "fled", "flee", "idp", "refugee", "evacuat", "shelter",
                     "camp", "returnees", "uprooted", "homeless",
                     "نزوح", "نازح", "لاجئ"],
    },
    "epidemic": {
        "label": "Epidemic and health emergency",
        "keywords": ["cholera", "outbreak", "dengue", "measles", "epidemic", "suspected cases",
                     "acute watery diarrhoea", "awd", "malaria", "case fatality",
                     "كوليرا", "وباء"],
    },
    "food_insecurity": {
        "label": "Food insecurity and famine signals",
        "keywords": ["famine", "hunger", "malnutrition", "ipc phase", "food insecurity", "starvation",
                     "food prices", "crop failure", "ration"],
    },
    "protection_incident": {
        "label": "Protection incident (GBV, child protection, civilian targeting)",
        "keywords": ["sexual violence", "gender-based violence", "gbv", "rape", "child recruitment",
                     "abduct", "civilians targeted", "trafficking", "unaccompanied children"],
    },
}

SECTORS = ["protection", "health", "emergency_shelter", "food_security", "wash", "education"]

SECTOR_KEYWORDS = {
    "health": ["hospital", "clinic", "health facilit", "cholera", "medical", "patients", "dengue"],
    "wash": ["water", "sanitation", "latrine", "drinking water", "hygiene", "wells"],
    "emergency_shelter": ["shelter", "homes destroyed", "houses", "tents", "camp", "displaced"],
    "food_security": ["food", "famine", "hunger", "crops", "market", "malnutrition", "ration"],
    "education": ["school", "students", "classroom", "teachers", "education"],
    "protection": ["civilians", "sexual violence", "children", "abduct", "protection", "gbv"],
}

# Event types where precise location can put people at risk (proposal §5.10).
SENSITIVE_TYPES = {"protection_incident"}

# Demo gazetteer for two candidate reference countries.
# Real pipeline: GADM / HDX COD-AB boundaries.
GAZETTEER = {
    "Sudan": {
        "Khartoum": ["Khartoum", "Omdurman", "Khartoum North", "Bahri"],
        "North Darfur": ["El Fasher", "Kutum", "Mellit", "Tawila"],
        "South Darfur": ["Nyala", "Kas"],
        "West Darfur": ["El Geneina", "Kereneik"],
        "Central Darfur": ["Zalingei"],
        "Al Jazirah": ["Wad Madani", "Hasahisa"],
        "North Kordofan": ["El Obeid", "Bara"],
        "South Kordofan": ["Kadugli", "Dilling"],
        "Blue Nile": ["Ed Damazin"],
        "White Nile": ["Kosti", "Rabak"],
        "Kassala": ["Kassala"],
        "Gedaref": ["Gedaref"],
        "Red Sea": ["Port Sudan"],
        "River Nile": ["Atbara", "Shendi"],
        "Sennar": ["Sennar", "Singa"],
    },
    "Bangladesh": {
        "Chattogram": ["Cox's Bazar", "Chattogram", "Feni", "Teknaf", "Ukhia", "Noakhali"],
        "Sylhet": ["Sylhet", "Sunamganj", "Moulvibazar", "Habiganj"],
        "Dhaka": ["Dhaka", "Gazipur", "Narayanganj"],
        "Khulna": ["Khulna", "Satkhira", "Bagerhat"],
        "Barishal": ["Barishal", "Bhola", "Patuakhali"],
        "Rangpur": ["Rangpur", "Kurigram", "Gaibandha", "Lalmonirhat"],
        "Rajshahi": ["Rajshahi", "Sirajganj", "Bogura"],
        "Mymensingh": ["Mymensingh", "Netrokona"],
    },
}


# Non-Latin aliases -> gazetteer names (real pipeline: COD-AB alt names)
ALIASES = {"الفاشر": "El Fasher", "شمال دارفور": "North Darfur", "طويلة": "Tawila",
           "الخرطوم": "Khartoum", "كوستي": "Kosti"}


def geocode(country: str | None, *names: str | None) -> dict:
    """Resolve within `country` first; if nothing matches, try the other gazetteer countries."""
    hit = _geocode(country, *names)
    if hit["admin_level"] == 0 and country in GAZETTEER:
        other = _geocode(None, *names)
        if other["admin_level"] > 0:
            other["geo_confidence"] = round(other["geo_confidence"] - 0.15, 2)   # country hint disagreed
            return other
    return hit


def _geocode(country: str | None, *names: str | None) -> dict:
    """Resolve free-text place names against the gazetteer.

    Returns admin1/admin2/admin_level/geo_confidence. Admin2 match beats admin1.
    """
    best = {"admin1": None, "admin2": None, "admin_level": 0, "geo_confidence": 0.3 if country else 0.0}
    countries = [country] if country in GAZETTEER else list(GAZETTEER)
    hay = " ".join(n for n in names if n)
    for alias, name in ALIASES.items():
        hay = hay.replace(alias, name)
    hay = hay.lower()
    if not hay:
        return best
    admin1_names = {a1.lower() for c in GAZETTEER.values() for a1 in c}
    hits = []   # (is_also_admin1_name, position, country, admin1, admin2)
    for c in countries:
        for a1, a2s in GAZETTEER[c].items():
            for a2 in a2s:
                pos = hay.find(a2.lower())
                if pos >= 0:
                    hits.append((a2.lower() in admin1_names, pos, c, a1, a2))
            if a1.lower() in hay and best["admin_level"] < 1:
                best = {"country": c, "admin1": a1, "admin2": None, "admin_level": 1, "geo_confidence": 0.7}
    if hits:   # prefer unambiguous district names, then the first one mentioned
        _, _, c, a1, a2 = sorted(hits)[0]
        return {"country": c, "admin1": a1, "admin2": a2, "admin_level": 2, "geo_confidence": 0.85}
    return best


def schema_for_prompt() -> str:
    types = "\n".join(f'  - "{k}": {v["label"]}' for k, v in EVENT_TYPES.items())
    return f"""Allowed event_type values:
{types}
Allowed sector values: {", ".join(SECTORS)}

Return JSON: {{"events": [ {{
  "event_type": one of the allowed values,
  "sector": one of the allowed sectors,
  "event_start": "YYYY-MM-DD" or null (when the event happened, NOT the report date),
  "event_end": "YYYY-MM-DD" or null,
  "country": country name,
  "location_text": most specific place named in the article,
  "admin1": first-level admin unit (state / division) or null,
  "admin2": second-level unit (locality / district) or null,
  "population_group": e.g. "IDPs", "children", "civilians", or null,
  "killed": integer or null, "injured": integer or null,
  "displaced": integer or null, "affected": integer or null,
  "actors": list of party/organisation categories as reported (never individual people's names),
  "summary": one neutral sentence in English written in your own words,
  "confidence": number 0-1 that this event is real and correctly typed
}} ]}}"""
