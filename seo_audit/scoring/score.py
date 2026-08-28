"""
Composite scoring: turn all the signals into one 0-100 number and a verdict.

Philosophy
----------
The trust tier is a STARTING POINT, not the answer. A .edu that has been hacked
to serve casino text is worse than a clean .com. So:

  1. Start from the tier base score (config: scoring.tier_base).
  2. If real DA exists, blend it in (config: scoring.da_weight). Real data
     should outvote a guess based on the TLD.
  3. Apply penalties for everything actually wrong with the link.
  4. Hard caps override everything: a dead page or a parked domain cannot
     score well no matter how good the domain looks.

Verdicts
--------
  GOOD       keep it, it is working for you
  REVIEW     something is off - look at it yourself
  LOW_VALUE  passes no ranking signal (nofollow / noindex / thin), but is NOT
             harmful. Do not disavow these - you just get nothing from them.
  TOXIC      real spam signals present. Disavow candidate.
  LINK_LOST  page is alive but your link has been removed. This is an outreach
             job, not a disavow job - which is why it gets its own verdict.
  DEAD       404 / 410 / DNS failure - the page or domain no longer exists
  BLOCKED    401 / 403 / 429 / 5xx / broken TLS - the page exists but we could
             not read it,
             so it is not judged. 5xx is usually temporary; re-run later.

The LOW_VALUE vs TOXIC split matters: disavowing a merely-useless link is a
mistake that can cost you rankings. Only genuine spam earns TOXIC.
"""


