"""
Spam / bad-neighbourhood keyword rules.

Two matching modes:
  * URL match     - substring, on the lower-cased full URL. Cheap and safe:
                    "casino" in a URL is essentially never innocent.
  * Content match - WORD-BOUNDARY regex on visible page text, so "sex" does
                    not match "Essex" and "bet" does not match "better".
                    Content needs a THRESHOLD of hits before it counts, because
                    a real article can legitimately mention any single term.

Edit the lists below to fit your niche.
"""

import re

ADULT = [
    "porn", "xxx", "escort", "camgirl", "hentai", "milf", "nsfw",
    "nude", "boobs", "fetish", "onlyfans", "erotic", "bdsm", "brazzers",
    "pornhub", "xvideos", "xnxx", "redtube", "youporn", "chaturbate",
    "stripchat", "callgirl", "call-girl", "sexcam", "adultwork",
    # Non-English adult spam, weighted to the languages that dominate SEO spam
    "bokep", "telanjang", "seks", "ngentot",          # Indonesian/Malay
    "khieu dam", "phim sex",                          # Vietnamese
    "porno", "pornographie", "sexo", "putas",         # ES/PT/FR
    "seksi", "erotik", "yetiskin",                    # Turkish
    "\u043f\u043e\u0440\u043d\u043e", "\u0441\u0435\u043a\u0441",   # Russian porno / seks
]

GAMBLING = [
    "casino", "betting", "gambling", "poker", "roulette", "baccarat",
    "sportsbook", "bookmaker", "jackpot", "bet365", "satta", "sattaking",
    "togel", "judi", "bandarq", "dominoqq", "pkv", "gacor", "slot88",
    "1xbet", "melbet", "parimatch", "teenpatti", "rummy", "lottery",
    "toto", "wagering",
    # Indonesian slot/gambling spam - by far the largest single vertical
    "gacor", "maxwin", "situs slot", "judi bola", "bandar", "deposit pulsa",
    "link alternatif", "agen bola", "sbobet", "rtp slot", "mahjong ways",
    "gates of olympus", "starlight princess", "scatter hitam", "pragmatic play",
    "slot online", "slot demo", "bonus new member",
    # other languages
    "apostas", "cassino", "aposta esportiva", "jogo do bicho",   # PT-BR
    "apuestas", "casino online", "tragaperras", "ruleta",        # ES
    "bahis", "casino siteleri", "deneme bonusu", "guvenilir bahis",  # TR
    "kazino", "stavki na sport", "bukmeker",                     # RU (latin)
    "\u043a\u0430\u0437\u0438\u043d\u043e", "\u0431\u0443\u043a\u043c\u0435\u043a\u0435\u0440",  # RU casino / bookmaker
    "nha cai", "ca cuoc", "danh bac", "xo so", "keo nha cai",    # VI
    "ufabet", "pgslot", "baccarat online",                       # TH
    "\u0e2a\u0e25\u0e47\u0e2d\u0e15", "\u0e1a\u0e32\u0e04\u0e32\u0e23\u0e48\u0e32",   # TH slot / baccarat
    "\uc628\ub77c\uc778\uce74\uc9c0\ub178", "\ud1a0\ud1a0\uc0ac\uc774\ud2b8",   # KO online casino / toto site
    "\u30aa\u30f3\u30e9\u30a4\u30f3\u30ab\u30b8\u30ce",   # JA online casino
    "\u535a\u5f69", "\u8d4c\u573a", "\u767e\u5bb6\u4e50",  # ZH gambling / casino / baccarat
]

PHARMA = [
    "viagra", "cialis", "levitra", "tramadol", "xanax", "adderall",
    "phentermine", "oxycontin", "hydrocodone", "kamagra", "modafinil",
    "steroids", "anabolic", "no-prescription", "noprescription",
    "onlinepharmacy", "online-pharmacy", "buypills", "buy-pills",
    "farmacia online", "apotheke online", "pharmacie en ligne",
    "obat kuat", "jual obat",                          # Indonesian
    "\u0430\u043f\u0442\u0435\u043a\u0430 \u043e\u043d\u043b\u0430\u0439\u043d",   # RU online pharmacy
]

FINANCIAL_SCAM = [
    "binaryoption", "binary-option", "forexsignal", "forex-signal",
    "double-your", "getrich", "get-rich", "hyip", "ponzi", "1000x",
    "profit-guarantee", "guaranteed-profit", "trading-bot", "tradingbot",
    "airdrop", "pumpanddump", "payday", "paydayloan", "payday-loan",
    "loan-fast", "fastloan", "badcreditloan", "cashadvance",
]

