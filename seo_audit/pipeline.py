"""
The per-link pipeline: everything that happens to one backlink.

Stages run cheapest-first and a link that fails a stage does not reach the
next one. See seo_audit/scoring/gate.py for the gate rules themselves; this
module is the order the work happens in.
"""

from seo_audit.analysis import classify
from seo_audit.analysis import domains as dom
from seo_audit.analysis import homepage as homepage_mod
from seo_audit.analysis import page as page_mod
from seo_audit.analysis import sitewide as sitewide_mod
from seo_audit.analysis import spamrules
from seo_audit.net import fetch
from seo_audit.scoring import gate as gate_mod

_is_homepage = homepage_mod._is_homepage
origin_of = homepage_mod.origin_of


def audit_one(item: dict, session, cfg, throttle, robots, authority,
              scan_content: bool, homecache=None, dns=None, db=None) -> dict:
    url = item["url"]
    target = item.get("target") or cfg.get("target_site") or ""
    aliases = cfg.get("target_aliases") or []

    row = {
        "url": url,
        "input_target": target,
        "input_anchor": item.get("anchor", ""),
        "notes": item.get("notes", ""),
        "target_checked": bool(target),
        "page_error": "",
        "robots_blocked": False,
    }

    # 0. is this domain already on the master list?
    #    This TAGS the row. It deliberately does not gate anything: a domain you
    #    already know about still gets every live check, because the whole
    #    question is whether it changed since you last looked.
    if db is not None:
        try:
            row.update(db.lookup(url))
        except Exception as exc:                     # noqa: BLE001
            row["master_note"] = f"master lookup failed: {type(exc).__name__}"

    # 1. domain trust tier
    row.update(classify.classify_domain(url, authority))

    # 2. URL-level spam keywords
    us = spamrules.scan_url(url)
    row["url_spam_categories"] = ", ".join(us["categories"])
    row["url_spam_keywords"] = ", ".join(us["keywords"])

    # 3. HTTP status
    row.update(fetch.check_status(session, url, cfg, throttle, dns))

    # 4. root-domain probe when it failed
    if row["status_verdict"] in ("DEAD", "GONE", "ERROR", "SERVER_ERROR"):
        row.update(fetch.check_root_domain(session, url, cfg, throttle, dns))
    else:
        row.setdefault("root_note", "")
        row.setdefault("root_domain", "")

    # 5. page analysis
    reachable = row["status_verdict"] in ("LIVE", "REDIRECT_PERM", "REDIRECT_TEMP")
    if scan_content and reachable:
        page_url = row.get("final_url") or url
        html, err = fetch.fetch_html(
            session, page_url, cfg, throttle,
            verify=(False if row.get("tls_invalid") else None))
        if err:
            row["page_error"] = err
        else:
            row.update(page_mod.analyze(html, page_url, target, aliases, cfg))
            if row.get("error") and not row.get("status_code"):
                row["page_error"] = row.pop("error")
        try:
            row["robots_blocked"] = robots.blocked(page_url)
        except Exception as exc:                     # noqa: BLE001
            # Record it rather than swallowing it -- a silent except here once
            # hid a NameError and made every page look robots-allowed.
            row["robots_error"] = f"{type(exc).__name__}: {exc}"

    # 6. STAGE 3 - the domain's home page
    pcfg = cfg.get("pipeline", {}) or {}
    row["home_checked"] = False
    if homecache is not None and bool(pcfg.get("check_homepage", True)) and reachable:
        page_for_home = row.get("final_url") or url
        origin = origin_of(page_for_home)
        if origin:
            if _is_homepage(page_for_home):
                # The linking page IS the home page - reuse what we already have
                # instead of fetching the same URL a second time.
                row.update({
                    "home_checked": True,
                    "home_url": row.get("final_url") or url,
                    "home_status_code": row.get("status_code"),
                    "home_status_verdict": row.get("status_verdict"),
                    "home_title": row.get("page_title", ""),
                    "home_word_count": row.get("word_count", 0),
                    "home_outbound_links": row.get("outbound_links", 0),
                    "home_is_noindex": row.get("is_noindex", False),
                    "home_content_spam": row.get("content_spam", False),
                    "home_content_spam_total": row.get("content_spam_total", 0),
                    "home_content_spam_categories": row.get("content_spam_categories", ""),
                    "home_parked_markers": row.get("parked_markers", ""),
                    "home_paid_link_markers": row.get("paid_link_markers", ""),
                    "home_link_directory_markers": row.get("link_directory_markers", ""),
                    "home_same_as_page": True,
                })
            else:
                row.update(homecache.get(origin, target, aliases))
                row["home_same_as_page"] = False

    # 6b. sitewide sampling - only meaningful when the link was found
    n_sample = int((cfg.get("pipeline", {}) or {}).get("sitewide_sample", 0))
    if n_sample and row.get("link_found"):
        try:
            row.update(sitewide_mod.sample(session, cfg, throttle, row,
                                           target, aliases, n_sample))
        except Exception as exc:                     # noqa: BLE001
            row["sitewide_note"] = f"sampling failed: {type(exc).__name__}"

    # Two cases are worth a real browser:
    #   1. the page loaded but the link is missing (it may be JS-injected);
    #   2. the page REFUSED us, or its TLS failed. Bot protection blocks a
    #      plain HTTP client and waves a browser through, so these are
    #      readable in practice - they just are not readable by requests.
    pcfg_r = cfg.get("pipeline", {}) or {}
    blocked_kind = row.get("status_verdict") in ("BLOCKED", "RATE_LIMITED", "SSL_ERROR")
    row["needs_render"] = bool(
        (row.get("target_checked") and reachable
         and not row.get("link_found") and not row.get("page_error"))
        or (blocked_kind and bool(pcfg_r.get("render_blocked", True))))
    row["render_reason"] = ("blocked" if blocked_kind and not reachable
                            else ("link-missing" if row["needs_render"] else ""))

    # 7. gate: decide whether stage 4 (DA/PA) is worth spending on
    row.update(gate_mod.evaluate(row, cfg))
    return row