def _f(v):
    """Coerce to float or None."""
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def score_row(row: dict, cfg: dict) -> dict:
    """
    Score one audited backlink. `row` holds merged status + page + metrics data.
    Returns {score, verdict, issues, wins, action}.
    """
    sc = cfg.get("scoring", {}) or {}
    tier_base = sc.get("tier_base", {}) or {}
    pen = sc.get("penalties", {}) or {}
    thr = sc.get("thresholds", {}) or {}
    content_cfg = cfg.get("content", {}) or {}

    def P(key, default=0):
        return float(pen.get(key, default))

    tier = row.get("tier", "D")
    score = float(tier_base.get(tier, 58))
    issues, wins = [], []

    # ---- 1. blend in real DA -----------------------------------------
    da = _f(row.get("da"))
    if da is not None:
        w = float(sc.get("da_weight", 0.5))
        w = min(max(w, 0.0), 1.0)
        score = score * (1 - w) + da * w
        if da >= 60:
            wins.append(f"strong DA {da:.0f}")
        elif da >= 35:
            wins.append(f"decent DA {da:.0f}")
        elif da < 15:
            issues.append(f"very low DA {da:.0f}")
    else:
        issues.append("no DA/PA data (scored on tier + on-page signals only)")

    # ---- 2. status ----------------------------------------------------
    sv = row.get("status_verdict", "ERROR")
    hard_cap = None

    if sv in ("DEAD", "GONE"):
        hard_cap = 5
        issues.append(f"page is dead ({row.get('status_code')})")
    elif sv == "DNS_ERROR":
        hard_cap = 3
        issues.append("domain does not resolve - the domain itself is gone, not just the page")
    elif sv == "SSL_ERROR":
        # The site exists and answers; its certificate is untrusted. Visitors
        # get a security warning, so the link is worthless in practice -- but
        # this is NOT a dead domain and must not be disavowed as one.
        hard_cap = 40
        issues.append(f"HTTPS is broken ({row.get('error') or 'certificate error'}) - "
                      f"visitors see a security warning. Verify manually before acting.")
    elif sv == "ERROR":
        hard_cap = 15
        issues.append(f"unreachable: {row.get('error') or 'connection failed'}")
    elif sv == "SERVER_ERROR":
        hard_cap = 30
        issues.append(f"server error {row.get('status_code')} (may be temporary - re-check later)")
    elif sv == "BLOCKED":
        hard_cap = 45
        issues.append(f"page returned {row.get('status_code')} to our crawler - cannot verify content")
    elif sv == "RATE_LIMITED":
        hard_cap = 45
        issues.append("rate-limited (429) - re-run this one with lower concurrency")
    elif sv in ("REDIRECT_PERM", "REDIRECT_TEMP"):
        hops = int(row.get("redirect_hops") or 0)
        score -= P("redirect", 5)
        kind = "301 permanent" if sv == "REDIRECT_PERM" else "302 temporary"
        issues.append(f"link points at a {kind} redirect -> {row.get('final_url', '')[:80]}")
        if hops >= 3:
            score -= P("redirect_chain_long", 8)
            issues.append(f"long redirect chain ({hops} hops) - authority leaks at every hop")
        if row.get("redirect_offsite"):
            score -= 5
            issues.append("redirect lands on a different domain")
    elif sv == "LIVE":
        wins.append("live 200 OK")

    if not row.get("https", True):
        score -= P("non_https", 3)
        issues.append("http:// not https://")
    if row.get("tls_invalid"):
        score -= P("tls_invalid", 12)
        issues.append("TLS certificate is untrusted - real visitors get a browser "
                      "security warning before they ever see your link")
    if row.get("https_unavailable"):
        score -= P("no_https", 6)
        issues.append("site serves http only; https is unavailable")

    # ---- 3. link verification ----------------------------------------
    checked_content = sv in ("LIVE", "REDIRECT_PERM", "REDIRECT_TEMP")
    if row.get("target_checked"):
        if row.get("link_found"):
            if row.get("is_followed"):
                wins.append("link present and followed")
            rels = []
            if row.get("is_nofollow"):
                score -= P("nofollow", 10)
                rels.append("nofollow")
            if row.get("is_sponsored"):
                score -= P("sponsored", 8)
                rels.append("sponsored")
            if row.get("is_ugc"):
                score -= P("ugc", 6)
                rels.append("ugc")
            if rels:
                issues.append(f"link is rel=\"{' '.join(rels)}\" - passes no ranking signal")
            if row.get("link_in_hidden_block"):
                score -= 15
                issues.append("link sits inside a hidden element - looks like cloaking")
            if row.get("link_is_sitewide"):
                score -= P("sitewide_link", 12)
                issues.append("link is sitewide boilerplate (footer/sidebar/blogroll), not an "
                              "in-content citation - Google discounts these heavily")
            elif row.get("link_placement") == "in-content":
                wins.append("in-content editorial link")
        elif checked_content:
            score -= P("link_missing", 30)
            issues.append("YOUR LINK IS GONE - page loads but the link to your site is not on it")

    # ---- 4. indexability ---------------------------------------------
    if row.get("is_noindex"):
        score -= P("noindex", 25)
        issues.append("page is noindex - Google never sees this link")
    if row.get("is_nofollow_page"):
        score -= 10
        issues.append("page-level meta nofollow")
    if row.get("robots_blocked"):
        score -= P("robots_blocked", 15)
        issues.append("blocked by robots.txt")

    # ---- 5. spam / neighbourhood -------------------------------------
    ss = _f(row.get("spam_score"))
    if ss is not None:
        if ss > 60:
            score -= P("spam_score_high", 30)
            issues.append(f"Spam Score {ss:.0f}% (high)")
        elif ss > 30:
            score -= P("spam_score_mid", 15)
            issues.append(f"Spam Score {ss:.0f}% (medium)")
        else:
            wins.append(f"low Spam Score {ss:.0f}%")

    url_spam = row.get("url_spam_categories") or ""
    content_spam = row.get("content_spam")
    if url_spam:
        score -= P("bad_neighbourhood", 35)
        issues.append(f"spam keywords in the URL: {url_spam}")
    if content_spam:
        # A tier A/B site merely *mentioning* these terms is usually a topical
        # article (Wikipedia on 'online gambling'), not a spam page.
        if tier in ("A", "B"):
            score -= 10
            issues.append(f"page mentions {row.get('content_spam_categories')} "
                          f"({row.get('content_spam_total')} hits) - likely topical on this domain, but verify")
        else:
            score -= P("bad_neighbourhood", 35)
            issues.append(f"page content is spammy: {row.get('content_spam_categories')} "
                          f"({row.get('content_spam_total')} hits)")

    if row.get("parked_markers"):
        hard_cap = min(hard_cap if hard_cap is not None else 999, 8)
        issues.append(f"parked / expired / placeholder page: \"{row.get('parked_markers')}\"")

    if row.get("lang_mismatch"):
        score -= P("lang_mismatch", 10)
        issues.append(f"page language is '{row.get('lang')}', which is not one you target - "
                      f"a link from another language audience is rarely relevant")

    if row.get("network_id"):
        ncfg = cfg.get("network_footprint", {}) or {}
        score -= float(ncfg.get("penalty_per_cluster", 12))
        issues.append(f"part of link network {row['network_id']} "
                      f"({row.get('network_size')} domains sharing "
                      f"{row.get('network_signals','')[:80]})")

    if row.get("free_subdomain"):
        score -= 12
        issues.append("free subdomain / dynamic-DNS host - the linker does not own this domain")

    if row.get("spam_tld"):
        score -= 6
        issues.append(f".{row.get('suffix')} is a TLD heavily used by link networks")

    # ---- 5b. the site's HOME PAGE (stage 3) --------------------------
    # A clean-looking article on a domain whose home page is now an online
    # casino is the expired-domain flip. Judging only the linking page misses
    # it completely, which is why stage 3 exists.
    home_spam = False
    if row.get("home_checked") and not row.get("home_same_as_page"):
        if row.get("home_parked_markers"):
            home_spam = True
            score -= P("homepage_parked", 50)
            issues.append(f'the site\'s HOME PAGE is parked/for-sale '
                          f'("{row.get("home_parked_markers")}") - the site is not really running')
        if row.get("home_content_spam"):
            home_spam = True
            score -= P("homepage_spam", 40)
            issues.append(f"linking page looks acceptable but the site's HOME PAGE is spam "
                          f"({row.get('home_content_spam_categories')}) - looks like an "
                          f"expired domain flipped to spam")
        hsv = row.get("home_status_verdict")
        if hsv and hsv not in ("LIVE", "REDIRECT_PERM", "REDIRECT_TEMP"):
            score -= P("homepage_dead", 15)
            issues.append(f"linking page is live but the site's home page is {hsv} - "
                          f"the site may be half-abandoned")
        hob = int(row.get("home_outbound_links") or 0)
        if hob >= int(content_cfg.get("outbound_bad", 300)):
            home_spam = True
            score -= P("outbound_extreme", 20)
            issues.append(f"home page carries {hob} outbound links - the site is a link farm")

    # ---- 6. page quality --------------------------------------------
    if checked_content and not row.get("page_error"):
        wc = int(row.get("word_count") or 0)
        min_wc = int(content_cfg.get("min_word_count", 150))
        if wc < min_wc:
            score -= P("thin_content", 8)
            issues.append(f"thin content ({wc} words)")

        ob = int(row.get("outbound_links") or 0)
        warn = int(content_cfg.get("outbound_warn", 150))
        bad = int(content_cfg.get("outbound_bad", 300))
        if ob >= bad:
            score -= P("outbound_extreme", 20)
            issues.append(f"{ob} outbound links - link farm behaviour")
        elif ob >= warn:
            score -= P("outbound_high", 10)
            issues.append(f"{ob} outbound links (high)")

        if row.get("link_directory_markers"):
            score -= P("link_directory", 12)
            issues.append(f"looks like a link directory: \"{row.get('link_directory_markers')}\"")

        if row.get("paid_link_markers"):
            score -= P("paid_link_marker", 8)
            issues.append(f"paid/guest-post markers: \"{row.get('paid_link_markers')}\" - "
                          f"Google's link-spam policy targets these")

        rel = _f(row.get("relevance_score"))
        if rel is not None and content_cfg.get("relevance_keywords"):
            if rel >= 50:
                wins.append(f"topically relevant ({rel:.0f}%)")
            elif rel == 0 and wc >= min_wc:
                score -= 5
                issues.append("no topical overlap with your keywords")

    # ---- 7. finalise -------------------------------------------------
    if hard_cap is not None:
        score = min(score, hard_cap)
    score = int(round(max(0, min(100, score))))

    good = float(thr.get("good", 75))
    review = float(thr.get("review", 50))

    # Did we see evidence of actual SPAM, as opposed to mere uselessness?
    # This decides TOXIC (disavow) vs LOW_VALUE (harmless, just worthless).
    spam_evidence = bool(
        home_spam
        or row.get("url_spam_categories")
        or row.get("parked_markers")
        or (content_spam and tier not in ("A", "B"))
        or (ss is not None and ss > 60)
        or row.get("link_in_hidden_block")
        or (row.get("link_directory_markers") and int(row.get("outbound_links") or 0) >= int(content_cfg.get("outbound_warn", 150)))
        or int(row.get("outbound_links") or 0) >= int(content_cfg.get("outbound_bad", 300))
        or (row.get("network_id") and int(row.get("network_size") or 0) >= 5)
    )

    if sv in ("DEAD", "GONE", "ERROR", "DNS_ERROR"):
        verdict = "DEAD"
    elif sv in ("BLOCKED", "RATE_LIMITED", "SERVER_ERROR", "SSL_ERROR"):
        # We could not read the page, so we must not pretend to judge it.
        # 5xx belongs here rather than with DEAD: it is usually temporary.
        verdict = "BLOCKED"
    elif spam_evidence and score < good:
        verdict = "TOXIC"
    elif row.get("target_checked") and checked_content and not row.get("link_found"):
        # Page is fine, the link is simply not there any more.
        verdict = "LINK_LOST"
    elif score >= good:
        verdict = "GOOD"
    elif score >= review:
        verdict = "REVIEW"
    else:
        verdict = "LOW_VALUE"

    action = {
        "GOOD": "Keep. No action needed.",
        "REVIEW": "Look at this one yourself before deciding.",
        "LOW_VALUE": "Harmless but passes nothing. Do NOT disavow - just do not count it as a win.",
        "TOXIC": "Disavow candidate - verify, then use the generated disavow.txt.",
        "LINK_LOST": "Page is live but your link was removed. Contact the site and ask for it back.",
        "DEAD": "Page is gone. Ask for a fix, redirect it, or drop it from your list.",
        "BLOCKED": "Could not verify (403/429/5xx). Open it in a browser, or re-run later.",
    }[verdict]

    if verdict == "DEAD" and row.get("root_note"):
        action += f" {row['root_note']}"

    return {
        "score": score,
        "verdict": verdict,
        "spam_evidence": spam_evidence,
        "issues": "; ".join(issues) if issues else "none found",
        "wins": "; ".join(wins),
        "action": action,
        "issue_count": len(issues),
    }