BLACKHAT_SEO = [
    "buybacklinks", "buy-backlinks", "backlink-package", "pbn-links",
    "link-farm", "linkfarm", "guestpost-cheap", "cheap-guest-post",
    "seo-backlinks", "buy-seo", "doorway", "cloaking",
    "write-my-essay", "essay-writing-service", "assignment-help-cheap",
    "paper-writing-service", "dissertation-for-sale",
]

PIRACY = [
    "warez", "keygen", "cracked", "nulled", "torrent", "free-download-full",
    "activator", "serialkey", "serial-key", "patch-download", "repack",
    "movierulz", "filmyzilla", "123movies", "putlocker", "fmovies",
    "tamilrockers", "openload", "streamsb",
    "nonton film", "streaming gratis", "indoxxi", "layarkaca21", "bioskop online",
    "lk21", "rebahin", "dutafilm",                     # Indonesian piracy
    "pelisplus", "cuevana", "descargar gratis",        # ES
    "assistir online", "baixar filme",                 # PT
    "\u0441\u043a\u0430\u0447\u0430\u0442\u044c \u0431\u0435\u0441\u043f\u043b\u0430\u0442\u043d\u043e",   # RU download free
]

COUNTERFEIT = [
    "replica", "fakerolex", "fake-rolex", "counterfeit", "knockoff",
    "replicawatch", "replica-watch", "replicabag", "aaa-replica",
]

CATEGORIES = {
    "adult / 18+": ADULT,
    "gambling / betting": GAMBLING,
    "pharma / pills": PHARMA,
    "financial scam / payday": FINANCIAL_SCAM,
    "blackhat SEO / essay mills": BLACKHAT_SEO,
    "piracy / warez": PIRACY,
    "counterfeit goods": COUNTERFEIT,
}

# ---------------------------------------------------------------------------
# Unambiguous terms: ONE hit is enough.
#
# The threshold system exists because a real article can legitimately mention
# "casino" or "poker" -- Wikipedia's article on gambling is not spam. But some
# terms carry no innocent reading at all. "situs slot gacor" is not a phrase
# that appears in editorial writing; neither is "deneme bonusu", a brand like
# "1xbet", or a pirate-streaming domain name. Holding those to a 4-hit
# threshold just means a short spam page with a spam title slips through.
#
# Authority domains are still protected: scoring downgrades a tier A/B page
# that trips this rather than calling it TOXIC, so a news article ABOUT
# 1xbet is treated as reporting, not as spam.
# ---------------------------------------------------------------------------
UNAMBIGUOUS = {
    # Indonesian slot/gambling ecosystem
    "situs slot", "gacor", "maxwin", "deposit pulsa", "link alternatif",
    "scatter hitam", "bonus new member", "rtp slot", "judi bola", "agen bola",
    "sbobet", "mahjong ways", "starlight princess", "gates of olympus",
    "slot88", "bandarq", "dominoqq", "pkv", "togel", "judi",
    # gambling brands and locale-specific phrases
    "1xbet", "melbet", "parimatch", "sattaking", "satta",
    "deneme bonusu", "casino siteleri", "guvenilir bahis",
    "kazino", "bukmeker", "nha cai", "keo nha cai", "ufabet", "pgslot",
    "казино", "букмекер",
    "สล็อต", "บาคาร่า",
    "온라인카지노", "토토사이트",
    "オンラインカジノ",
    "博彩", "赌场",
    # adult
    "bokep", "ngentot", "telanjang", "pornhub", "xvideos", "xnxx",
    "brazzers", "chaturbate", "stripchat", "onlyfans", "redtube", "youporn",
    "порно",
    # pharma
    "viagra", "cialis", "kamagra", "tramadol", "xanax", "levitra",
    "obat kuat", "no-prescription", "onlinepharmacy",
    # piracy
    "indoxxi", "layarkaca21", "lk21", "rebahin", "dutafilm", "tamilrockers",
    "filmyzilla", "movierulz", "123movies", "putlocker", "fmovies",
    # counterfeit brands only. Deliberately NOT here: "buybacklinks",
    # "link-farm", "pbn-links", "write-my-essay". Those read as spam but an
    # SEO article warning people off them uses exactly the same words, so a
    # single mention must not condemn a page -- they stay on the normal
    # threshold. Everything above is a term with no innocent reading.
    "fakerolex", "aaa-replica",
}

# Content thresholds: how much evidence before we call a PAGE spammy.
CONTENT_TOTAL_THRESHOLD = 4      # total hits across all categories
CONTENT_CATEGORY_THRESHOLD = 3   # hits inside a single category

# Markers of paid / solicited links. Not toxic, but they tell you the link
# was bought or requested, which is what Google's link-spam policy targets.
PAID_LINK_MARKERS = [
    "write for us", "write for our", "guest post", "guest posting",
    "guest author", "sponsored post", "sponsored content", "sponsored by",
    "paid partnership", "paid post", "advertorial", "this is a paid",
    "submit a guest", "contribute an article", "become a contributor",
    "link insertion", "niche edit", "pay per post",
]

