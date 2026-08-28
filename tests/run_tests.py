"""
End-to-end verification of the audit pipeline.

Starts the local fixture server, audits every fixture page, and asserts the
verdicts, HTTP statuses, gate decisions and report writers are what they
should be. No internet required -- everything is served locally, which is a
stricter test of the logic than hitting real sites.

    python tests/run_tests.py

Exits non-zero if anything regressed. Run it after editing any rule.
"""

import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import yaml                                                        # noqa: E402

from seo_audit import pipeline as audit_mod                         # noqa: E402
from seo_audit.analysis import classify, homepage as homepage_mod   # noqa: E402
from seo_audit.analysis import archive as archive_mod               # noqa: E402
from seo_audit.analysis import domains as dom                      # noqa: E402
from seo_audit.analysis import page as page_mod                     # noqa: E402
from seo_audit.analysis import relevance as relevance_mod           # noqa: E402
from seo_audit.analysis import sitewide as sitewide_mod             # noqa: E402
from seo_audit.analysis import spamrules as spamrules_mod           # noqa: E402
from seo_audit.net import fetch, render as render_mod, resolve as resolve_mod  # noqa: E402
from seo_audit.net.robots import RobotsCache                        # noqa: E402
from seo_audit.providers import asn as asn_mod, metrics as metrics_mod  # noqa: E402
from seo_audit.reporting import disavow_diff as disavow_mod         # noqa: E402
from seo_audit.reporting import report as report_mod                # noqa: E402
from seo_audit.reporting import rundiff as rundiff_mod              # noqa: E402
from seo_audit.scoring import anchors as anchors_mod                # noqa: E402
from seo_audit.scoring import gate as gate_mod                      # noqa: E402
from seo_audit.scoring import network_footprint as netfp            # noqa: E402
from seo_audit.scoring import score as score_mod                    # noqa: E402
from seo_audit.store import database as db_mod                       # noqa: E402
from seo_audit.store import resultcache as rc_mod                   # noqa: E402
from fixture_server import make_server                              # noqa: E402

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
TARGET = "edstellar.com"

# Every fixture is served from 127.0.0.1, which has no TLD and therefore lands
# in trust tier D. To keep the SCORE meaningful we inject one controlled DA for
# all fixtures, so any difference between rows comes from the on-page signals
# being tested -- not from the domain.
INJECT_DA = 92
INJECT_SS = 2

# path, expected verdict, expected http status, expect link found
CASES = [
    ("/good",      "GOOD",      200, True),
    ("/nofollow",  "REVIEW",    200, True),
    ("/sponsored", "REVIEW",    200, True),
    ("/removed",   "LINK_LOST", 200, False),
    ("/noindex",   "REVIEW",    200, True),
    ("/casino",    "TOXIC",     200, True),
    ("/parked",    "TOXIC",     200, False),
    ("/linkfarm",  "TOXIC",     200, True),
    ("/thin",      "REVIEW",    200, True),
    ("/hidden",    "TOXIC",     200, True),
    ("/404",       "DEAD",      404, False),
    ("/410",       "DEAD",      410, False),
    ("/403",       "BLOCKED",   403, False),
    ("/500",       "BLOCKED",   500, False),
    ("/redirect",  "REVIEW",    301, True),
    ("/chain1",    "REVIEW",    301, True),
    ("/blocked",   None,        200, True),
    ("/sitewide",  None,        200, True),
    ("/jslink",    None,        200, False),   # link only exists after JS runs
]

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append(f"{label}: expected {want!r}, got {got!r}")
    return ok


