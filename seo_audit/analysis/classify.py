"""
Domain trust classification -> tiers A / B / C / D.

  A  Institutional. .gov .edu .mil .int and their country variants
     (.ac.uk, .edu.au, .gob.mx ...). Registration is restricted, so the
     signal is strong and hard to fake.

  B  Curated high-authority sites from data/authority_domains.yaml
     (Wikipedia, Glassdoor, Crunchbase, GitHub, major press ...).

  C  Non-profit-flavoured TLDs: .org .ngo .int .foundation.
     IMPORTANT: .org has been open registration since the 1990s. It is a
     WEAK signal, not a good one -- spam networks buy .org in bulk precisely
     because people assume it means "non-profit". Tier C sits below B on
     purpose and is still fully spam-checked.

  D  Everything else. Not bad -- just unproven without DA/PA.

A tier is a STARTING POINT for the score, never the verdict. Spam signals,
noindex, dead status and missing links all override it. A hacked .edu page
serving casino text scores worse than a clean .com.
"""

import os
import re
import yaml

from seo_audit.analysis import domains as dom

# ---------------------------------------------------------------------------
# Tier A: restricted institutional suffixes
# ---------------------------------------------------------------------------
INSTITUTIONAL_SUFFIXES = {
    # global restricted
    "gov", "edu", "mil", "int",
    # education
    "ac.uk", "ac.in", "edu.in", "ac.jp", "ac.kr", "ac.nz", "ac.za", "ac.ae",
    "ac.il", "ac.ir", "ac.cy", "ac.at", "ac.ie", "ac.be", "ac.th", "ac.id",
    "ac.cn", "ac.ke", "ac.tz", "ac.ug", "ac.zm", "ac.zw", "ac.mu", "ac.ma",
    "ac.bw", "ac.mz", "ac.pa", "ac.cr", "ac.pk", "ac.bd", "ac.vn", "ac.ru",
    "ac.kr", "ac.mx",
    "edu.au", "edu.sg", "edu.my", "edu.cn", "edu.tw", "edu.hk", "edu.mo",
    "edu.ph", "edu.vn", "edu.pk", "edu.bd", "edu.np", "edu.lk", "edu.kh",
    "edu.bn", "edu.kz", "edu.mn", "edu.ge", "edu.tr", "edu.pl", "edu.ua",
    "edu.ru", "edu.gr", "edu.mt", "edu.rs", "edu.es", "edu.it", "edu.pt",
    "edu.sa", "edu.qa", "edu.kw", "edu.bh", "edu.om", "edu.jo", "edu.lb",
    "edu.iq", "edu.eg", "edu.ng", "edu.gh", "edu.et", "edu.dz", "edu.tn",
    "edu.na", "edu.ao", "edu.za", "edu.br", "edu.mx", "edu.ar", "edu.co",
    "edu.pe", "edu.ve", "edu.ec", "edu.uy", "edu.bo", "edu.do", "edu.gt",
    "edu.sv", "edu.hn", "edu.ni", "edu.pa", "edu.cu", "edu.pr", "edu.jm",
    "edu.tt", "edu.bz", "edu.bs", "edu.bb", "edu.gy", "edu.py",
    "sch.uk", "sch.id", "sch.ir", "sch.sa", "sch.ae", "sch.ng",
    "k12.tr", "k12.il", "ed.jp", "ed.cr", "school.nz", "sc.ke",
    "res.in", "nic.in",
    # government
    "gov.uk", "gov.au", "gov.in", "gov.sg", "gov.my", "gov.cn", "gov.tw",
    "gov.hk", "gov.mo", "gov.ph", "gov.vn", "gov.pk", "gov.bd", "gov.np",
    "gov.lk", "gov.kh", "gov.kz", "gov.mn", "gov.tr", "gov.pl", "gov.ua",
    "gov.ru", "gov.gr", "gov.mt", "gov.rs", "gov.it", "gov.nl", "gov.ie",
    "gov.cy", "gov.pt", "gov.sa", "gov.qa", "gov.kw", "gov.bh", "gov.om",
    "gov.jo", "gov.lb", "gov.iq", "gov.il", "gov.ae", "gov.ir", "gov.eg",
    "gov.ng", "gov.gh", "gov.et", "gov.dz", "gov.tn", "gov.za", "gov.zw",
    "gov.zm", "gov.mu", "gov.bw", "gov.mz", "gov.ao", "gov.cm", "gov.br",
    "gov.co", "gov.py", "gov.pr", "gov.jm", "gov.tt", "gov.bz", "gov.bs",
    "gov.bb", "gov.gy", "gov.cl", "gov.mx", "gov.sd",
    "gob.mx", "gob.pe", "gob.ar", "gob.es", "gob.ve", "gob.ec", "gob.cl",
    "gob.bo", "gob.do", "gob.gt", "gob.sv", "gob.hn", "gob.ni", "gob.pa",
    "gob.cu", "gub.uy",
    "gouv.fr", "gouv.sn", "gouv.ci", "go.jp", "go.kr", "go.id", "go.th",
    "go.ke", "go.tz", "go.ug", "govt.nz", "gv.at", "jus.br", "gc.ca",
    "canada.ca", "mod.uk", "nhs.uk", "police.uk", "judiciary.uk",
    "mil.in", "mil.co", "mil.ar", "mil.cn", "mil.pe",
    "muni.il", "lg.jp", "bel.tr",
}

