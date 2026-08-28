"""
Compare two audit runs.

Every run on its own is a snapshot, which answers "what does my backlink
profile look like" but not the questions that actually drive ongoing work:

    which links died since last month?
    whose link got removed?
    what went nofollow?
    which domains turned toxic?
    did anything recover?
    what is new, and what vanished from my input?

All of it is already in the JSON each run writes. This compares two of them.

Deliberate choice: links are matched on URL, and DOMAINS are reported
separately, because a referring page moving to a new URL looks like one death
and one birth at the link level while the relationship is intact at the domain
level. You want both views.
"""

import csv
import json
import os
from collections import Counter

# Direction of travel, so we can say "got worse" rather than just "changed".
SEVERITY = {"GOOD": 0, "REVIEW": 1, "LOW_VALUE": 2, "BLOCKED": 3,
            "LINK_LOST": 4, "DEAD": 5, "TOXIC": 6}


def load_run(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("rows") or []
    return {
        "path": path,
        "meta": data.get("meta") or {},
        "summary": data.get("summary") or {},
        "by_url": {r.get("url"): r for r in rows if r.get("url")},
        "by_domain": _fold_domains(rows),
        "rows": rows,
    }


def _fold_domains(rows: list) -> dict:
    """Worst verdict per domain -- one bad page makes a domain worth attention."""
    out = {}
    for r in rows:
        d = r.get("registered")
        if not d:
            continue
        cur = out.get(d)
        if cur is None or SEVERITY.get(r.get("verdict"), 9) > SEVERITY.get(cur.get("verdict"), 9):
            out[d] = r
    return out


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def compare(old_path: str, new_path: str, score_delta: float = 10.0) -> dict:
    old, new = load_run(old_path), load_run(new_path)
    o, n = old["by_url"], new["by_url"]

    added = [n[u] for u in n.keys() - o.keys()]
    removed = [o[u] for u in o.keys() - n.keys()]
    common = o.keys() & n.keys()

    changes = {k: [] for k in (
        "died", "revived", "link_lost", "link_restored", "went_nofollow",
        "became_followed", "turned_toxic", "cleared", "score_up", "score_down",
        "verdict_worse", "verdict_better", "redirect_new")}

    ALIVE = ("GOOD", "REVIEW", "LOW_VALUE")
    for u in sorted(common):
        a, b = o[u], n[u]
        va, vb = a.get("verdict"), b.get("verdict")
        sa, sb = _num(a.get("score")) or 0, _num(b.get("score")) or 0
        entry = {
            "url": u, "domain": b.get("registered", ""),
            "was": va, "now": vb,
            "score_was": sa, "score_now": sb,
            "delta": round(sb - sa, 1),
            "da": b.get("da"),
            "detail": "",
        }

        if va in ALIVE and vb in ("DEAD",):
            changes["died"].append({**entry, "detail": b.get("error") or f"HTTP {b.get('status_code')}"})
        elif va == "DEAD" and vb in ALIVE:
            changes["revived"].append({**entry, "detail": "page is answering again"})

        # "Link removed" only counts while the page is still REACHABLE. A page
        # that 404'd obviously no longer carries the link, and reporting that
        # as both a death and a removal double-counts one event and inflates
        # the outreach list with pages nobody can restore a link on.
        page_reachable = vb in ALIVE or vb == "LINK_LOST"
        if not a.get("link_found") and b.get("link_found"):
            changes["link_restored"].append({**entry, "detail": f"anchor: {b.get('anchor_texts','')[:60]}"})
        elif (a.get("link_found") and not b.get("link_found")
              and b.get("target_checked") and page_reachable):
            changes["link_lost"].append({**entry, "detail": "page still loads, link is gone"})

        # Require POSITIVE evidence of a nofollow-style rel. Inferring it from
        # a missing is_followed field turns absent data into a fake finding.
        now_nofollowed = bool(b.get("is_nofollow") or b.get("is_sponsored")
                              or b.get("is_ugc"))
        was_nofollowed = bool(a.get("is_nofollow") or a.get("is_sponsored")
                              or a.get("is_ugc"))
        if b.get("link_found") and now_nofollowed and not was_nofollowed:
            changes["went_nofollow"].append({**entry,
                "detail": f'rel="{b.get("link_rel","") or "nofollow"}"'})
        elif b.get("link_found") and was_nofollowed and not now_nofollowed and b.get("is_followed"):
            changes["became_followed"].append({**entry, "detail": "rel attribute dropped"})

        if va != "TOXIC" and vb == "TOXIC":
            changes["turned_toxic"].append({**entry, "detail": (b.get("issues") or "")[:110]})
        elif va == "TOXIC" and vb != "TOXIC":
            changes["cleared"].append({**entry, "detail": "no longer shows spam signals"})

        if not a.get("redirect_hops") and b.get("redirect_hops"):
            changes["redirect_new"].append({**entry,
                "detail": f"now redirects to {b.get('final_url','')[:70]}"})

        ds = sb - sa
        if ds >= score_delta:
            changes["score_up"].append(entry)
        elif ds <= -score_delta:
            changes["score_down"].append(entry)

        sev_a, sev_b = SEVERITY.get(va, 9), SEVERITY.get(vb, 9)
        if sev_b > sev_a:
            changes["verdict_worse"].append(entry)
        elif sev_b < sev_a:
            changes["verdict_better"].append(entry)

    od, nd = old["by_domain"], new["by_domain"]
    domains = {
        "new": sorted(nd.keys() - od.keys()),
        "gone": sorted(od.keys() - nd.keys()),
        "count_was": len(od), "count_now": len(nd),
    }

    def verdict_counts(run):
        return Counter(r.get("verdict") for r in run["rows"])

    return {
        "old": {"path": os.path.basename(old_path), "when": old["meta"].get("when", ""),
                "links": len(o), "verdicts": dict(verdict_counts(old)),
                "avg_score": old["summary"].get("avg_score")},
        "new": {"path": os.path.basename(new_path), "when": new["meta"].get("when", ""),
                "links": len(n), "verdicts": dict(verdict_counts(new)),
                "avg_score": new["summary"].get("avg_score")},
        "added": added, "removed": removed,
        "changes": changes, "domains": domains,
        "n_changed": sum(len(v) for v in changes.values()),
    }


# ---------------------------------------------------------------------------
# What deserves attention first, and why.
HEADLINES = [
    ("died", "Links that died", "critical"),
    ("link_lost", "Your link was removed", "critical"),
    ("turned_toxic", "Turned toxic", "critical"),
    ("went_nofollow", "Went nofollow", "warn"),
    ("score_down", "Score dropped", "warn"),
    ("verdict_worse", "Verdict got worse", "warn"),
    ("redirect_new", "Newly redirecting", "warn"),
    ("revived", "Came back to life", "good"),
    ("link_restored", "Link restored", "good"),
    ("became_followed", "Became followed", "good"),
    ("cleared", "No longer toxic", "good"),
    ("score_up", "Score improved", "good"),
    ("verdict_better", "Verdict improved", "good"),
]


def write_csv(d: dict, path: str) -> int:
    rows = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Change", "Priority", "URL", "Domain", "Was", "Now",
                    "Score was", "Score now", "Delta", "DA", "Detail"])
        for key, label, pri in HEADLINES:
            for e in d["changes"][key]:
                w.writerow([label, pri, e["url"], e["domain"], e["was"], e["now"],
                            e["score_was"], e["score_now"], e["delta"],
                            e.get("da") or "", e["detail"]])
                rows += 1
        for r in d["added"]:
            w.writerow(["New in this run", "info", r.get("url", ""), r.get("registered", ""),
                        "", r.get("verdict", ""), "", r.get("score", ""), "",
                        r.get("da") or "", "not present in the earlier run"])
            rows += 1
        for r in d["removed"]:
            w.writerow(["Dropped from input", "info", r.get("url", ""), r.get("registered", ""),
                        r.get("verdict", ""), "", r.get("score", ""), "", "",
                        r.get("da") or "", "was audited before, absent from this input"])
            rows += 1
    return rows


def console_summary(d: dict) -> str:
    L = []
    o, n = d["old"], d["new"]
    L.append(f"  was : {o['path']}  {o['when']}  {o['links']} links  avg {o['avg_score']}")
    L.append(f"  now : {n['path']}  {n['when']}  {n['links']} links  avg {n['avg_score']}")
    L.append("  " + "-" * 66)
    any_change = False
    for key, label, pri in HEADLINES:
        c = len(d["changes"][key])
        if c:
            any_change = True
            mark = {"critical": "!!", "warn": " !", "good": " +"}[pri]
            L.append(f"  {mark} {label:26} {c:>4}")
    if d["added"]:
        L.append(f"     {'New in this run':26} {len(d['added']):>4}")
    if d["removed"]:
        L.append(f"     {'Dropped from input':26} {len(d['removed']):>4}")
    if d["domains"]["new"]:
        L.append(f"     {'New referring domains':26} {len(d['domains']['new']):>4}")
    if d["domains"]["gone"]:
        L.append(f"     {'Domains no longer present':26} {len(d['domains']['gone']):>4}")
    if not any_change and not d["added"] and not d["removed"]:
        L.append("     nothing changed between these two runs")
    return "\n".join(L)
