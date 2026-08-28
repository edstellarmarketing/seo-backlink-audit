"""
Anchor-text distribution analysis.

Per-link anchor text is nearly useless on its own. Risk lives in the
DISTRIBUTION: if 60% of your followed links all say "corporate training
company", that is not a natural link profile, and exact-match anchor
over-optimisation is one of the oldest triggers for a manual penalty.

A healthy profile is mostly branded and naked-URL anchors, with keyword
anchors as a minority. This module reports what you actually have.
"""

import re
from collections import Counter

_WS = re.compile(r"\s+")
_URLISH = re.compile(r"^(https?://|www\.)|\.(com|org|net|io|co|in|de)\b", re.I)
_GENERIC = {
    "click here", "here", "read more", "more", "link", "this", "this link",
    "website", "visit", "visit website", "learn more", "see more", "source",
    "read the full article", "continue reading", "check it out", "view",
}


def classify_anchor(text: str, brand_terms) -> str:
    """branded | naked-url | generic | image-empty | keyword"""
    t = _WS.sub(" ", (text or "")).strip().lower()
    if not t or t in ("[image/empty anchor]",):
        return "image-empty"
    if any(b and b in t for b in brand_terms):
        return "branded"
    if _URLISH.search(t):
        return "naked-url"
    if t in _GENERIC or len(t) <= 3:
        return "generic"
    return "keyword"


def analyse(rows: list, cfg: dict) -> dict:
    """
    Returns a distribution report plus warnings. Only counts links we actually
    found on a page -- an anchor you cannot see is not part of your profile.
    """
    acfg = (cfg.get("anchors") or {})
    max_share = float(acfg.get("max_single_anchor_share", 25))
    max_kw_share = float(acfg.get("max_keyword_share", 50))

    brand = [str(b).lower().strip() for b in (acfg.get("brand_terms") or []) if str(b).strip()]
    if not brand:
        target = str(cfg.get("target_site", "") or "")
        stem = target.replace("www.", "").split(".")[0].lower()
        if stem:
            brand = [stem]

    anchors, kinds, followed = Counter(), Counter(), 0
    for r in rows:
        if not r.get("link_found"):
            continue
        raw = str(r.get("anchor_texts") or "")
        for piece in [p.strip() for p in raw.split("|") if p.strip()]:
            anchors[piece.lower()] += 1
            kinds[classify_anchor(piece, brand)] += 1
        if r.get("is_followed"):
            followed += 1

    total = sum(anchors.values())
    warnings = []
    if total:
        top_text, top_n = anchors.most_common(1)[0]
        top_share = 100 * top_n / total
        if top_share > max_share and top_n >= 3:
            warnings.append(
                f'"{top_text}" is {top_share:.0f}% of all anchors ({top_n} of {total}). '
                f"Above ~{max_share:.0f}% a single anchor starts to look manufactured.")
        kw_share = 100 * kinds.get("keyword", 0) / total
        if kw_share > max_kw_share:
            warnings.append(
                f"{kw_share:.0f}% of anchors are keyword anchors. A natural profile leans "
                f"on branded and naked-URL anchors; consider diversifying.")
        if kinds.get("branded", 0) == 0:
            warnings.append(
                "No branded anchors at all. Real editorial mentions usually use your "
                "brand name, so a profile with none looks built rather than earned.")
        img = kinds.get("image-empty", 0)
        if img and 100 * img / total > 40:
            warnings.append(
                f"{100*img/total:.0f}% of links have an empty or image anchor, which passes "
                f"little textual relevance.")

    return {
        "total_anchors": total,
        "followed_links": followed,
        "distinct_anchors": len(anchors),
        "top_anchors": anchors.most_common(25),
        "kinds": dict(kinds),
        "warnings": warnings,
        "brand_terms": brand,
    }