# Tier C: non-profit-flavoured but OPEN registration -> weak signal only
NONPROFIT_SUFFIXES = {
    "org", "ngo", "ong", "foundation", "charity", "org.uk", "org.au",
    "org.in", "org.nz", "org.za", "org.sg", "org.my", "org.cn", "org.tw",
    "org.hk", "org.ph", "org.vn", "org.pk", "org.bd", "org.np", "org.lk",
    "org.tr", "org.pl", "org.ua", "org.ru", "org.gr", "org.rs", "org.es",
    "org.it", "org.pt", "org.sa", "org.qa", "org.kw", "org.ae", "org.il",
    "org.ir", "org.eg", "org.ng", "org.gh", "org.et", "org.tn", "org.za",
    "org.br", "org.mx", "org.ar", "org.co", "org.pe", "org.ve", "org.ec",
    "org.uy", "org.py", "org.do", "org.se", "org.ro", "org.pl", "or.jp",
    "or.kr", "or.id", "or.th", "or.ke", "or.tz", "or.cr", "or.at",
    "asso.fr", "asn.au",
}

# Frequently-abused TLDs in link networks. Not automatically toxic, but a
# strong "prove yourself" signal.
SPAM_TLDS = {
    "xyz", "top", "loan", "click", "link", "gq", "ml", "cf", "ga", "tk",
    "work", "bid", "date", "review", "stream", "download", "racing", "win",
    "party", "science", "men", "webcam", "cricket", "accountant", "trade",
    "faith", "country", "kim", "mom", "wang", "buzz", "rest", "cyou",
    "monster", "quest", "shop", "icu", "sbs", "bar", "casa", "surf",
    "fit", "pw", "cc", "ws", "su", "info", "biz", "us.com",
}

_AUTH_CACHE = {"path": None, "mtime": None, "map": {}}


def load_authority_domains(path: str | None = None) -> dict:
    """
    Load data/authority_domains.yaml -> {registered_domain: group_name}.
    Re-reads the file when it changes so edits take effect without a restart.
    """
    if path is None:
        # Resolved from the project root, not relative to this file, so moving
        # the module between subpackages cannot silently break the data path.
        from seo_audit.appconfig import ROOT
        path = os.path.join(ROOT, "data", "authority_domains.yaml")
    path = os.path.abspath(path)

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}

    if _AUTH_CACHE["path"] == path and _AUTH_CACHE["mtime"] == mtime:
        return _AUTH_CACHE["map"]

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    mapping = {}
    for group, entries in raw.items():
        for e in entries or []:
            # entries may be full hosts (aws.amazon.com) or registered domains
            key = str(e).strip().lower()
            mapping.setdefault(key, group)
            reg = dom.registered_domain(key)
            if reg:
                mapping.setdefault(reg, group)

    _AUTH_CACHE.update(path=path, mtime=mtime, map=mapping)
    return mapping


def classify_domain(url: str, authority: dict | None = None) -> dict:
    """
    Assign a trust tier to a URL's domain.

    Returns:
      tier          "A" | "B" | "C" | "D"
      tier_label    human-readable tier name
      reason        why this tier
      suffix        public suffix
      registered    registered domain
      authority_group  which authority group matched (tier B only)
      spam_tld      bool
      free_subdomain bool
    """
    if authority is None:
        authority = load_authority_domains()

    host = dom.host_of(url)
    reg = dom.registered_domain(url)
    suf = dom.suffix(url)

    out = {
        "host": host,
        "registered": reg,
        "suffix": suf,
        "tier": "D",
        "tier_label": "Unproven",
        "reason": "",
        "authority_group": "",
        "spam_tld": suf in SPAM_TLDS,
        "free_subdomain": dom.is_free_subdomain(url),
        "is_subdomain": dom.is_real_subdomain(url),
    }

    # --- Tier A: institutional suffix ---------------------------------
    if suf in INSTITUTIONAL_SUFFIXES:
        kind = ("government" if any(k in suf for k in ("gov", "gob", "gouv", "go.", "gub", "gv", "mil", "police", "judiciary", "nhs", "muni", "bel", "lg."))
                else "education" if any(k in suf for k in ("edu", "ac.", "sch", "k12", "ed.", "school", "res.in", "nic.in", "sc.ke"))
                else "institutional")
        out.update(
            tier="A", tier_label=f"Institutional ({kind})",
            reason=f".{suf} is a restricted {kind} suffix - registration is verified, so this is a strong trust signal.",
        )
        return out

    # --- Tier B: curated authority list -------------------------------
    group = authority.get(host) or authority.get(reg)
    if group:
        out.update(
            tier="B", tier_label="High authority (curated)",
            authority_group=group,
            reason=f"{reg} is on the curated authority list (group: {group}).",
        )
        return out

    # --- Tier C: non-profit-flavoured suffix ---------------------------
    if suf in NONPROFIT_SUFFIXES:
        out.update(
            tier="C", tier_label="Non-profit TLD (weak signal)",
            reason=(f".{suf} suggests a non-profit, but registration is open to anyone "
                    f"and spam networks buy it in bulk - treat as unproven until DA/PA confirms."),
        )
        return out

    # --- Tier D: everything else --------------------------------------
    if out["spam_tld"]:
        out["reason"] = (f".{suf} is heavily used by link networks. Not automatically bad, "
                         f"but needs DA/PA or manual review before you trust it.")
    else:
        out["reason"] = f"No institutional or curated-authority signal for .{suf}. Judge on DA/PA and page quality."
    if out["free_subdomain"]:
        out["reason"] += (" Site sits on a free-subdomain / dynamic-DNS host, "
                          "so the linker does not own the domain.")
    return out