def main():
    srv = make_server(PORT)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.6)

    cfg = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))
    cfg["target_site"] = TARGET
    cfg["target_aliases"] = ["www.edstellar.com"]
    cfg.setdefault("network", {})
    cfg["network"]["delay_per_host"] = 0        # local server, no politeness needed
    cfg["network"]["concurrency"] = 4
    cfg["network"]["timeout"] = 10
    # The fixture server speaks plain HTTP on 127.0.0.1, so every row would
    # otherwise take the non-HTTPS penalty -- an artifact of the test rig, not
    # of the page being tested. Zero it so the assertions measure the signals
    # we actually care about.
    cfg["scoring"]["penalties"]["non_https"] = 0

    session = fetch.make_session(cfg)
    session.trust_env = False                  # bypass the sandbox proxy for 127.0.0.1
    throttle = fetch.HostThrottle(0)
    robots = RobotsCache(session, cfg)
    dns = resolve_mod.DnsCache(3)
    homecache = homepage_mod.HomepageCache(session, cfg, throttle, dns)
    authority = classify.load_authority_domains()

    print("=" * 78)
    print("  PIPELINE VERIFICATION")
    print("=" * 78)
    print(f"  {'fixture':12} {'HTTP':>5} {'verdict':11} {'score':>5}  {'link':6} {'follow':7} issues")
    print("  " + "-" * 74)

    rows = []
    for path, want_verdict, want_status, want_link in CASES:
        item = {"url": BASE + path, "target": TARGET, "anchor": "", "notes": ""}
        row = audit_mod.audit_one(item, session, cfg, throttle, robots, authority,
                                  True, homecache, dns)
        row["da"], row["pa"], row["spam_score"] = INJECT_DA, 70, INJECT_SS
        row["backlinks"] = row["referring_domains"] = None
        row["metrics_source"] = "test-injected"
        row.update(score_mod.score_row(row, cfg))
        rows.append(row)

        got_status = row.get("status_code")
        got_verdict = row.get("verdict")
        got_link = bool(row.get("link_found"))

        check(f"{path} status", got_status, want_status)
        if want_verdict is not None:
            check(f"{path} verdict", got_verdict, want_verdict)
        if path not in ("/redirect", "/chain1"):
            check(f"{path} link_found", got_link, want_link)

        print(f"  {path:12} {str(got_status):>5} {got_verdict:11} {row['score']:>5}  "
              f"{'yes' if got_link else 'no':6} "
              f"{'yes' if row.get('is_followed') else 'no':7} {row['issues'][:60]}")

    print("  " + "-" * 74)

    # ---- targeted flag assertions ------------------------------------
    by = {r["url"].replace(BASE, ""): r for r in rows}
    print("\n  Flag assertions:")

    def flag(label, cond):
        ok = bool(cond)
        if not ok:
            FAILS.append(f"flag {label}")
        print(f"    [{'PASS' if ok else 'FAIL'}] {label}")

    flag("/good link is followed",            by["/good"]["is_followed"])
    flag("/good link is in-content",          by["/good"]["link_placement"] == "in-content")
    flag("/sitewide link is boilerplate",     by["/sitewide"]["link_placement"] == "boilerplate")
    flag("/sitewide flagged sitewide",        by["/sitewide"]["link_is_sitewide"] is True)
    flag("/good outscores /sitewide",         by["/good"]["score"] > by["/sitewide"]["score"])
    flag("/good is relevant (>0%)",           by["/good"]["relevance_score"] > 0)
    flag("/nofollow detects rel=nofollow",    by["/nofollow"]["is_nofollow"])
    flag("/nofollow NOT followed",            not by["/nofollow"]["is_followed"])
    flag("/nofollow is not TOXIC",            by["/nofollow"]["verdict"] != "TOXIC")
    flag("/sponsored detects rel=sponsored",  by["/sponsored"]["is_sponsored"])
    flag("/sponsored finds paid markers",     by["/sponsored"]["paid_link_markers"])
    flag("/noindex detects noindex",          by["/noindex"]["is_noindex"])
    flag("/noindex not disavow-listed",       by["/noindex"]["verdict"] != "TOXIC")
    flag("/casino content flagged spam",      by["/casino"]["content_spam"])
    flag("/casino category = gambling",       "gambling" in by["/casino"]["content_spam_categories"])
    flag("/parked markers found",             by["/parked"]["parked_markers"])
    flag("/linkfarm >300 outbound links",     by["/linkfarm"]["outbound_links"] >= 300)
    flag("/linkfarm directory markers",       by["/linkfarm"]["link_directory_markers"])
    flag("/thin flagged thin content",        "thin content" in by["/thin"]["issues"])
    flag("/hidden detects hidden link block", by["/hidden"]["link_in_hidden_block"])
    flag("/redirect verdict is REDIRECT_PERM", by["/redirect"]["status_verdict"] == "REDIRECT_PERM")
    flag("/redirect final lands on /good",    by["/redirect"]["final_url"].endswith("/good"))
    flag("/chain1 has 3 hops",                by["/chain1"]["redirect_hops"] == 3)
    flag("/chain1 penalised for long chain",  "long redirect chain" in by["/chain1"]["issues"])
    flag("/500 is SERVER_ERROR not DEAD",     by["/500"]["status_verdict"] == "SERVER_ERROR")
    flag("/403 is BLOCKED not DEAD",          by["/403"]["verdict"] == "BLOCKED")
    flag("/removed says link is gone",        "LINK IS GONE" in by["/removed"]["issues"])
    flag("/blocked is robots.txt-disallowed", by["/blocked"]["robots_blocked"] is True)
    flag("/good is robots.txt-allowed",       by["/good"]["robots_blocked"] is False)
    flag("no robots errors swallowed",        not any(r.get("robots_error") for r in rows))
    flag("/good outscores /casino",           by["/good"]["score"] > by["/casino"]["score"])
    flag("/good outscores /nofollow",         by["/good"]["score"] > by["/nofollow"]["score"])
    flag("/good outscores /noindex",          by["/good"]["score"] > by["/noindex"]["score"])
    flag("/good outscores /linkfarm",         by["/good"]["score"] > by["/linkfarm"]["score"])

    # ---- staged gating -----------------------------------------------
    print("\n  Staged gating (stage 4 = DA/PA worth buying):")

    def gcase(label, row, want_pass, want_stage):
        g = gate_mod.evaluate(row, cfg)
        ok = (g["gate_passed"] == want_pass and g["gate_stage"] == want_stage)
        if not ok:
            FAILS.append(f"gate {label}: got pass={g['gate_passed']} "
                         f"stage={g['gate_stage']}, wanted pass={want_pass} stage={want_stage}")
        print(f"    [{'PASS' if ok else 'FAIL'}] {label} -> {g['gate_stage']}")

    gcase("404 stops at stage 1", {"status_verdict": "DEAD", "status_code": 404},
          False, gate_mod.STAGE_LIVE)
    gcase("DNS failure stops at stage 1", {"status_verdict": "DNS_ERROR"},
          False, gate_mod.STAGE_LIVE)
    gcase("broken TLS stops at stage 1", {"status_verdict": "SSL_ERROR"},
          False, gate_mod.STAGE_LIVE)
    gcase("casino page stops at stage 2",
          {"status_verdict": "LIVE", "tier": "D", "content_spam": True,
           "content_spam_categories": "gambling / betting"}, False, gate_mod.STAGE_PAGE)
    gcase("parked page stops at stage 2",
          {"status_verdict": "LIVE", "tier": "D",
           "parked_markers": "this domain is for sale"}, False, gate_mod.STAGE_PAGE)
    gcase("link farm stops at stage 2",
          {"status_verdict": "LIVE", "tier": "D", "outbound_links": 400},
          False, gate_mod.STAGE_PAGE)
    gcase("link directory (190 outbound) stops at stage 2",
          {"status_verdict": "LIVE", "tier": "D", "outbound_links": 190,
           "link_directory_markers": "submit link, top hits"}, False, gate_mod.STAGE_PAGE)
    gcase("noindex stops at stage 2",
          {"status_verdict": "LIVE", "tier": "D", "is_noindex": True},
          False, gate_mod.STAGE_PAGE)
    gcase("clean page + SPAM HOMEPAGE stops at stage 3",
          {"status_verdict": "LIVE", "tier": "D", "outbound_links": 20,
           "home_checked": True, "home_content_spam": True,
           "home_content_spam_categories": "gambling / betting"},
          False, gate_mod.STAGE_HOME)
    gcase("clean page + parked HOMEPAGE stops at stage 3",
          {"status_verdict": "LIVE", "tier": "D", "outbound_links": 20,
           "home_checked": True, "home_parked_markers": "buy this domain"},
          False, gate_mod.STAGE_HOME)
    gcase("authority site mentioning gambling reaches stage 4",
          {"status_verdict": "LIVE", "tier": "B", "content_spam": True,
           "content_spam_categories": "gambling", "outbound_links": 50,
           "home_checked": True}, True, gate_mod.STAGE_METRICS)
    gcase("fully clean reaches stage 4",
          {"status_verdict": "LIVE", "tier": "D", "outbound_links": 20,
           "home_checked": True}, True, gate_mod.STAGE_METRICS)

    dead_rows = [r for r in rows if r["verdict"] == "DEAD"]
    flag("dead links never reach stage 4",
         all(not r.get("gate_passed") for r in dead_rows))
    flag("dead links are not queued for DA/PA",
         all(not r.get("needs_metrics") for r in dead_rows))
    flag("homepage stage ran on live pages",
         any(r.get("home_checked") for r in rows if r["status_verdict"] == "LIVE"))

    # A spammy homepage must drag the score down even when the page is clean.
    clean_page = {"status_verdict": "LIVE", "tier": "D", "https": True,
                  "target_checked": True, "link_found": True, "is_followed": True,
                  "word_count": 800, "outbound_links": 20, "da": 40,
                  "home_checked": True, "home_same_as_page": False}
    spam_home = dict(clean_page, home_content_spam=True,
                     home_content_spam_categories="gambling / betting")
    a = score_mod.score_row(dict(clean_page), cfg)
    b = score_mod.score_row(dict(spam_home), cfg)
    flag(f"spam homepage lowers score ({a['score']} -> {b['score']})", b["score"] < a["score"])
    flag("spam homepage forces TOXIC", b["verdict"] == "TOXIC")

    # ---- disavow safety ----------------------------------------------
    tmp = tempfile.mkdtemp()
    dpath = os.path.join(tmp, "disavow.txt")
    n = report_mod.write_disavow(rows, dpath)
    body = open(dpath, encoding="utf-8").read()
    nofollow_dom = by["/nofollow"]["registered"]
    print("\n  Disavow safety:")
    flag(f"disavow.txt is non-empty ({n} entries)", n > 0)
    # All fixtures share the 127.0.0.1 "domain", so a domain-level check on the
    # live rows proves nothing. Assert on the writer's filter with synthetic rows:
    fake = [
        {"verdict": "TOXIC", "registered": "spam-site.xyz", "free_subdomain": False},
        {"verdict": "LOW_VALUE", "registered": "harmless.org", "free_subdomain": False},
        {"verdict": "LINK_LOST", "registered": "lostlink.com", "free_subdomain": False},
        {"verdict": "DEAD", "registered": "dead.org", "free_subdomain": False},
        {"verdict": "TOXIC", "registered": "zapto.org", "free_subdomain": True,
         "host": "spammer1.zapto.org", "url": "http://spammer1.zapto.org/"},
    ]
    f2 = os.path.join(tmp, "d2.txt")
    report_mod.write_disavow(fake, f2)
    b2 = open(f2, encoding="utf-8").read()
    flag("TOXIC domain IS disavowed",          "domain:spam-site.xyz" in b2)
    flag("LOW_VALUE domain NOT disavowed",     "domain:harmless.org" not in b2)
    flag("LINK_LOST domain NOT disavowed",     "domain:lostlink.com" not in b2)
    flag("DEAD domain NOT disavowed",          "domain:dead.org" not in b2)
    flag("free-subdomain disavows exact host", "domain:spammer1.zapto.org" in b2)
    flag("free-subdomain does NOT blanket provider", "domain:zapto.org\n" not in b2)

    # ---- new: placement, language, DNS, networks, anchors, resume -----
    print("\n  Link placement:")
    T = "https://www.edstellar.com/x"
    pcfg = {"content": {"expected_languages": ["en"], "relevance_keywords": ["training"]}}

    def placement_of(body, lang="en"):
        html = f'<html lang="{lang}"><body>{body}</body></html>'
        return page_mod.analyze(html, "https://blog.test.org/p", "edstellar.com",
                                ["www.edstellar.com"], pcfg)

    flag("in <article> -> in-content",
         placement_of(f'<article><p><a href="{T}">E</a></p></article>')["link_placement"] == "in-content")
    flag("in <footer> -> boilerplate",
         placement_of(f'<footer><a href="{T}">E</a></footer>')["link_placement"] == "boilerplate")
    flag("class=sidebar -> boilerplate",
         placement_of(f'<div class="sidebar"><a href="{T}">E</a></div>')["link_placement"] == "boilerplate")
    flag("id=blogroll -> boilerplate",
         placement_of(f'<ul id="blogroll"><a href="{T}">E</a></ul>')["link_placement"] == "boilerplate")
    flag("entry-content -> in-content",
         placement_of(f'<div class="entry-content"><a href="{T}">E</a></div>')["link_placement"] == "in-content")
    flag("footer link marked sitewide",
         placement_of(f'<footer><a href="{T}">E</a></footer>')["link_is_sitewide"] is True)
    flag("sitewide link scores below in-content", (
        score_mod.score_row({"status_verdict": "LIVE", "tier": "D", "https": True,
                             "target_checked": True, "link_found": True, "is_followed": True,
                             "word_count": 800, "outbound_links": 20, "da": 50,
                             "link_placement": "boilerplate", "link_is_sitewide": True}, cfg)["score"]
        < score_mod.score_row({"status_verdict": "LIVE", "tier": "D", "https": True,
                               "target_checked": True, "link_found": True, "is_followed": True,
                               "word_count": 800, "outbound_links": 20, "da": 50,
                               "link_placement": "in-content"}, cfg)["score"]))

    print("\n  Language mismatch:")
    flag("lang=id flagged against expected en",
         placement_of(f'<article><a href="{T}">E</a></article>', lang="id")["lang_mismatch"] is True)
    flag("lang=en not flagged",
         placement_of(f'<article><a href="{T}">E</a></article>', lang="en")["lang_mismatch"] is False)
    flag("lang=en-GB not flagged (primary subtag)",
         placement_of(f'<article><a href="{T}">E</a></article>', lang="en-GB")["lang_mismatch"] is False)

    print("\n  DNS pre-check:")
    dcache = resolve_mod.DnsCache(3)
    r_bad = dcache.resolve("this-domain-does-not-exist-zz9.invalid")
    flag("NXDOMAIN detected", r_bad["resolved"] is False and "NXDOMAIN" in r_bad["dns_error"])
    import time as _t
    _t0 = _t.time()
    dcache.resolve("this-domain-does-not-exist-zz9.invalid")
    flag(f"second lookup is cached ({(_t.time()-_t0)*1000:.2f}ms)", (_t.time() - _t0) < 0.05)
    flag("subnet24 works", resolve_mod.subnet24("203.0.113.42") == "203.0.113.0/24")
    flag("subnet24 ignores IPv6", resolve_mod.subnet24("2606:4700::1") == "")

    print("\n  Fetch ladder:")
    ladder = fetch._ladder("https://x.test/p", True)
    flag("https tried first", ladder[0][2] == "https")
    flag("relaxed TLS tried second", ladder[1][2] == "https-noverify" and ladder[1][1] is False)
    flag("plain http tried last", ladder[2][2] == "http")
    flag("http URL keeps http first", fetch._ladder("http://x.test/p", True)[0][2] == "http")
    flag("SSL error is not called DEAD",
         score_mod.score_row({"status_verdict": "SSL_ERROR", "tier": "D",
                              "error": "SSL certificate error"}, cfg)["verdict"] == "BLOCKED")
    flag("DNS error IS called DEAD",
         score_mod.score_row({"status_verdict": "DNS_ERROR", "tier": "D"}, cfg)["verdict"] == "DEAD")

    print("\n  Link-network footprint:")
    fake_net = [
        dict(registered="a-dir.com", ip="10.9.9.9", generator="PHP Link Directory 5.3",
             page_title="A Directory .com"),
        dict(registered="b-dir.net", ip="10.9.9.9", generator="PHP Link Directory 5.2",
             page_title="B Directory .net"),
        dict(registered="c-dir.org", ip="10.9.9.9", generator="PHP Link Directory 5.3",
             page_title="C Directory .org"),
        dict(registered="genuine.de", ip="93.1.2.3", generator="WordPress 6.9",
             page_title="Echte Nachrichten und Tipps"),
    ]
    nsum = netfp.analyse(fake_net, cfg)
    flag("cluster of 3 detected", len(nsum["clusters"]) == 1 and nsum["clusters"][0]["size"] == 3)
    flag("genuine site left out of cluster",
         next(r for r in fake_net if r["registered"] == "genuine.de")["network_id"] == "")
    # Negative case: these four share ONE signal only (the CMS). They sit in
    # different /24s and their titles reduce to different shapes, so a single
    # shared signal must NOT be enough to call them a network -- half the web
    # runs WordPress.
    one_signal = [
        dict(registered="alpha.com", ip="5.5.1.1", generator="WordPress 6.9",
             page_title="Alpha Bakery Bristol"),
        dict(registered="beta.de", ip="6.6.2.2", generator="WordPress 6.9",
             page_title="Reisen Wandern Alpen"),
        dict(registered="gamma.org", ip="7.7.3.3", generator="WordPress 6.9",
             page_title="Community Garden Volunteers"),
        dict(registered="delta.net", ip="8.8.4.4", generator="WordPress 6.9",
             page_title="Vintage Motorcycle Restoration"),
    ]
    flag("one shared signal is NOT a network",
         len(netfp.analyse(one_signal, cfg)["clusters"]) == 0)
    flag("shared CMS alone leaves rows unflagged",
         all(r["network_id"] == "" for r in one_signal))
    flag("network membership costs score", (
        score_mod.score_row({"status_verdict": "LIVE", "tier": "D", "https": True,
                             "word_count": 800, "outbound_links": 20, "da": 50,
                             "network_id": "NET-1", "network_size": 6,
                             "network_signals": "same IP"}, cfg)["score"]
        < score_mod.score_row({"status_verdict": "LIVE", "tier": "D", "https": True,
                               "word_count": 800, "outbound_links": 20, "da": 50}, cfg)["score"]))

    print("\n  Anchor-text analysis:")
    arows = [dict(link_found=True, is_followed=True, anchor_texts="corporate training company")
             for _ in range(4)]
    arows += [dict(link_found=True, is_followed=True, anchor_texts="Edstellar"),
              dict(link_found=True, is_followed=True, anchor_texts="www.edstellar.com"),
              dict(link_found=False, anchor_texts="should be ignored")]
    arep = anchors_mod.analyse(arows, cfg)
    flag("ignores links that were not found", arep["total_anchors"] == 6)
    flag("over-optimisation warned",
         any("of all anchors" in w for w in arep["warnings"]))
    flag("branded anchor classified",
         anchors_mod.classify_anchor("Edstellar", ["edstellar"]) == "branded")
    flag("keyword anchor classified",
         anchors_mod.classify_anchor("best corporate training", ["edstellar"]) == "keyword")
    flag("generic anchor classified",
         anchors_mod.classify_anchor("click here", ["edstellar"]) == "generic")
    flag("empty anchor classified",
         anchors_mod.classify_anchor("[image/empty anchor]", ["edstellar"]) == "image-empty")

    print("\n  Resume cache:")
    rc_path = os.path.join(tempfile.mkdtemp(), "rc.json")
    rc = rc_mod.ResultCache(rc_path, 24)
    rc.put("https://x.test/1", {"url": "https://x.test/1", "score": 77}, autosave_every=1)
    flag("row stored", len(rc) == 1)
    rc2 = rc_mod.ResultCache(rc_path, 24)
    got = rc2.get("https://x.test/1")
    flag("row reloaded from disk", got is not None and got["score"] == 77)
    flag("reloaded row marked from_cache", bool(got and got.get("from_cache")))
    # Backdate the record rather than racing the wall clock: with a tiny TTL the
    # whole test can run inside it, which made this check flaky.
    rc4 = rc_mod.ResultCache(rc_path, 1.0)
    rc4.data["https://x.test/1"]["_cached_at"] = time.time() - 7200   # 2h old
    flag("row older than the TTL is ignored", rc4.get("https://x.test/1") is None)
    flag("row inside the TTL is returned", rc_mod.ResultCache(rc_path, 24).get(
        "https://x.test/1") is not None)
    flag("resume_hours=0 means do not reuse",
         rc_mod.ResultCache(rc_path, 0).get("https://x.test/1") is None)
    rc2.clear()
    flag("clear() empties the cache", len(rc2) == 0 and not os.path.exists(rc_path))

    # ================= new capability checks =================
    print("\n  Adaptive rate-limit backoff:")
    th = fetch.HostThrottle(delay=0.0, max_delay=8.0)
    U = "https://slow.test/x"
    flag("starts at the configured delay", th._delay_for("slow.test") == 0.0)
    th.note_response(U, 429)
    d1 = th._delay_for("slow.test")
    flag(f"429 widens the delay ({d1}s)", d1 > 0)
    th.note_response(U, 429)
    flag("a second 429 widens it further", th._delay_for("slow.test") > d1)
    th.note_response(U, 503, retry_after="6")
    flag("Retry-After is honoured", th._delay_for("slow.test") >= 6)
    for _ in range(8):
        th.note_response(U, 200)
    flag("clean responses let it decay", th._delay_for("slow.test") < 8)
    flag("other hosts are unaffected", th._delay_for("fine.test") == 0.0)
    th2 = fetch.HostThrottle(delay=1.0, max_delay=4.0)
    for _ in range(9):
        th2.note_response("https://a.test/", 429)
    flag("ceiling is respected", th2._delay_for("a.test") == 4.0)

    print("\n  Spam rules - non-English verticals:")
    for label, text, want in [
        ("Indonesian slots", "Situs slot gacor maxwin bonus new member", True),
        ("Thai casino", "\u0e2a\u0e25\u0e47\u0e2d\u0e15 \u0e1a\u0e32\u0e04\u0e32\u0e23\u0e48\u0e32 online", True),
        ("Russian casino", "\u041b\u0443\u0447\u0448\u0435\u0435 \u043a\u0430\u0437\u0438\u043d\u043e \u043e\u043d\u043b\u0430\u0439\u043d", True),
        ("Korean toto", "\uc628\ub77c\uc778\uce74\uc9c0\ub178 \ud1a0\ud1a0\uc0ac\uc774\ud2b8", True),
        ("Turkish bahis", "Guvenilir bahis siteleri ve deneme bonusu", True),
        ("Indonesian piracy", "Nonton film gratis di indoxxi", True),
        ("clean English", "Corporate training in Essex. Results are better than before.", False),
        ("clean German", "Reisen, Wandern und Kochen Tipps fuer die Familie.", False),
        ("SEO article naming blackhat once",
         "Never buy backlinks from a link-farm; it is against Google policy.", False),
    ]:
        got = spamrules_mod.scan_content(text)["spammy"]
        flag(f"{label} -> spammy={want}", got == want)
    flag("word boundaries still hold (Essex/better)",
         spamrules_mod.scan_content("Essex county, better results, Sussex.")["total"] == 0)
    flag("blackhat terms are NOT single-hit",
         "linkfarm" not in spamrules_mod.UNAMBIGUOUS)
    flag("locale gambling terms ARE single-hit",
         "gacor" in spamrules_mod.UNAMBIGUOUS and "\u043a\u0430\u0437\u0438\u043d\u043e" in spamrules_mod.UNAMBIGUOUS)

    print("\n  Relevance - stemming and synonyms:")
    KW = ["corporate training", "employee", "upskilling", "workshop"]
    SYN = {"corporate training": ["staff development"], "employee": ["personnel"],
           "upskilling": ["reskilling"], "workshop": ["seminar"]}
    r_syn = relevance_mod.score({"title": "Staff Development Programmes", "h1": "",
                                 "meta": "", "anchor": "", "body": ""}, KW, SYN)
    flag(f"synonym in title scores ({r_syn['score']}%, was 0)", r_syn["score"] > 0)
    r_none = relevance_mod.score({"title": "Vintage Motorcycle Restoration", "h1": "",
                                  "meta": "", "anchor": "", "body": "engines"}, KW, SYN)
    flag("unrelated page still scores 0", r_none["score"] == 0)
    r_title = relevance_mod.score({"title": "Employee training", "h1": "", "meta": "",
                                   "anchor": "", "body": ""}, KW, SYN)
    r_body = relevance_mod.score({"title": "", "h1": "", "meta": "", "anchor": "",
                                  "body": "employee training"}, KW, SYN)
    flag("title outweighs body", r_title["score"] > r_body["score"])
    for a, b in [("organisation", "organization"), ("programme", "program"),
                 ("centre", "center"), ("staff", "employees"),
                 ("leader", "leaders"), ("manager", "managers")]:
        flag(f"stem({a}) == stem({b})", relevance_mod.stem(a) == relevance_mod.stem(b))
    flag("no over-stemming of 'organization'",
         relevance_mod.stem("organization") == "organization")
    flag("no over-stemming of 'center'", relevance_mod.stem("center") == "center")

    print("\n  Hosting-aware PBN clustering:")
    shared = [dict(registered=f"x{i}.com", ip="104.21.0.5", shared_host=True,
                   net_org="Cloudflare, Inc.", generator="WordPress 6.9",
                   page_title=t)
              for i, t in enumerate(["Artisan Sourdough Bakery Bristol",
                                     "Wandern in den Alpen Reiseberichte",
                                     "Community Garden Volunteers",
                                     "Vintage Motorcycle Restoration"])]
    flag("unrelated sites behind a CDN do NOT cluster",
         len(netfp.analyse(shared, cfg)["clusters"]) == 0)
    small = [dict(registered=f"y{i}.com", ip="45.9.9.9", shared_host=False,
                  net_org="Tiny VPS Ltd", generator="PHP Link Directory 5.3",
                  page_title=f"Directory {i}") for i in range(4)]
    flag("same small host DOES cluster",
         len(netfp.analyse(small, cfg)["clusters"]) == 1)
    flag("shared IPs are recorded as discounted",
         netfp.analyse(shared, cfg)["discounted_shared_ips"] == ["104.21.0.5"])
    flag("shared-host classifier knows the big providers",
         bool(asn_mod.SHARED_HOSTING_HINTS.search("CLOUDFLARENET"))
         and not asn_mod.SHARED_HOSTING_HINTS.search("Bob Small VPS Ltd"))

    print("\n  Optional network lookups degrade safely:")
    ac = asn_mod.AsnCache(os.path.join(tempfile.mkdtemp(), "a.json"), enabled=False)
    flag("ASN disabled returns empty, does not raise",
         ac.lookup("8.8.8.8") == dict(asn_mod.AsnCache.EMPTY))
    flag("ASN skips IPv6", ac.lookup("2606:4700::1")["net_org"] == "")
    arc = archive_mod.ArchiveCache(os.path.join(tempfile.mkdtemp(), "b.json"), enabled=False)
    flag("archive disabled returns empty, does not raise",
         arc.recover("https://x.test/p", None, cfg, "edstellar.com", [])["archive_available"] is False)

    print("\n  Sitewide sampling:")
    flag("skipped when the link was not found",
         sitewide_mod.sample(None, cfg, None, {"link_found": False},
                             "edstellar.com", [], 3)["sitewide_checked"] is False)
    flag("skipped when sample size is 0",
         sitewide_mod.sample(None, cfg, None,
                             {"link_found": True, "internal_urls": ["x"]},
                             "edstellar.com", [], 0)["sitewide_checked"] is False)
    flag("page analysis exposes internal URLs for sampling",
         isinstance(by["/good"].get("internal_urls"), list))

    print("\n  JS rendering fallback:")
    ok_r, why_r = render_mod.available()
    flag(f"availability is reported ({'present' if ok_r else 'absent'})",
         isinstance(ok_r, bool) and (ok_r or "Playwright" in why_r))
    flag("empty batch is a no-op", render_mod.render_many([], cfg) == {})
    flag("/jslink has no link in raw HTML (the false LINK_LOST)",
         by["/jslink"]["link_found"] is False)
    flag("/jslink is flagged for a browser re-check",
         by["/jslink"].get("needs_render") is True)
    if ok_r:
        got = render_mod.render_many([BASE + "/jslink"], cfg, 700)
        html_r, err_r = got[BASE + "/jslink"]
        a_r = page_mod.analyze(html_r, BASE + "/jslink", TARGET,
                               ["www.edstellar.com"], cfg) if html_r else {}
        flag("browser re-check FINDS the JS-injected link",
             bool(a_r.get("link_found")))

    print("\n  Disavow diff:")
    dd_dir = tempfile.mkdtemp()
    old_f = os.path.join(dd_dir, "old.txt")
    new_f = os.path.join(dd_dir, "new.txt")
    open(old_f, "w").write("# live\ndomain:oldspam.com\ndomain:stillbad.net\n")
    open(new_f, "w").write("domain:stillbad.net\ndomain:newspam.xyz\n")
    dd = disavow_mod.diff(old_f, new_f)
    flag("added detected", dd["added"] == ["domain:newspam.xyz"])
    flag("REMOVED detected (the dangerous one)", dd["removed"] == ["domain:oldspam.com"])
    flag("unchanged detected", dd["unchanged"] == ["domain:stillbad.net"])
    flag("merged keeps everything", len(dd["merged"]) == 3)
    flag("missing existing file is handled",
         disavow_mod.diff(os.path.join(dd_dir, "nope.txt"), new_f)["have_existing"] is False)
    flag("comments and blanks ignored",
         disavow_mod.parse("# c\n\ndomain:a.com\n", is_text=True) == {"domain:a.com"})

    print("\n  Run-to-run diff:")
    import json as _json
    rd_dir = tempfile.mkdtemp()
    def _mk(rows, when):
        return {"meta": {"when": when},
                "summary": {"avg_score": round(sum(r["score"] for r in rows) / len(rows), 1)},
                "rows": rows}
    o_rows = [
        dict(url="https://a.com/1", registered="a.com", verdict="GOOD", score=82,
             link_found=True, is_followed=True, target_checked=True),
        dict(url="https://b.com/2", registered="b.com", verdict="GOOD", score=78,
             link_found=True, is_followed=True, target_checked=True),
        dict(url="https://e.com/5", registered="e.com", verdict="GOOD", score=80,
             link_found=True, is_followed=True, target_checked=True),
    ]
    n_rows = [
        dict(url="https://a.com/1", registered="a.com", verdict="DEAD", score=5,
             link_found=False, target_checked=True, status_code=404),
        dict(url="https://b.com/2", registered="b.com", verdict="LOW_VALUE", score=45,
             link_found=True, is_followed=False, is_nofollow=True,
             link_rel="nofollow", target_checked=True),
        dict(url="https://e.com/5", registered="e.com", verdict="LINK_LOST", score=40,
             link_found=False, target_checked=True),
        dict(url="https://new.io/9", registered="new.io", verdict="GOOD", score=80,
             link_found=True, is_followed=True, target_checked=True),
    ]
    op = os.path.join(rd_dir, "o.json"); np_ = os.path.join(rd_dir, "n.json")
    _json.dump(_mk(o_rows, "2026-07-01 10:00"), open(op, "w"))
    _json.dump(_mk(n_rows, "2026-08-28 10:00"), open(np_, "w"))
    rd = rundiff_mod.compare(op, np_)
    ch = rd["changes"]
    flag("death detected", [e["url"] for e in ch["died"]] == ["https://a.com/1"])
    flag("a dead page is NOT double-counted as link-removed",
         "https://a.com/1" not in [e["url"] for e in ch["link_lost"]])
    flag("link removal on a LIVE page detected",
         [e["url"] for e in ch["link_lost"]] == ["https://e.com/5"])
    flag("went-nofollow needs positive evidence",
         [e["url"] for e in ch["went_nofollow"]] == ["https://b.com/2"])
    flag("new link detected", [r["url"] for r in rd["added"]] == ["https://new.io/9"])
    flag("new referring domain detected", rd["domains"]["new"] == ["new.io"])
    flag("score drops detected", len(ch["score_down"]) == 3)
    rd_csv = os.path.join(rd_dir, "changes.csv")
    flag("changes csv written", rundiff_mod.write_csv(rd, rd_csv) > 0
         and os.path.getsize(rd_csv) > 120)
    flag("console summary renders", "Links that died" in rundiff_mod.console_summary(rd))
    same = rundiff_mod.compare(op, op)
    flag("identical runs report no changes", same["n_changed"] == 0)

    print("\n  Database - master list:")
    db_dir = tempfile.mkdtemp()
    db_path = os.path.join(db_dir, "t.db")
    sheet = os.path.join(db_dir, "master.csv")
    # Mirrors the real sheet's shape: two side-by-side column blocks, the
    # second one empty, and a trailing "To Check" column.
    open(sheet, "w", encoding="utf-8").write(
        "Domain,DA ,SS,Status,,To Check,Domain,DA,SS,Status\n"
        "medium.com,95,1,No Issues,,,,,,\n"
        "conformance1.com,10,17,Spammy,,,,,,\n"
        "blog.tandemai.io,5,1,No Issues,,,,,,\n"
        "nostatus.com,40,3,,,,,,,\n"
        "medium.com,95,1,No Issues,,,,,,\n")          # duplicate, must be skipped
    tdb = db_mod.AuditDb(db_path)
    res = tdb.import_sheet(sheet)
    flag(f"sheet imported ({res['imported']} new)", res["imported"] == 4)
    flag("duplicate row skipped", res["skipped"] >= 1)
    flag("no import error", res["error"] == "")
    st = tdb.stats()
    flag("statuses counted", st["by_status"].get("Spammy") == 1
         and st["by_status"].get("No Issues") == 2)
    flag("DA stored", st["with_da"] == 4)

    print("\n  Database - matching:")
    flag("exact host matches", tdb.lookup("https://medium.com/x")["master_match"] == "host")
    flag("www form matches the registered domain",
         tdb.lookup("https://www.medium.com/")["in_master"] is True)
    flag("subdomain on the sheet matches",
         tdb.lookup("https://blog.tandemai.io/post")["in_master"] is True)
    flag("status comes back",
         tdb.lookup("https://conformance1.com/p")["master_status"] == "Spammy")
    flag("unknown domain is not a match",
         tdb.lookup("https://never-seen-zz9.com/x")["in_master"] is False)
    flag("blank status is preserved as blank",
         tdb.lookup("https://nostatus.com/")["master_status"] == "")

    print("\n  Database - metrics reuse window:")
    fresh = tdb.metrics_for(["medium.com", "conformance1.com"], max_age_days=30)
    flag("recent DA is reused", fresh.get("medium.com", {}).get("da") == 95.0)
    flag("reuse is labelled as coming from the sheet",
         fresh.get("medium.com", {}).get("source") == "master-sheet")
    # Backdate the record rather than racing the clock with a microscopic TTL:
    # the whole test can run inside such a window, which made this flaky.
    with tdb._connect() as _c:
        _c.execute("UPDATE master_domains SET last_seen=? WHERE host=?",
                   ("2020-01-01T00:00:00+00:00", "medium.com"))
    flag("DA recorded years ago is NOT reused",
         tdb.metrics_for(["medium.com"], max_age_days=30) == {})
    flag("that domain is listed for a refresh",
         tdb.stale_metrics(["medium.com"], max_age_days=30) == ["medium.com"])
    flag("a fresh sibling is still reused",
         tdb.metrics_for(["conformance1.com"], max_age_days=30)
         .get("conformance1.com", {}).get("da") == 10.0)
    flag("max_age_days=0 disables the window entirely",
         tdb.metrics_for(["medium.com"], max_age_days=0)
         .get("medium.com", {}).get("da") == 95.0)
    flag("unknown domain yields no metrics",
         tdb.metrics_for(["never-seen-zz9.com"], 30) == {})

    print("\n  Database - a known domain is still fully checked:")
    known_row = {"url": "https://medium.com/x", "status_verdict": "LIVE", "tier": "B",
                 "outbound_links": 20, "home_checked": True}
    known_row.update(tdb.lookup("https://medium.com/x"))
    g = gate_mod.evaluate(known_row, cfg)
    flag("being on the master list does not skip the gates",
         g["gate_passed"] is True and g["gate_stage"] == gate_mod.STAGE_METRICS)
    dead_known = {"url": "https://medium.com/x", "status_verdict": "DEAD",
                  "status_code": 404}
    dead_known.update(tdb.lookup("https://medium.com/x"))
    flag("a known domain that died is still reported dead",
         score_mod.score_row(dead_known, cfg)["verdict"] == "DEAD")

    print("\n  Database - learning and history:")
    rows_for_db = [
        {"url": "https://newspam.xyz/p", "host": "newspam.xyz", "registered": "newspam.xyz",
         "verdict": "TOXIC", "score": 8, "issues": "gambling content"},
        {"url": "https://fine.com/p", "host": "fine.com", "registered": "fine.com",
         "verdict": "GOOD", "score": 80, "issues": ""},
    ]
    added = tdb.add_from_audit(rows_for_db)
    flag("newly toxic domain remembered", added == 1)
    flag("it is now on the master list",
         tdb.lookup("https://newspam.xyz/p")["master_status"] == "Spammy")
    flag("a GOOD row is not added", tdb.lookup("https://fine.com/p")["in_master"] is False)
    before = tdb.stats()["runs"]
    tdb.record_run("run_test_1", "edstellar.com", rows_for_db, {"total": 2})
    flag("run recorded", tdb.stats()["runs"] == before + 1)
    flag("links recorded", tdb.stats()["links_recorded"] >= 2)
    flag("db size reported including WAL", tdb.stats()["db_bytes"] > 4096)

    print("\n  Input parsing - URLs and bare domains together:")
    in_dir = tempfile.mkdtemp()
    mixed = os.path.join(in_dir, "mixed.csv")
    open(mixed, "w", encoding="utf-8").write(
        "url,target,anchor,notes\n"
        "medium.com,edstellar.com,,bare domain\n"
        "https://conformance1.com/page,edstellar.com,,full url\n")
    from seo_audit import inputs as inputs_read
    got = inputs_read.read_input_file(mixed)
    urls = [i["url"] for i in got]
    flag("both a domain and a URL are read", len(got) == 2)
    flag("header row is NOT read as data",
         not any(u.strip().lower() in inputs_read.ALL_KEYS for u in urls))
    # read_input_file returns cells verbatim; normalising is gather_input's job,
    # so assert the contract where it actually lives.
    flag("bare domain is read as-is", urls[0] == "medium.com")
    flag("a bare domain gains a scheme when normalised",
         fetch.normalize_url(urls[0]) == "https://medium.com")
    flag("a full URL survives normalising unchanged",
         fetch.normalize_url(urls[1]) == "https://conformance1.com/page")
    flag("URL path is preserved", urls[1].endswith("/page"))
    headerless = os.path.join(in_dir, "plain.csv")
    open(headerless, "w", encoding="utf-8").write("medium.com\nfoo.com\n")
    flag("headerless file still works", len(inputs_read.read_input_file(headerless)) == 2)
    sneaky = os.path.join(in_dir, "sneaky.csv")
    open(sneaky, "w", encoding="utf-8").write("domain\nmedium.com\n")
    flag("a lone 'domain' header is not audited",
         [i["url"] for i in inputs_read.read_input_file(sneaky)][0].endswith("medium.com"))

    print("\n  www handling (the medium.com bug):")
    for host, want in [("https://www.medium.com/", "medium.com"),
                       ("https://someblog.medium.com/x", "someblog.medium.com"),
                       ("https://www.wordpress.com/", "wordpress.com"),
                       ("https://spammer.wordpress.com/", "spammer.wordpress.com"),
                       ("https://www.uncp.edu.pe/", "uncp.edu.pe")]:
        flag(f"{host} -> {want}", dom.registered_domain(host) == want)
    flag("www is not treated as a real subdomain",
         dom.is_real_subdomain("https://www.medium.com/") is False)

    print("\n  DNS is a hint, not a verdict:")
    dns2 = resolve_mod.DnsCache(4)
    r_dead = dns2.resolve("this-really-does-not-exist-zz991.invalid")
    flag("a bad name still reports unresolved", r_dead["resolved"] is False)
    st_row = {"status_verdict": "DNS_ERROR", "tier": "D",
              "error": "domain does not resolve (confirmed by DNS and HTTP)"}
    flag("a CONFIRMED dead domain is DEAD",
         score_mod.score_row(st_row, cfg)["verdict"] == "DEAD")
    # The important property: a failed lookup alone must not short-circuit HTTP.
    src_fetch = open(os.path.join(ROOT, "seo_audit", "net", "fetch.py"),
                     encoding="utf-8").read()
    flag("fetch does not return early on a failed lookup",
         'out["dns_said_no"] = True' in src_fetch
         and 'if rec.get("confirmed_dead")' not in src_fetch)
    flag("fetch records when the resolver was wrong", 'dns_note' in src_fetch)

    print("\n  Browser retry covers blocked pages:")
    src_pipe = open(os.path.join(ROOT, "seo_audit", "pipeline.py"),
                    encoding="utf-8").read()
    flag("blocked pages are flagged for a browser re-check",
         'render_blocked' in src_pipe)
    flag("render reason is recorded", 'render_reason' in src_pipe)
    flag("render_blocked is configurable",
         "render_blocked" in yaml.safe_load(
             open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))["pipeline"])

    print("\n  CDN vs VPS hosting (the Hetzner case):")
    for label, want in [("CLOUDFLARENET", "shared"), ("Amazon Data Services", "shared"),
                        ("GoDaddy.com LLC", "shared"), ("Automattic Inc", "shared"),
                        ("Hetzner Online GmbH", "vps"), ("Contabo GmbH", "vps"),
                        ("DigitalOcean LLC", "vps"), ("Vultr Holdings", "vps"),
                        ("OVH SAS", "vps")]:
        is_shared = bool(asn_mod.SHARED_HOSTING_HINTS.search(label))
        is_vps = bool(asn_mod.VPS_HINTS.search(label))
        got = "vps" if is_vps else ("shared" if is_shared else "unknown")
        flag(f"{label} classified as {want}", got == want)
    hetzner_trio = [dict(registered=d, ip="195.201.46.178", shared_host=False,
                         vps_host=True, net_org="Hetzner Online GmbH", generator="",
                         page_title=t)
                    for d, t in [("apages.co.uk", "APages: curated local news"),
                                 ("bpages.co.uk", "BPages: curated local news"),
                                 ("cpages.co.uk", "CPages: curated local news")]]
    flag("three sites on one VPS IP DO cluster",
         len(netfp.analyse(hetzner_trio, cfg)["clusters"]) == 1)
    cf_trio = [dict(r, ip="104.21.0.9", shared_host=True, vps_host=False,
                    net_org="Cloudflare, Inc.",
                    page_title=t)
               for r, t in zip([dict(x) for x in hetzner_trio],
                               ["Sourdough Bakery Bristol", "Wandern Alpen Reise",
                                "Motorcycle Restoration Guides"])]
    flag("three unrelated sites behind a CDN do NOT cluster",
         len(netfp.analyse(cf_trio, cfg)["clusters"]) == 0)

    print("\n  Master list vs live check (the anibookmark case):")
    for label, row_d, want in [
        ("recorded clean, now toxic",
         dict(in_master=True, master_status="No Issues", verdict="TOXIC"), "clean_now_bad"),
        ("recorded clean, now dead",
         dict(in_master=True, master_status="No Issues", verdict="DEAD"), "clean_now_dead"),
        ("recorded spammy, now clean",
         dict(in_master=True, master_status="Spammy", verdict="GOOD"), "spammy_now_clean"),
        ("recorded spammy, still toxic",
         dict(in_master=True, master_status="Spammy", verdict="TOXIC"), ""),
        ("recorded clean, still good",
         dict(in_master=True, master_status="No Issues", verdict="GOOD"), ""),
        ("not on the sheet at all",
         dict(in_master=False, verdict="TOXIC"), ""),
    ]:
        flag(label, report_mod.master_disagreement(row_d) == want)
    flag("a contradiction becomes its own action",
         report_mod.action_group(dict(in_master=True, master_status="No Issues",
                                      verdict="TOXIC")) == "correct_sheet_bad")
    flag("a needless disavow becomes its own action",
         report_mod.action_group(dict(in_master=True, master_status="Spammy",
                                      verdict="GOOD")) == "correct_sheet_clean")
    flag("agreement does not create a correction action",
         report_mod.action_group(dict(in_master=True, master_status="Spammy",
                                      verdict="TOXIC")) == "disavow")
    dis_rows = [dict(in_master=True, master_status="No Issues", verdict="TOXIC",
                     url="https://a.com/", registered="a.com", score=5),
                dict(in_master=True, master_status="No Issues", verdict="GOOD",
                     url="https://b.com/", registered="b.com", score=80)]
    dsum = report_mod.summarize(dis_rows, cfg)
    flag("disagreements are counted in the summary",
         dsum["master_disagrees"] == 1 and dsum["clean_now_bad"] == 1)

    print("\n  Report says when link verification was skipped:")
    dom_only = [dict(url="https://a.com/", registered="a.com", verdict="LOW_VALUE",
                     score=40, target_checked=False, gate_stage="4-metrics",
                     tier="D", tier_label="Unproven", status_verdict="LIVE",
                     status_code=200)]
    tmp_html = os.path.join(tempfile.mkdtemp(), "r.html")
    report_mod.write_html(dom_only, tmp_html, report_mod.summarize(dom_only, cfg),
                          {"target": "x", "when": "now"})
    body = open(tmp_html, encoding="utf-8").read()
    flag("the notice appears when nothing could be verified",
         "Link verification did not run" in body)
    verified = [dict(dom_only[0], target_checked=True, link_found=True)]
    report_mod.write_html(verified, tmp_html, report_mod.summarize(verified, cfg),
                          {"target": "x", "when": "now"})
    flag("and is absent when everything was verified",
         "Link verification did not run" not in
         open(tmp_html, encoding="utf-8").read())

    print("\n  Package layout:")
    import seo_audit
    flag("package exposes a version", bool(getattr(seo_audit, "__version__", "")))
    for mod in ("seo_audit.cli", "seo_audit.pipeline", "seo_audit.inputs",
                "seo_audit.appconfig", "seo_audit.net.fetch", "seo_audit.net.robots",
                "seo_audit.analysis.homepage", "seo_audit.scoring.gate",
                "seo_audit.providers.metrics", "seo_audit.reporting.report",
                "seo_audit.store.resultcache"):
        try:
            __import__(mod)
            ok_m = True
        except Exception:                                    # noqa: BLE001
            ok_m = False
        flag(f"{mod} imports", ok_m)
    flag("authority data still resolves after the move",
         len(classify.load_authority_domains()) > 100)

    print("\n  Excel sheet naming:")
    flag("slashes stripped from sheet names",
         "/" not in report_mod.safe_sheet_name("HTTP 401 / 403 / 429"))
    flag("sheet name capped at 31 chars", len(report_mod.safe_sheet_name("x" * 60)) == 31)

    # ---- report writers ----------------------------------------------
    print("\n  Report writers:")
    summary = report_mod.summarize(rows, cfg)
    meta = {"target": TARGET, "when": "test", "metrics_provider": "none"}
    for name, fn in (("csv", lambda p: report_mod.write_csv(rows, p)),
                     ("xlsx", lambda p: report_mod.write_xlsx(rows, p, summary, arep, nsum)),
                     ("html", lambda p: report_mod.write_html(rows, p, summary, meta, arep, nsum)),
                     ("json", lambda p: report_mod.write_json(rows, p, summary, meta)),
                     ("outreach", lambda p: report_mod.write_outreach(rows, p)),
                     ("anchors", lambda p: report_mod.write_anchor_report(rows, p, cfg)),
                     ("networks", lambda p: report_mod.write_network_report(rows, p, nsum))):
        fp = os.path.join(tmp, f"out.{name}")
        try:
            fn(fp)
            size = os.path.getsize(fp)
            # A minimum that proves real content was written without assuming
            # every report is large -- link_networks.csv is small by nature.
            flag(f"{name} written ({size:,} bytes)", size > 120)
        except Exception as e:                                # noqa: BLE001
            flag(f"{name} written -> {type(e).__name__}: {e}", False)

    # ---- metrics parser ----------------------------------------------
    print("\n  Metrics import parser:")
    p1 = metrics_mod.parse_metric_rows(
        [["URL", "DA", "PA", "SS", "TB", "QB"],
         ["https://en.wikipedia.org/", "98", "82", "1%", "2,340,111", "1,900,000"]])
    flag("guestpostlinks format -> DA 98", p1.get("wikipedia.org", {}).get("da") == 98.0)
    flag("guestpostlinks format -> SS 1",  p1.get("wikipedia.org", {}).get("spam_score") == 1.0)
    p2 = metrics_mod.parse_metric_rows(
        [["Website", "Domain Authority", "Page Authority", "Spam Score"],
         ["glassdoor.com", "92", "75", "2"]])
    flag("dapachecker format -> DA 92", p2.get("glassdoor.com", {}).get("da") == 92.0)
    p3 = metrics_mod.parse_metric_rows([["example.com", "45", "38", "5"]])
    flag("headerless paste -> DA 45", p3.get("example.com", {}).get("da") == 45.0)

    # ---- domain parsing ----------------------------------------------
    print("\n  Domain parsing:")
    flag("zootecnia.uncp.edu.pe -> uncp.edu.pe",
         dom.registered_domain("https://zootecnia.uncp.edu.pe/x") == "uncp.edu.pe")
    flag("bing.520.edu.pl -> 520.edu.pl",
         dom.registered_domain("bing.520.edu.pl") == "520.edu.pl")
    flag("en.wikipedia.org -> wikipedia.org",
         dom.registered_domain("https://en.wikipedia.org/wiki/X") == "wikipedia.org")
    flag("jtwxx1.zapto.org flagged free-subdomain",
         dom.is_free_subdomain("jtwxx1.zapto.org"))
    flag("ox.ac.uk is tier A",
         classify.classify_domain("https://ox.ac.uk", authority)["tier"] == "A")
    flag("wikipedia.org is tier B",
         classify.classify_domain("https://en.wikipedia.org/x", authority)["tier"] == "B")
    flag("glassdoor.com is tier B",
         classify.classify_domain("https://glassdoor.com", authority)["tier"] == "B")
    flag("random .org is tier C (weak, not good)",
         classify.classify_domain("https://acgel.org", authority)["tier"] == "C")
    flag("onthejob.education is NOT tier A",
         classify.classify_domain("https://onthejob.education", authority)["tier"] != "A")

    # Release pooled sockets first, then close the listening socket. We do NOT
    # call srv.shutdown(): the serve_forever loop lives in a daemon thread and
    # shutdown() would block on any connection the pool is still holding.
    session.close()
    srv.server_close()

    print("\n" + "=" * 78)
    if FAILS:
        print(f"  {len(FAILS)} CHECK(S) FAILED")
        for f in FAILS:
            print(f"    - {f}")
        print("=" * 78)
        return 1
    print("  ALL CHECKS PASSED")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
