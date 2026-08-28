"""
Staged gating: decide whether a link is worth carrying to the next stage.

The pipeline runs cheapest-first and stops as soon as a link is disqualified:

    Stage 1  live?            a 404 needs no content scan and no DA lookup
    Stage 2  page content     a casino page needs no DA lookup either
    Stage 3  home page        catches the expired-domain flip
    Stage 4  DA / PA / SS     only for links that survived 1-3

The point is economy. DA/PA is the expensive stage -- it costs API credits, or
your own clicking time on a free checker. Spending it on a domain that is
already dead or already spam is waste, and on a list of a thousand backlinks
that waste is most of the work.
"""

STAGE_LIVE = "1-live"
STAGE_PAGE = "2-page-content"
STAGE_HOME = "3-homepage"
STAGE_METRICS = "4-metrics"

REACHABLE = ("LIVE", "REDIRECT_PERM", "REDIRECT_TEMP")


def evaluate(row: dict, cfg: dict) -> dict:
    """
    Returns:
      gate_passed   bool  - survived every gate, so DA/PA is worth buying
      gate_stage    str   - the stage it reached (or failed at)
      gate_reason   str   - plain-English why
      needs_metrics bool  - should this domain go to the DA/PA stage
    """
    pcfg = cfg.get("pipeline", {}) or {}
    ccfg = cfg.get("content", {}) or {}
    staged = bool(pcfg.get("staged", True))

    out = {"gate_passed": True, "gate_stage": STAGE_METRICS,
           "gate_reason": "", "needs_metrics": True}

    if not staged:
        return out

    def fail(stage, reason):
        return {"gate_passed": False, "gate_stage": stage, "gate_reason": reason,
                "needs_metrics": not bool(pcfg.get("metrics_only_for_passing", True))}

    # ---- Stage 1: is it live? ----------------------------------------
    sv = row.get("status_verdict", "ERROR")
    if sv not in REACHABLE:
        label = {
            "DNS_ERROR": "domain does not resolve",
            "SSL_ERROR": "HTTPS/certificate is broken",
            "DEAD": f"page returns {row.get('status_code')}",
            "GONE": "page returns 410 Gone",
            "SERVER_ERROR": f"server error {row.get('status_code')}",
            "BLOCKED": f"page refused us ({row.get('status_code')})",
            "RATE_LIMITED": "rate-limited (429)",
            "ERROR": row.get("error") or "unreachable",
        }.get(sv, sv)
        return fail(STAGE_LIVE, f"Stopped at stage 1: not live - {label}. "
                                f"No content scan or DA/PA lookup needed.")

    # ---- Stage 2: is the linking page clean? -------------------------
    if row.get("parked_markers"):
        return fail(STAGE_PAGE, f'Stopped at stage 2: page is parked/for-sale '
                                f'("{row.get("parked_markers")}").')
    if row.get("url_spam_categories"):
        return fail(STAGE_PAGE, f"Stopped at stage 2: spam keywords in the URL "
                                f"({row.get('url_spam_categories')}).")
    if row.get("content_spam") and row.get("tier") not in ("A", "B"):
        return fail(STAGE_PAGE, f"Stopped at stage 2: page content is spam "
                                f"({row.get('content_spam_categories')}).")
    if row.get("link_in_hidden_block"):
        return fail(STAGE_PAGE, "Stopped at stage 2: the link is hidden inside a "
                                "display:none block - cloaking.")
    ob = int(row.get("outbound_links") or 0)
    if ob >= int(ccfg.get("outbound_bad", 300)):
        return fail(STAGE_PAGE, f"Stopped at stage 2: {ob} outbound links - link farm.")
    if row.get("link_directory_markers") and ob >= int(ccfg.get("outbound_warn", 150)):
        return fail(STAGE_PAGE, f"Stopped at stage 2: link directory carrying {ob} outbound "
                                f"links - it aggregates or sells links rather than publishing "
                                f"content.")
    if bool(pcfg.get("noindex_fails_gate", True)) and row.get("is_noindex"):
        return fail(STAGE_PAGE, "Stopped at stage 2: page is noindex, so it cannot pass "
                                "ranking signal - its DA is irrelevant.")

    # ---- Stage 3: is the home page clean? ---------------------------
    if row.get("home_checked"):
        if row.get("home_parked_markers"):
            return fail(STAGE_HOME, f'Stopped at stage 3: the site\'s HOME PAGE is '
                                    f'parked/for-sale ("{row.get("home_parked_markers")}").')
        if row.get("home_content_spam"):
            return fail(STAGE_HOME, f"Stopped at stage 3: the linking page looks acceptable "
                                    f"but the site's HOME PAGE is spam "
                                    f"({row.get('home_content_spam_categories')}) - "
                                    f"classic expired-domain flip.")
        hob = int(row.get("home_outbound_links") or 0)
        if hob >= int(ccfg.get("outbound_bad", 300)):
            return fail(STAGE_HOME, f"Stopped at stage 3: home page has {hob} outbound "
                                    f"links - the site is a link farm.")
        if row.get("home_status_verdict") and row.get("home_status_verdict") not in REACHABLE:
            # Not a hard fail: a live article on a site whose homepage 404s is odd
            # but not proof of spam. Flag it and carry on.
            out["gate_reason"] = (f"Note: linking page is live but the home page is "
                                 f"{row.get('home_status_verdict')}.")

    out["gate_reason"] = out["gate_reason"] or "Passed live + content gates - DA/PA worth checking."
    return out
