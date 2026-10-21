"""Synthetic demo articles (NOT real news).

Shaped exactly like Media Cloud `story_list(expanded=True)` results so the
rest of the pipeline cannot tell the difference. Dates are relative to today
so the "last 14 days" style queries return something.
"""
from datetime import date, timedelta


def _d(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


SAMPLE_STORIES = [
    # ---- Sudan: one conflict/displacement event reported by 3 outlets ----
    dict(id="demo-sd-001", media_name="Demo Nile Tribune", media_url="nile-tribune.example",
         language="en", country="Sudan", publish_date=_d(3),
         title="Shelling hits displacement camp near El Fasher",
         text=("Artillery shelling struck the outskirts of El Fasher in North Darfur on Tuesday, "
               "local monitors said. At least 14 civilians were killed and 30 injured. "
               "Residents said around 6,000 people fled toward Tawila after the attack. "
               "Aid groups said the main clinic serving the camp was damaged.")),
    dict(id="demo-sd-002", media_name="Demo Darfur Monitor", media_url="darfur-monitor.example",
         language="en", country="Sudan", publish_date=_d(3),
         title="Thousands flee El Fasher after artillery attack",
         text=("An artillery attack on El Fasher killed 17 people, according to a local emergency room "
               "network, while more than 7,000 residents were displaced towards Tawila. "
               "Both the army and the RSF accused each other of the shelling.")),
    dict(id="demo-sd-003", media_name="Demo Horn Wire", media_url="horn-wire.example",
         language="ar", country="Sudan", publish_date=_d(2),
         title="قصف مدفعي على الفاشر ونزوح الآلاف",
         text=("قالت مصادر محلية إن قصفاً مدفعياً على مدينة الفاشر في شمال دارفور أدى إلى مقتل 15 مدنياً "
               "ونزوح نحو 6500 شخص باتجاه طويلة.")),
    # ---- Sudan: cholera ----
    dict(id="demo-sd-004", media_name="Demo Nile Tribune", media_url="nile-tribune.example",
         language="en", country="Sudan", publish_date=_d(6),
         title="Cholera cases rise in Kosti as water supply fails",
         text=("Health authorities in White Nile state reported 212 suspected cholera cases and 9 deaths "
               "in Kosti over the past week. Officials linked the outbreak to contaminated drinking water "
               "after the main pumping station stopped working.")),
    dict(id="demo-sd-005", media_name="Demo Sahel Health News", media_url="sahel-health.example",
         language="en", country="Sudan", publish_date=_d(5),
         title="White Nile cholera outbreak strains hospitals",
         text=("Hospitals in Kosti are overwhelmed by acute watery diarrhoea cases. Doctors said more than "
               "230 patients have been admitted and at least 11 have died. Water and sanitation services "
               "remain disrupted.")),
    # ---- Sudan: food insecurity ----
    dict(id="demo-sd-006", media_name="Demo Darfur Monitor", media_url="darfur-monitor.example",
         language="en", country="Sudan", publish_date=_d(10),
         title="Hunger deepens in South Kordofan as markets empty",
         text=("Families in Kadugli, South Kordofan, report eating one meal a day. Food prices have tripled "
               "since roads were cut, and aid workers warn of rising child malnutrition.")),
    # ---- Sudan: protection (sensitive) ----
    dict(id="demo-sd-007", media_name="Demo Horn Wire", media_url="horn-wire.example",
         language="en", country="Sudan", publish_date=_d(8),
         title="Rights groups document abductions of women in Al Jazirah",
         text=("Rights groups say armed men abducted at least 12 women and girls from villages near "
               "Wad Madani in Al Jazirah state last week, and reported cases of sexual violence. "
               "Survivors have limited access to medical care.")),
    # ---- Bangladesh: flood event reported by 2 outlets ----
    dict(id="demo-bd-001", media_name="Demo Delta Daily", media_url="delta-daily.example",
         language="en", country="Bangladesh", publish_date=_d(4),
         title="Flash floods submerge villages in Sunamganj",
         text=("Flash floods triggered by heavy upstream rain inundated large parts of Sunamganj district "
               "in Sylhet division. Officials said about 250,000 people are affected and 18,000 have moved "
               "to shelters. Three people drowned. Many schools have been turned into shelters.")),
    dict(id="demo-bd-002", media_name="Demo Bengal Observer", media_url="bengal-observer.example",
         language="en", country="Bangladesh", publish_date=_d(3),
         title="Sylhet flood: 300,000 stranded, drinking water scarce",
         text=("The flood situation in Sunamganj and Sylhet worsened as rivers crossed danger levels. "
               "Local administration estimates 300,000 people are stranded, and 20,000 are in shelters. "
               "Tube wells are submerged and safe drinking water is scarce.")),
    # ---- Bangladesh: Cox's Bazar camp fire / displacement ----
    dict(id="demo-bd-003", media_name="Demo Delta Daily", media_url="delta-daily.example",
         language="en", country="Bangladesh", publish_date=_d(12),
         title="Fire in Ukhia camp leaves thousands without shelter",
         text=("A fire swept through a Rohingya refugee camp in Ukhia, Cox's Bazar, destroying about 800 "
               "shelters. Camp officials said around 4,000 refugees were left homeless. No deaths were "
               "reported.")),
    # ---- Bangladesh: dengue ----
    dict(id="demo-bd-004", media_name="Demo Bengal Observer", media_url="bengal-observer.example",
         language="en", country="Bangladesh", publish_date=_d(1),
         title="Dengue admissions climb in Dhaka hospitals",
         text=("The health directorate reported 1,140 new dengue hospitalisations in the past 24 hours, "
               "most of them in Dhaka. Five deaths were recorded.")),
    # ---- irrelevant: should be dropped by the stage-1 filter ----
    dict(id="demo-bd-005", media_name="Demo Delta Daily", media_url="delta-daily.example",
         language="en", country="Bangladesh", publish_date=_d(2),
         title="National cricket team wins series opener",
         text="The national side won the opening match of the series by six wickets in Chattogram."),
    dict(id="demo-sd-008", media_name="Demo Nile Tribune", media_url="nile-tribune.example",
         language="en", country="Sudan", publish_date=_d(4),
         title="Port Sudan hosts trade fair for local artisans",
         text="Hundreds of visitors attended a craft and trade fair in Port Sudan this weekend."),
]
