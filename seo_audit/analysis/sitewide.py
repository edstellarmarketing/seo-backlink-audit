"""
True sitewide detection, by sampling.

`page.py` classifies a link's PLACEMENT structurally -- is it inside an
article, or inside footer/sidebar boilerplate. That is a good proxy but it
answers a different question from the one that matters. "Sitewide" means the
link appears on every page of the site, and no amount of looking at one page
can establish that.

So: take a few internal URLs from the page we already downloaded, fetch them,
and count how many also carry the link. If the link shows up on all of them it
is sitewide in fact, not just in appearance -- and that is worth knowing,
because one sitewide link across 400 pages is treated by Google as roughly one
link, not four hundred.

Costs `sample_size` extra requests per domain, so it is opt-in and only runs
where it can tell you something: when the link was actually found.
"""

from seo_audit.net import fetch
from seo_audit.analysis import page as page_mod


def sample(session, cfg, throttle, row: dict, target: str, aliases,
           sample_size: int = 3) -> dict:
    """
    Returns sitewide_* fields. Never raises; degrades to "not checked".
    """
    out = {
        "sitewide_checked": False,
        "sitewide_sampled": 0,
        "sitewide_hits": 0,
        "sitewide_ratio": 0.0,
        "sitewide_note": "",
    }
    if sample_size <= 0 or not row.get("link_found") or not target:
        return out

    candidates = [u for u in (row.get("internal_urls") or [])][:sample_size * 3]
    if not candidates:
        out["sitewide_note"] = "no internal links to sample"
        return out

    checked, hits = 0, 0
    for url in candidates:
        if checked >= sample_size:
            break
        html, err = fetch.fetch_html(
            session, url, cfg, throttle,
            verify=(False if row.get("tls_invalid") else None))
        if err or not html:
            continue
        checked += 1
        try:
            a = page_mod.analyze(html, url, target, aliases, cfg)
        except Exception:                       # noqa: BLE001
            continue
        if a.get("link_found"):
            hits += 1

    out["sitewide_checked"] = checked > 0
    out["sitewide_sampled"] = checked
    out["sitewide_hits"] = hits
    out["sitewide_ratio"] = round(hits / checked, 2) if checked else 0.0

    if not checked:
        out["sitewide_note"] = "could not fetch any sample pages"
    elif hits == checked and checked >= 2:
        out["sitewide_note"] = (
            f"link found on all {checked} sampled pages - genuinely sitewide. "
            f"Google treats a sitewide link as roughly one link, not one per page.")
    elif hits:
        out["sitewide_note"] = (f"link found on {hits} of {checked} sampled pages - "
                                f"appears on some templates but not all")
    else:
        out["sitewide_note"] = (f"link absent from all {checked} sampled pages - "
                                f"a genuine one-off placement, which is what you want")
    return out
