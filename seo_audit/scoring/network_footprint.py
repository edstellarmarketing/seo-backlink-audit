"""
Link-network (PBN) footprint detection.

A private blog network is a set of sites built to look unrelated while being
run by one operator. Judged one row at a time they all look like ordinary
mediocre sites. Judged together, the footprint shows:

  * shared IP address          - forty "independent" sites on one box
  * shared /24 subnet          - same rack, different IPs
  * identical CMS fingerprint  - the same niche directory script everywhere
  * templated titles           - the same title pattern across domains

Any single signal can be innocent: shared hosting genuinely puts thousands of
unrelated sites on one IP, and WordPress is on half the web. So this module
deliberately does NOT judge on one signal. It reports clusters, requires a
minimum cluster size, and treats a cluster as suspicious only when more than
one signal lines up. Seeing 15 of your backlinks land in one cluster is the
insight -- it turns 15 separate "meh" rows into a single obvious decision.
"""

import re
from collections import defaultdict

from seo_audit.net import resolve as resolve_mod

_TITLE_NOISE = re.compile(r"[^a-z ]+")
_STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "best",
         "top", "home", "page", "site", "website", "online", "free", "com",
         "net", "org", "info", "www", "welcome"}


def _title_shape(title: str) -> str:
    """
    Reduce a title to a coarse shape so templated titles collide.
    'Blue Sparkle Directory.com' and 'Abstract Directory .net' both -> 'directory'
    """
    t = _TITLE_NOISE.sub(" ", (title or "").lower())
    words = [w for w in t.split() if w not in _STOP and len(w) > 2]
    return " ".join(sorted(set(words))[:3])


def _generator_shape(gen: str) -> str:
    """Strip version numbers: 'PHP Link Directory 5.3' -> 'php link directory'."""
    g = re.sub(r"[\d.]+", " ", (gen or "").lower())
    return " ".join(g.split())[:60]


def analyse(rows: list, cfg: dict) -> dict:
    """
    Annotate rows in place with footprint fields and return a cluster summary.

    Fields added to each row:
      network_id       cluster label, or ""
      network_size     how many audited domains share it
      network_signals  which signals matched
      network_note     plain-English explanation
    """
    ncfg = (cfg.get("network_footprint") or {})
    min_size = int(ncfg.get("min_cluster", 3))
    enabled = bool(ncfg.get("enabled", True))

    for r in rows:
        r.setdefault("network_id", "")
        r.setdefault("network_size", 0)
        r.setdefault("network_signals", "")
        r.setdefault("network_note", "")
    if not enabled or not rows:
        return {"clusters": [], "domains_in_clusters": 0}

    # one entry per DOMAIN, not per link, so ten links from one site do not
    # fake a cluster all by themselves
    by_domain = {}
    for r in rows:
        d = r.get("registered") or ""
        if d and d not in by_domain:
            by_domain[d] = r

    ip_groups = defaultdict(set)
    sub_groups = defaultdict(set)
    gen_groups = defaultdict(set)
    title_groups = defaultdict(set)
    host_groups = defaultdict(set)
    shared_ips = set()

    for d, r in by_domain.items():
        ip = (r.get("ip") or "").strip()
        if ip:
            ip_groups[ip].add(d)
            sub = resolve_mod.subnet24(ip)
            if sub:
                sub_groups[sub].add(d)
            # A shared host or CDN legitimately fronts thousands of unrelated
            # sites, so "same IP" there is not a footprint -- it is just
            # hosting. Remember which addresses those are and discount them.
            if r.get("shared_host"):
                shared_ips.add(ip)
        g = _generator_shape(r.get("generator", ""))
        if g:
            gen_groups[g].add(d)
        t = _title_shape(r.get("page_title", ""))
        if t:
            title_groups[t].add(d)
        # Hosting organisation, but only when it is NOT one of the big shared
        # providers -- "all on AWS" describes half the internet.
        org = (r.get("net_org") or r.get("net_name") or "").strip().lower()
        if org and not r.get("shared_host"):
            host_groups[org[:60]].add(d)

    def big(groups):
        return {k: v for k, v in groups.items() if len(v) >= min_size}

    ip_big, sub_big = big(ip_groups), big(sub_groups)
    gen_big, title_big = big(gen_groups), big(title_groups)
    host_big = big(host_groups)

    # Score each domain by how many footprint signals it shares with others.
    per_domain = defaultdict(list)
    for ip, ds in ip_big.items():
        if ip in shared_ips:
            continue                       # shared hosting, not a footprint
        for d in ds:
            per_domain[d].append(("same IP " + ip, ds))
    for org, ds in host_big.items():
        for d in ds:
            per_domain[d].append((f'same host "{org}"', ds))
    for sub, ds in sub_big.items():
        if any(set(ds) <= set(v) for k, v in ip_big.items() if k not in shared_ips):
            continue                       # already explained by the exact IP
        if all((by_domain.get(d) or {}).get("shared_host") for d in ds):
            continue                       # whole block is shared hosting
        for d in ds:
            per_domain[d].append(("same /24 " + sub, ds))
    for g, ds in gen_big.items():
        for d in ds:
            per_domain[d].append((f'same CMS "{g}"', ds))
    for t, ds in title_big.items():
        for d in ds:
            per_domain[d].append((f'templated title "{t}"', ds))

    clusters = []
    seen = set()
    for d, signals in per_domain.items():
        if len(signals) < 2:               # one signal alone proves nothing
            continue
        members = set()
        for _, ds in signals:
            members |= set(ds)
        key = tuple(sorted(members))
        if key in seen:
            continue
        seen.add(key)
        labels = sorted({lab for lab, _ in signals})
        clusters.append({"members": sorted(members), "signals": labels,
                         "size": len(members)})

    clusters.sort(key=lambda c: -c["size"])
    in_cluster = set()
    for i, c in enumerate(clusters, 1):
        cid = f"NET-{i}"
        for d in c["members"]:
            in_cluster.add(d)
        note = (f"{c['size']} audited domains share {len(c['signals'])} footprint "
                f"signals ({'; '.join(c['signals'])}). Looks like one operator, "
                f"not {c['size']} independent sites - judge the cluster as a whole.")
        for r in rows:
            if r.get("registered") in c["members"]:
                r["network_id"] = cid
                r["network_size"] = c["size"]
                r["network_signals"] = "; ".join(c["signals"])
                r["network_note"] = note

    return {
        "clusters": [{"id": f"NET-{i}", **c} for i, c in enumerate(clusters, 1)],
        "domains_in_clusters": len(in_cluster),
        "single_signal_groups": {
            "shared_ip": {k: sorted(v) for k, v in ip_big.items()},
            "shared_subnet": {k: sorted(v) for k, v in sub_big.items()},
            "shared_cms": {k: sorted(v) for k, v in gen_big.items()},
            "shared_host_org": {k: sorted(v) for k, v in host_big.items()},
        },
        "discounted_shared_ips": sorted(shared_ips),
    }
