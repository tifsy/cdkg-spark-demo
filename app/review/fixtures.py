"""Offline demo data for Task 2 (fictional .example sites).

MOCK_QUEUE mimics GET /api/review-queues/<guid>/items from
mediacloud/collection-review-tool. SNAPSHOTS mimic what the site inspector
would see when it visits each homepage, so the demo runs without internet.
"""
import datetime as dt

_today = dt.date.today()
_d = lambda n: (_today - dt.timedelta(days=n)).strftime("%B %d, %Y")

MOCK_QUEUE_GUID = "demo-queue-sudan-national"

MOCK_QUEUE = [
    {"id": 101, "source_id": 900101, "source_label": "nile-tribune.example", "source_homepage": "https://nile-tribune.example/",
     "source_metadata": {"pub_country": "SDN", "primary_language": "en", "media_type": "news"}},
    {"id": 102, "source_id": 900102, "source_label": "sudan-newshub.example", "source_homepage": "https://sudan-newshub.example/",
     "source_metadata": {"pub_country": "SDN", "primary_language": "en"}},
    {"id": 103, "source_id": 900103, "source_label": "acme-cement.example", "source_homepage": "https://acme-cement.example/",
     "source_metadata": {"pub_country": "SDN"}},
    {"id": 104, "source_id": 900104, "source_label": "darfur-voices.example", "source_homepage": "https://darfur-voices.example/",
     "source_metadata": {"primary_language": "ar"}},
    {"id": 105, "source_id": 900105, "source_label": "khartoum-evening.example", "source_homepage": "https://khartoum-evening.example/",
     "source_metadata": {"pub_country": "SDN", "primary_language": "ar"}},
    {"id": 106, "source_id": 900106, "source_label": "horn-wire.example", "source_homepage": "https://horn-wire.example/",
     "source_metadata": {"primary_language": "en"}},
    {"id": 107, "source_id": 900107, "source_label": "the-daily-camel.example", "source_homepage": "https://the-daily-camel.example/",
     "source_metadata": {}},
    {"id": 108, "source_id": 900108, "source_label": "radio-kassala.example", "source_homepage": "https://radio-kassala.example/",
     "source_metadata": {"pub_country": "SDN", "primary_language": "ar"}},
]

SNAPSHOTS = {
    "https://nile-tribune.example/": {
        "status": 200, "title": "Nile Tribune | Independent news from Sudan",
        "description": "Daily reporting from Khartoum, Darfur and the regions by our own correspondents.",
        "text": (f"Shelling hits displacement camp near El Fasher. By our Darfur correspondent. {_d(1)}. "
                 f"Cholera cases rise in Kosti. Reporting by health desk staff. {_d(2)}. "
                 "Opinion | Editorials | Investigations | Contact the newsroom"),
        "internal_article_links": 46, "external_article_links": 3,
        "about": {"url": "https://nile-tribune.example/about",
                  "text": "Founded in 2009. Editor-in-chief, managing editor and a team of 22 journalists in 6 states. "
                          "Member of the regional press council. Editorial policy and corrections."},
        "bylines": 9, "has_rss": True,
    },
    "https://sudan-newshub.example/": {
        "status": 200, "title": "Sudan NewsHub - All Sudan news in one place",
        "description": "Top Sudan headlines collected from around the web, updated every 5 minutes.",
        "text": (f"Read more at aljazeera.example • via bbc.example • Source: reuters.example • {_d(0)} "
                 "Trending now • Sponsored • Headlines from 120 sites"),
        "internal_article_links": 4, "external_article_links": 61,
        "about": None, "bylines": 0, "has_rss": True,
    },
    "https://acme-cement.example/": {
        "status": 200, "title": "Acme Cement Sudan - Building the nation",
        "description": "Leading producer of cement and construction materials.",
        "text": (f"Press release: Acme opens new plant in River Nile state ({_d(20)}). Our products. "
                 "Request a quote. Careers. Investor relations. Shop bulk orders."),
        "internal_article_links": 6, "external_article_links": 0,
        "about": {"url": "https://acme-cement.example/about-us",
                  "text": "Acme Cement is a manufacturing company founded in 1998 with 1,200 employees."},
        "bylines": 0, "has_rss": False,
    },
    "https://darfur-voices.example/": {
        "status": 200, "title": "Darfur Voices – a personal blog",
        "description": "Thoughts and photos from Nyala.",
        "text": (f"My reflections on the market this week ({_d(40)}). A poem for my grandmother ({_d(95)}). "
                 "Comments (3)"),
        "internal_article_links": 8, "external_article_links": 2,
        "about": {"url": "https://darfur-voices.example/about", "text": "I am a teacher who writes in my free time."},
        "bylines": 1, "has_rss": True,
    },
    "https://khartoum-evening.example/": {
        "status": None, "error": "DNS resolution failed (NXDOMAIN)",
    },
    "https://horn-wire.example/": {
        "status": 200, "title": "Horn Wire",
        "description": "News agency covering Sudan and the Horn of Africa.",
        "text": (f"Rights groups document abductions in Al Jazirah. By staff reporter. {_d(4)}. "
                 f"Artillery attack on El Fasher. Horn Wire correspondents. {_d(2)}."),
        "internal_article_links": 31, "external_article_links": 5,
        "about": None, "bylines": 6, "has_rss": True,
    },
    "https://the-daily-camel.example/": {
        "status": 200, "title": "The Daily Camel – Sudan's least reliable news",
        "description": "Satire. Everything here is made up.",
        "text": (f"Camel elected mayor of Omdurman, promises more shade ({_d(3)}). "
                 "This website is satire and parody."),
        "internal_article_links": 22, "external_article_links": 1,
        "about": {"url": "https://the-daily-camel.example/about",
                  "text": "A humour and satire site. None of our stories are real."},
        "bylines": 3, "has_rss": True,
    },
    "https://radio-kassala.example/": {
        "status": 200, "title": "Radio Kassala 98.4 FM",
        "description": "Listen live. Programmes in Arabic and Beja.",
        "text": f"Listen live ▶ Programme schedule. Morning show podcast ({_d(55)}). Weather. Contact the studio.",
        "internal_article_links": 5, "external_article_links": 1,
        "about": {"url": "https://radio-kassala.example/about",
                  "text": "Community radio station established in 2015 with a small news team."},
        "bylines": 0, "has_rss": False,
    },
}