# Markers of a parked / for-sale / expired domain. A link from one of these
# passes nothing at all.
PARKED_MARKERS = [
    "this domain is for sale", "domain is for sale", "buy this domain",
    "domain for sale", "this domain may be for sale",
    "the domain name you requested", "parked free, courtesy of",
    "this webpage is parked", "domain parking", "parkingcrew",
    "sedoparking", "afternic", "hugedomains", "dan.com",
    "future home of something quite cool", "website coming soon",
    "account suspended", "this account has been suspended",
    "bandwidth limit exceeded", "default web page", "apache2 debian default",
    "welcome to nginx", "it works!", "index of /",
    "under construction", "site not configured",
]

# Markers that the page is a bare link directory rather than real content.
LINK_DIRECTORY_MARKERS = [
    "submit your site", "add your site", "add url", "submit url",
    "web directory", "link directory", "free directory", "add a link",
    "submit link", "suggest a site", "directory listing", "seo directory",
    "article directory", "bookmark this site", "social bookmarking",
]

# ---------------------------------------------------------------------------
# Compiled matchers
# ---------------------------------------------------------------------------
def _is_ascii(word: str) -> bool:
    return all(ord(c) < 128 for c in word)


def _compile(words):
    """
    Build one matcher per keyword.

    ASCII keywords get a leading \b so "sex" cannot match "Essex". Non-ASCII
    keywords deliberately do NOT: \b is defined against word characters, and
    Thai, Japanese and Chinese are written without spaces, so a word boundary
    there either never matches or matches in the wrong place. For those a plain
    substring search is both correct and safe, because the scripts themselves
    make accidental collisions vanishingly unlikely.
    """
    pats = []
    for w in words:
        esc = re.escape(w)
        # allow hyphen OR space OR nothing between hyphenated parts
        esc = esc.replace(r"\-", r"[-\s]?").replace(r"\ ", r"\s+")
        prefix = r"\b" if _is_ascii(w) else ""
        pats.append((w, re.compile(rf"{prefix}{esc}", re.IGNORECASE)))
    return pats


_CONTENT_PATTERNS = {cat: _compile(words) for cat, words in CATEGORIES.items()}
_PAID_PATTERNS = _compile(PAID_LINK_MARKERS)
_DIRECTORY_PATTERNS = _compile(LINK_DIRECTORY_MARKERS)


def scan_url(url: str) -> dict:
    """Substring scan of a URL. Returns {'categories': [...], 'keywords': [...]}."""
    norm = (url or "").lower()
    cats, words = set(), set()
    for cat, kws in CATEGORIES.items():
        for w in kws:
            if w in norm:
                cats.add(cat)
                words.add(w)
    return {"categories": sorted(cats), "keywords": sorted(words)}


def scan_content(text: str) -> dict:
    """
    Word-boundary scan of visible page text.

    Returns:
      spammy       bool  - passed a threshold
      total        int   - total keyword hits
      categories   list  - categories with hits
      per_category dict  - {category: hit_count}
      top_keywords list  - most frequent matched keywords
    """
    text = text or ""
    per_cat, kw_counts = {}, {}
    total = 0
    for cat, pats in _CONTENT_PATTERNS.items():
        n_cat = 0
        for word, pat in pats:
            n = len(pat.findall(text))
            if n:
                kw_counts[word] = kw_counts.get(word, 0) + n
                n_cat += n
        if n_cat:
            per_cat[cat] = n_cat
            total += n_cat

    hard = sorted(w for w in kw_counts if w in UNAMBIGUOUS)
    spammy = (
        bool(hard)                                     # one is enough
        or total >= CONTENT_TOTAL_THRESHOLD
        or (max(per_cat.values()) if per_cat else 0) >= CONTENT_CATEGORY_THRESHOLD
    )
    top = sorted(kw_counts.items(), key=lambda kv: -kv[1])[:6]
    return {
        "spammy": spammy,
        "total": total,
        "categories": sorted(per_cat, key=lambda c: -per_cat[c]),
        "per_category": per_cat,
        "top_keywords": [f"{w} x{n}" for w, n in top],
        "unambiguous": hard,
    }


def _any_marker(text_lower: str, markers) -> list:
    return [m for m in markers if m in text_lower]


def scan_markers(text: str) -> dict:
    """Detect parked / paid-link / link-directory markers in page text."""
    low = (text or "").lower()
    parked = _any_marker(low, PARKED_MARKERS)
    paid = [w for w, pat in _PAID_PATTERNS if pat.search(low)]
    directory = [w for w, pat in _DIRECTORY_PATTERNS if pat.search(low)]
    return {
        "parked": parked,
        "paid_link": paid,
        "link_directory": directory,
    }
