import re


THEME_RULES = {
    "sports": [
        r"\bbun[\s-]", r"\bpre[\s-]", r"\bser[\s-]", r"\blal[\s-]", r"\blig[\s-]",
        r"\buel[\s-]", r"\becl[\s-]", r"\btennis", r"\bracing[\s-]",
        r"\bwin\s+on\s+\d{4}", r"\bfc[\s-]", r"\bac[\s-]+milan",
        r"\breal[\s-]+(madrid|betis|sociedad|valladolid)",
        r"\bbayern", r"\bdortmund", r"\bleipzig", r"\bstuttgart",
        r"\bliverpool", r"\bmanchester", r"\bchelsea", r"\bArsenal",
        r"\btottenham", r"\bnewcastle",
        r"\binternazionale", r"\bjuventus",
        r"\bnapoli", r"\batalanta", r"\broma", r"\blazio", r"\btorino",
        r"\blecce", r"\bsassuolo", r"\bpisa", r"\bcomo[\s-]",
        r"\bcagliari", r"\bempoli", r"\bfiorentina", r"\bvenezia",
        r"\bvillarreal", r"\batletico[\s-]+madrid", r"\bbarcelona",
        r"\bvalencia", r"\bsevilla", r"\bathletic[\s-]+club",
        r"\bgetafe", r"\bgirona", r"\brayo[\s-]+vallecano",
        r"\bcrystal[\s-]+palace", r"\bwest[\s-]+ham",
        r"\bwolverhampton", r"\bnottingham", r"\bbrentford",
        r"\bbournemouth", r"\bfulham", r"\brighton",
        r"\bmonaco", r"\bpsg", r"\bmarseille", r"\blyon",
        r"\blille", r"\brennes", r"\bnice", r"\blens",
        r"\bmadrid[\s-]+open",
        r"\bgrand[\s-]*slam", r"\batp[\s-]", r"\bwta[\s-]",
        r"\bformula[\s-]*1", r"\bf1[\s-]",
        r"\bsuper[\s-]*bowl", r"\bworld[\s-]*series",
        r"\bnba[\s-]", r"\bnfl[\s-]", r"\bmlb[\s-]", r"\bnhl[\s-]",
        r"\bwnba[\s-]", r"\bmls[\s-]",
        r"\bulster[\s-]", r"\bboston", r"\bnew[\s-]+york",
        r"\blos[\s-]+angeles", r"\bgolden[\s-]+state",
        r"\bmiami[\s-]", r"\bdallas[\s-]",
    ],
    "politics": [
        r"\belection[\s-]", r"\bpresident[\s-]",
        r"\bcongress[\s-]", r"\bsenate[\s-]", r"\bgovernor[\s-]",
        r"\bmayor[\s-]", r"\bprimary[\s-]", r"\bcaucus[\s-]",
        r"\bdebate[\s-]", r"\bpoll[\s-]",
        r"\bgop[\s-]", r"\bdemocrat[\s-]", r"\brepublican[\s-]",
        r"\bmidterm[\s-]", r"\bcabinet[\s-]",
        r"\bsupreme[\s-]*court", r"\bimpeachment[\s-]",
        r"\bfilibuster[\s-]", r"\babortion[\s-]",
        r"\bimmigration[\s-]", r"\bgun[\s-]*control",
        r"\bclimate[\s-]*bill",
        r"\btrump[\s-]", r"\bbiden[\s-]",
        r"\bharris[\s-]", r"\bvance[\s-]",
        r"\bnewsom[\s-]", r"\bdesantis[\s-]",
        r"\brally[\s-]",
    ],
    "crypto": [
        r"\bbitcoin[\s-]", r"\bethereum[\s-]",
        r"\bbtc[\s-]", r"\beth[\s-]",
        r"\bcrypto[\s-]", r"\bsolana[\s-]",
        r"\bsol[\s-]", r"\bmatic[\s-]",
        r"\bdefi[\s-]", r"\bweb3[\s-]",
        r"\btoken[\s-]", r"\bcoin[\s-]",
        r"\bhalving[\s-]", r"\bmining[\s-]",
        r"\bblockchain[\s-]", r"\bbinance[\s-]",
        r"\bcoinbase[\s-]", r"\bsec[\s-]",
        r"\betf[\s-]", r"\bprice[\s-]*target",
        r"\bprice[\s-]*prediction",
        r"\bgas[\s-]*fee", r"\bgas[\s-]*price",
        r"\blayer[\s-]*2",
    ],
}


def categorize(event_slug: str, event_title: str = "") -> str:
    text = f"{event_slug or ''} {event_title or ''}".lower().replace("_", "-").replace(" ", "-")

    for theme, patterns in THEME_RULES.items():
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                return theme

    return "general"
