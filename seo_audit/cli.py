#!/usr/bin/env python3
"""
SEO Backlink Audit - command line entry point.

    python -m seo_audit                          audit everything in input/
    python -m seo_audit -i input/sites.csv       one specific file
    python -m seo_audit --urls a.com b.org       an ad-hoc list
    python -m seo_audit --no-content             status + tier only (fast)
    python -m seo_audit --resume                 continue an interrupted run
    python -m seo_audit --compare A.json B.json  diff two earlier runs

Run `python -m seo_audit --help` for the full set of flags.
"""

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from seo_audit import inputs as inputs_mod
from seo_audit import pipeline as pipeline_mod
from seo_audit.appconfig import ROOT, load_config, load_env
from seo_audit.analysis import archive as archive_mod
from seo_audit.analysis import classify
from seo_audit.analysis import domains as dom
from seo_audit.analysis import homepage as homepage_mod
from seo_audit.analysis import page as page_mod
from seo_audit.net import fetch
from seo_audit.net import render as render_mod
from seo_audit.net import resolve as resolve_mod
from seo_audit.net.robots import RobotsCache
from seo_audit.providers import asn as asn_mod
from seo_audit.providers import metrics as metrics_mod
from seo_audit.reporting import disavow_diff as disavow_mod
from seo_audit.reporting import report as report_mod
from seo_audit.reporting import rundiff as rundiff_mod
from seo_audit.scoring import gate as gate_mod
from seo_audit.scoring import network_footprint as netfp
from seo_audit.scoring import score as score_mod
from seo_audit.store import database as db_mod
from seo_audit.store import resultcache as resultcache_mod

audit_one = pipeline_mod.audit_one
HomepageCache = homepage_mod.HomepageCache
gather_input = inputs_mod.gather_input
read_input_file = inputs_mod.read_input_file


def main():
    ap = argparse.ArgumentParser(
        description="Audit SEO backlinks: HTTP status, trust tier, DA/PA, spam, link verification.")
    ap.add_argument("--input", "-i", help="specific .csv/.xlsx/.txt (default: everything in input/)")
    ap.add_argument("--urls", "-u", nargs="+", help="audit these URLs directly")
    ap.add_argument("--config", "-c", default=os.path.join(ROOT, "config.yaml"))
    ap.add_argument("--outdir", "-o", help="override output directory")
    ap.add_argument("--workers", "-w", type=int, help="override concurrency")
    ap.add_argument("--no-content", action="store_true",
                    help="skip page download: status + tier only (much faster)")
    ap.add_argument("--no-metrics", action="store_true", help="skip DA/PA lookup entirely")
    ap.add_argument("--queue-only", action="store_true",
                    help="only write output/da_pa_queue.txt, do not audit")
    ap.add_argument("--limit", type=int, help="audit only the first N links (for testing)")
    ap.add_argument("--resume", action="store_true",
                    help="reuse cached results from a previous interrupted run")
    ap.add_argument("--fresh", action="store_true",
                    help="clear the resume cache before starting")
    ap.add_argument("--no-dns-precheck", action="store_true",
                    help="skip DNS pre-resolution (slower on lists with dead domains)")
    ap.add_argument("--no-render", action="store_true",
                    help="skip the browser re-check for links that look missing")
    ap.add_argument("--no-sitewide", action="store_true",
                    help="skip sitewide sampling")
    ap.add_argument("--no-archive", action="store_true",
                    help="skip Wayback lookups for dead links")
    ap.add_argument("--existing-disavow", metavar="FILE",
                    help="your currently-uploaded disavow file, to diff against")
    ap.add_argument("--compare", nargs=2, metavar=("OLD.json", "NEW.json"),
                    help="compare two previous runs and exit (no auditing)")
    ap.add_argument("--import-master", metavar="FILE", action="append",
                    help="import a master domain sheet (.csv/.xlsx) into the database; "
                         "repeatable. Exits after importing unless input is also given")
    ap.add_argument("--db-stats", action="store_true",
                    help="print what the database holds and exit")
    ap.add_argument("--no-db", action="store_true",
                    help="ignore the database for this run")
    ap.add_argument("--rerun", metavar="RUN.json",
                    help="re-audit the links from a previous run's JSON")
    ap.add_argument("--only", metavar="VERDICTS",
                    help="with --rerun, re-audit only these verdicts, "
                         "comma-separated (e.g. BLOCKED,DEAD)")
    ap.add_argument("--history", metavar="DOMAIN",
                    help="show what the database knows about one domain and exit")
    args = ap.parse_args()

    load_env(os.path.join(ROOT, ".env"))
    cfg = load_config(args.config)
    if args.workers:
        cfg.setdefault("network", {})["concurrency"] = args.workers

    out_dir = args.outdir or os.path.join(ROOT, cfg.get("output", {}).get("dir", "output"))
    os.makedirs(out_dir, exist_ok=True)

    # ---- database -------------------------------------------------------
    dbcfg = cfg.get("database", {}) or {}
    db = None
    if bool(dbcfg.get("enabled", True)) and not args.no_db:
        try:
            db = db_mod.open_db(ROOT, cfg)
        except Exception as exc:                      # noqa: BLE001
            print(f"  ! could not open the database: {type(exc).__name__}: {exc}")
            db = None

    if args.import_master:
        if db is None:
            sys.exit("ERROR: the database is disabled, so there is nowhere to import to.")
        print("=" * 72)
        print("  IMPORT MASTER SHEET")
        print("=" * 72)
        for f in args.import_master:
            if not os.path.exists(f):
                print(f"  ! not found: {f}")
                continue
            res = db.import_sheet(f)
            if res["error"]:
                print(f"  ! {res['file']}: {res['error']}")
            else:
                print(f"  {res['file']}: {res['imported']} new, {res['updated']} updated, "
                      f"{res['skipped']} skipped (of {res['read']} rows)")
        st = db.stats()
        print(f"\n  Database now holds {st['master_domains']:,} domains "
              f"({st['with_da']:,} with DA, {st['with_spam_score']:,} with Spam Score)")
        for k, v in st["by_status"].items():
            print(f"    {k:<14} {v:,}")
        if not (args.input or args.urls):
            print()
            return

    if args.history:
        if db is None:
            sys.exit("ERROR: the database is disabled.")
        from seo_audit.analysis import domains as _dom
        target_dom = _dom.registered_domain(args.history) or args.history
        conn = db._connect()
        print("=" * 72)
        print(f"  HISTORY: {target_dom}")
        print("=" * 72)
        m = db.lookup("https://" + args.history.replace("https://", "")
                      .replace("http://", "").strip("/") + "/")
        if m["in_master"]:
            print(f"  On your master list as: {m['master_status'] or '(no status)'}")
            print(f"    matched by {m['master_match']} ({m['master_host']}), "
                  f"DA {m['master_da']}, Spam Score {m['master_spam_score']}")
            print(f"    first recorded {m['master_first_seen']}, from {m['master_source']}")
        else:
            print("  Not on your master list.")
        rows_h = list(conn.execute(
            """SELECT l.run_id, r.started_at, l.url, l.verdict, l.score, l.da,
                      l.status_code, l.link_found, l.is_followed, l.action
                 FROM audit_links l JOIN audit_runs r ON r.run_id = l.run_id
                WHERE l.registered = ?
                ORDER BY r.started_at""", (target_dom,)))
        if not rows_h:
            print("\n  Never audited.")
        else:
            print(f"\n  Audited {len(rows_h)} time(s):\n")
            print(f"  {'when':17} {'verdict':10} {'score':>5} {'DA':>5} {'HTTP':>5} "
                  f"{'link':5} next action")
            print("  " + "-" * 74)
            prev = None
            for h in rows_h:
                when = (h["started_at"] or "")[:16].replace("T", " ")
                mark = ""
                if prev and prev != h["verdict"]:
                    mark = f"   <- changed from {prev}"
                print(f"  {when:17} {h['verdict'] or '?':10} "
                      f"{h['score'] if h['score'] is not None else '':>5} "
                      f"{h['da'] if h['da'] is not None else '':>5} "
                      f"{str(h['status_code'] or ''):>5} "
                      f"{('yes' if h['link_found'] else 'no'):5} "
                      f"{h['action'] or ''}{mark}")
                prev = h["verdict"]
        print()
        return

    if args.db_stats:
        if db is None:
            sys.exit("ERROR: the database is disabled.")
        import json as _j
        print(_j.dumps(db.stats(), indent=1))
        return

    # ---- compare mode: diff two earlier runs and stop ------------------
    if args.compare:
        old_p, new_p = args.compare
        for f in (old_p, new_p):
            if not os.path.exists(f):
                sys.exit(f"ERROR: run file not found: {f}")
        print("=" * 72)
        print("  RUN COMPARISON")
        print("=" * 72)
        d = rundiff_mod.compare(old_p, new_p)
        print(rundiff_mod.console_summary(d))
        cpath = os.path.join(out_dir, "changes.csv")
        n = rundiff_mod.write_csv(d, cpath)
        print(f"\n  {n} change row(s) written to {os.path.basename(cpath)}")
        print(f"  Folder: {out_dir}\n")
        return

    target = cfg.get("target_site", "")
    print("=" * 72)
    print("  SEO BACKLINK AUDIT")
    print("=" * 72)
    print(f"  Target site : {target or '(none set - link verification disabled)'}")
    print(f"  Config      : {args.config}")
    print("\nReading input...")

    if args.rerun:
        if not os.path.exists(args.rerun):
            sys.exit(f"ERROR: run file not found: {args.rerun}")
        import json as _json
        prev_rows = (_json.load(open(args.rerun, encoding="utf-8")).get("rows") or [])
        wanted = None
        if args.only:
            wanted = {v.strip().upper() for v in args.only.split(",") if v.strip()}
        items = [{"url": r.get("url", ""),
                  "target": r.get("input_target", "") or cfg.get("target_site", ""),
                  "anchor": r.get("input_anchor", ""),
                  "notes": r.get("notes", "")}
                 for r in prev_rows
                 if r.get("url") and (wanted is None or r.get("verdict") in wanted)]
        seen_u, uniq = set(), []
        for it in items:
            u = fetch.normalize_url(it["url"])
            if u and u not in seen_u:
                seen_u.add(u)
                it["url"] = u
                uniq.append(it)
        items = uniq
        print(f"  re-auditing {len(items)} link(s) from "
              f"{os.path.basename(args.rerun)}"
              + (f" (verdict in {sorted(wanted)})" if wanted else ""))
        if not items:
            sys.exit("Nothing matched. Check the --only verdicts against that run.")
    else:
        items = gather_input(cfg, args.input, args.urls)
    if args.limit:
        items = items[: args.limit]
    if not items:
        sys.exit("No URLs found.")
    print(f"  = {len(items)} unique backlinks to audit")

    all_domains = sorted({dom.registered_domain(i["url"]) for i in items
                          if dom.registered_domain(i["url"])})
    mcfg = cfg.get("metrics", {}) or {}
    pcfg = cfg.get("pipeline", {}) or {}
    cache = metrics_mod.MetricsCache(
        os.path.join(ROOT, "cache", "metrics_cache.json"),
        int(mcfg.get("cache_days", 30)),
    )
    queue_path = os.path.join(out_dir, "da_pa_queue.txt")
    print(f"  = {len(all_domains)} unique domains")

    if args.queue_only:
        uncached = [d for d in all_domains if not cache.get(d)]
        n_batches = metrics_mod.write_queue(uncached, queue_path, 100)
        print(f"\nWrote {n_batches} paste-batch(es) to {queue_path}")
        return

    # ---- audit --------------------------------------------------------
    net = cfg.get("network", {})
    session = fetch.make_session(cfg)
    throttle = fetch.HostThrottle(
        float(net.get("delay_per_host", 1.0)),
        float(net.get("max_delay_per_host", 15.0)),
        float(net.get("backoff_recover", 0.85)))
    robots = RobotsCache(session, cfg)
    authority = classify.load_authority_domains()
    scan_content = not args.no_content
    workers = int(net.get("concurrency", 8))

    use_dns = bool(pcfg.get("dns_precheck", True)) and not args.no_dns_precheck
    dns = resolve_mod.DnsCache(float(pcfg.get("dns_timeout", 5))) if use_dns else None
    homecache = HomepageCache(session, cfg, throttle, dns)

    rcache = resultcache_mod.ResultCache(
        os.path.join(ROOT, "cache", "results_cache.json"),
        float(pcfg.get("resume_hours", 24)))
    if args.fresh:
        rcache.clear()
        print("  resume cache cleared")
    staged = bool(pcfg.get("staged", True))
    check_home = bool(pcfg.get("check_homepage", True)) and scan_content

    print(f"\nAuditing {len(items)} backlinks with {workers} workers.")
    print(f"  Stage 1 live check      : ON")
    print(f"  Stage 2 page content    : {'ON' if scan_content else 'OFF (--no-content)'}")
    print(f"  Stage 3 home page       : {'ON' if check_home else 'OFF'}")
    print(f"  Stage 4 DA/PA           : {'only for links passing 1-3' if staged and pcfg.get('metrics_only_for_passing', True) else 'all domains'}")
    print(f"  DNS pre-check           : {'ON' if use_dns else 'OFF'}")
    if args.resume and len(rcache):
        print(f"  Resume                  : {len(rcache)} cached row(s) available")
    print()

    rows, t0 = [], time.time()
    todo, reused = [], 0
    for it in items:
        cached = rcache.get(it["url"]) if args.resume else None
        if cached:
            rows.append(cached)
            reused += 1
        else:
            todo.append(it)
    if reused:
        print(f"  reused {reused} cached row(s); {len(todo)} left to check\n")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(audit_one, it, session, cfg, throttle, robots,
                          authority, scan_content, homecache, dns, db): it
                for it in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            it = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:                 # noqa: BLE001
                row = {"url": it["url"], "status_verdict": "ERROR",
                       "error": f"audit crashed: {type(exc).__name__}: {exc}",
                       "tier": "D", "tier_label": "Unproven",
                       "registered": dom.registered_domain(it["url"]),
                       "target_checked": False, "gate_passed": False,
                       "gate_stage": gate_mod.STAGE_LIVE,
                       "gate_reason": "audit crashed", "needs_metrics": False}
            rows.append(row)
            rcache.put(it["url"], row)          # crash-safe: progress is on disk
            mark = "->4" if row.get("gate_passed") else "stop"
            print(f"  [{n}/{len(todo)}] {str(row.get('status_code') or 'ERR'):>4} "
                  f"{row.get('gate_stage', ''):<15} {mark:<5} {row['url'][:58]}")
    rcache.save()

    # ---- render pass: re-check links that look missing, in a real browser ----
    # Sequential and after the pool on purpose: Playwright's sync API must be
    # driven from one thread, and only a handful of links ever need this.
    if not args.no_render and bool(pcfg.get("render_js", True)):
        pending = [r for r in rows if r.get("needs_render")]
        if pending:
            ok, why = render_mod.available()
            if not ok:
                print(f"\n{why}")
            else:
                n_blocked = sum(1 for r in pending if r.get("render_reason") == "blocked")
                why = []
                if len(pending) - n_blocked:
                    why.append(f"{len(pending) - n_blocked} with a missing link")
                if n_blocked:
                    why.append(f"{n_blocked} that refused the crawler")
                print(f"\nRe-checking {len(pending)} page(s) in a browser "
                      f"({', '.join(why)})...")
                urls = [r.get("final_url") or r["url"] for r in pending]
                rendered = render_mod.render_many(
                    urls, cfg, int(pcfg.get("render_wait_ms", 1200)))
                recovered, unblocked = 0, 0
                for r in pending:
                    u = r.get("final_url") or r["url"]
                    html, err = rendered.get(u, ("", "not rendered"))
                    if err or not html:
                        r["render_note"] = err or "no content"
                        continue
                    try:
                        a = page_mod.analyze(html, u, r.get("input_target")
                                             or cfg.get("target_site", ""),
                                             cfg.get("target_aliases") or [], cfg)
                    except Exception as exc:              # noqa: BLE001
                        r["render_note"] = f"analysis failed: {type(exc).__name__}"
                        continue
                    r["rendered"] = True
                    was_blocked = r.get("render_reason") == "blocked"
                    if was_blocked:
                        # The page refused our HTTP client but a browser read it.
                        # That makes it judgeable, so promote it out of BLOCKED
                        # rather than leaving it unassessed - while recording the
                        # original status so nothing is hidden.
                        unblocked += 1
                        r["original_status_code"] = r.get("status_code")
                        r["original_status_verdict"] = r.get("status_verdict")
                        r["browser_readable"] = True
                        r["status_verdict"] = "LIVE"
                        r["error"] = ""
                        r.update(a)
                        r["render_note"] = (
                            f"refused our crawler ({r.get('original_status_code') or 'error'}) "
                            f"but read fine in a browser - judged on the browser's view")
                        r.update(gate_mod.evaluate(r, cfg))
                    elif a.get("link_found"):
                        recovered += 1
                        r.update(a)
                        r["render_note"] = ("link found only after JavaScript ran - "
                                            "it is live, the plain HTML just lacks it")
                        r.update(gate_mod.evaluate(r, cfg))
                    else:
                        r["render_note"] = "still no link after JavaScript ran"
                if recovered:
                    print(f"  recovered {recovered} link(s) that only exist after "
                          f"JavaScript runs (would have read as LINK_LOST)")
                if unblocked:
                    print(f"  read {unblocked} page(s) that refused the crawler "
                          f"(would have stayed BLOCKED and unjudged)")
                if not (recovered or unblocked):
                    print(f"  nothing changed for the {len(pending)} page(s) re-checked")

    # ---- archive pass: what did the dead pages used to say? ----
    if not args.no_archive and bool(pcfg.get("archive_dead_links", True)):
        dead = [r for r in rows if r.get("status_verdict") in ("DEAD", "GONE", "DNS_ERROR")]
        if dead:
            acache = archive_mod.ArchiveCache(
                os.path.join(ROOT, "cache", "archive_cache.json"),
                enabled=True,
                max_lookups=int(pcfg.get("archive_max_lookups", 200)))
            print(f"\nAsking the Wayback Machine about {len(dead)} dead link(s)...")
            for r in dead:
                try:
                    r.update(acache.recover(r["url"], session, cfg,
                                            r.get("input_target") or target,
                                            cfg.get("target_aliases") or []))
                except Exception as exc:                  # noqa: BLE001
                    r["archive_note"] = f"archive failed: {type(exc).__name__}"
            acache.save()
            st = acache.stats()
            with_link = sum(1 for r in dead if r.get("archive_link_found"))
            print(f"  {st['snapshots_found']} snapshot(s) found; "
                  f"{with_link} still show your link - use those for outreach")

    if dns:
        d = dns.stats()
        msg = f"\nDNS: {d['resolved']} of {d['hosts']} host(s) resolved"
        if d["unresolved"]:
            msg += f"; {d['unresolved']} dead domain(s) skipped instantly"
        print(msg + ".")
    tstats = throttle.stats()
    if tstats["pushback_responses"]:
        print(f"Rate limiting: {tstats['pushback_responses']} pushback response(s) from "
              f"{tstats['throttled_hosts']} host(s); slowed to "
              f"{tstats['worst_delay']}s at the worst point.")

    elapsed = time.time() - t0

    # ---- STAGE 4: DA/PA, only for links that passed the earlier gates ----
    eligible = sorted({r.get("registered", "") for r in rows if r.get("needs_metrics")})
    eligible = [d for d in eligible if d]
    skipped = len(all_domains) - len(eligible)
    print(f"\nStage 4: {len(eligible)} domain(s) passed the live + content gates"
          f"{f'; {skipped} skipped (no DA/PA needed)' if skipped else ''}.")

    provider_name = "none" if args.no_metrics else str(mcfg.get("provider", "none"))

    # Numbers we already own come first. The master sheet carries DA and Spam
    # Score for thousands of domains, so asking a provider for those again
    # would be paying twice for the same fact.
    from_db, stale = {}, []
    if db is not None and eligible and not args.no_metrics:
        reuse_days = float(dbcfg.get("reuse_metrics_days", 30))
        try:
            from_db = db.metrics_for(eligible, reuse_days)
            stale = db.stale_metrics(eligible, reuse_days)
        except Exception as exc:                      # noqa: BLE001
            print(f"  ! database metrics lookup failed: {type(exc).__name__}: {exc}")
        if from_db:
            print(f"  {len(from_db)} domain(s) already had DA/Spam Score on your master "
                  f"list, recorded within {reuse_days:g} days - reused, not re-checked")
        if stale:
            print(f"  {len(stale)} domain(s) had DA older than {reuse_days:g} days "
                  f"- queued for a refresh")

    still_needed = [d for d in eligible if d not in from_db]
    provider = (metrics_mod.NoneProvider() if args.no_metrics
                else metrics_mod.build_provider(cfg, ROOT))
    metric_map = dict(from_db)
    if still_needed:
        metric_map.update(metrics_mod.collect(
            still_needed, provider, cache, bool(mcfg.get("allow_missing", True))))

    for row in rows:
        m = metric_map.get(row.get("registered", ""), {}) or {}
        for k in ("da", "pa", "spam_score", "backlinks",
                  "quality_backlinks", "referring_domains", "domain_age"):
            row[k] = m.get(k)
        row["metrics_source"] = m.get("source", "")
        row.update(score_mod.score_row(row, cfg))

    # ---- sort: most urgent first --------------------------------------
    order = {v: i for i, v in enumerate(report_mod.VERDICT_ORDER)}
    rows.sort(key=lambda r: (order.get(r.get("verdict"), 99), r.get("score", 0)))

    # ---- hosting lookup, then link-network footprint ----
    ncfg = cfg.get("network_footprint", {}) or {}
    if bool(ncfg.get("enabled", True)) and bool(ncfg.get("asn_lookup", True)):
        ips = {(r.get("ip") or "").strip() for r in rows}
        ips.discard("")
        if ips:
            acache = asn_mod.AsnCache(
                os.path.join(ROOT, "cache", "asn_cache.json"),
                enabled=True,
                max_lookups=int(ncfg.get("asn_max_lookups", 300)))
            print(f"\nLooking up who hosts {len(ips)} unique IP(s)...")
            asn_mod.annotate(rows, acache)
            acache.save()
            ast_ = acache.stats()
            print(f"  identified {ast_['identified']} of {ast_['cached_ips']}; "
                  f"{ast_['shared_hosts']} on large shared hosts (discounted as a signal)")

    net = netfp.analyse(rows, cfg)
    if net.get("clusters"):
        print(f"\nLink networks: {len(net['clusters'])} cluster(s) covering "
              f"{net['domains_in_clusters']} domain(s).")
        for c in net["clusters"][:5]:
            print(f"  {c['id']}: {c['size']} domains - {'; '.join(c['signals'])}")
        # a cluster changes the verdict, so re-score with that knowledge
        for row in rows:
            row.update(score_mod.score_row(row, cfg))

    summary = report_mod.summarize(rows, cfg)
    meta = {
        "target": target,
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "metrics_provider": provider_name,
        "links": len(rows),
        "elapsed_sec": round(elapsed, 1),
        "page_scan": scan_content,
    }

    # ---- write reports -------------------------------------------------
    ocfg = cfg.get("output", {}) or {}
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    prefix = ocfg.get("prefix", "backlink_audit")
    written = []

    def p(name):
        return os.path.join(out_dir, name)

    anchor_rep = None
    if ocfg.get("csv", True):
        f = p(f"{prefix}_{stamp}.csv")
        report_mod.write_csv(rows, f)
        written.append(f)
    f = p("anchor_text.csv")
    anchor_rep = report_mod.write_anchor_report(rows, f, cfg)
    written.append(f)
    f = p("link_networks.csv")
    report_mod.write_network_report(rows, f, net)
    written.append(f)
    if ocfg.get("excel", True):
        f = p(f"{prefix}_{stamp}.xlsx")
        report_mod.write_xlsx(rows, f, summary, anchor_rep, net)
        written.append(f)
    if ocfg.get("html", True):
        f = p(f"{prefix}_{stamp}.html")
        report_mod.write_html(rows, f, summary, meta, anchor_rep, net)
        written.append(f)

    f = p("disavow.txt")
    n_dis = report_mod.write_disavow(rows, f)
    written.append(f)

    existing = args.existing_disavow or (ocfg.get("existing_disavow") or "")
    dis_diff = disavow_mod.diff(existing, f)
    dpath = p("disavow_diff.txt")
    disavow_mod.write_report(dis_diff, dpath, p("disavow_merged.txt"))
    written.extend([dpath, p("disavow_merged.txt")])
    f = p("outreach_list.csv")
    n_out = report_mod.write_outreach(rows, f)
    written.append(f)
    f = p(f"{prefix}_{stamp}.json")
    report_mod.write_json(rows, f, summary, meta, anchor_rep, net)
    written.append(f)

    if db is not None:
        try:
            if bool(dbcfg.get("record_runs", True)):
                db.record_run(stamp, target, rows, summary)
            if bool(dbcfg.get("learn_from_runs", True)):
                added = db.add_from_audit(rows)
                if added:
                    print(f"  {added} newly-toxic domain(s) remembered on the master list")
        except Exception as exc:                      # noqa: BLE001
            print(f"  ! could not write to the database: {type(exc).__name__}: {exc}")

    # Keep a copy in history/ so --compare always has something to diff
    # against, even when output/ gets cleared out.
    hist_dir = os.path.join(ROOT, "history")
    os.makedirs(hist_dir, exist_ok=True)
    hist_path = os.path.join(hist_dir, f"run_{stamp}.json")
    try:
        import shutil
        shutil.copy2(f, hist_path)
    except OSError:
        hist_path = ""

    # If an earlier run exists, diff against the most recent one automatically.
    prior = sorted(x for x in os.listdir(hist_dir)
                   if x.startswith("run_") and x.endswith(".json")
                   and x != os.path.basename(hist_path))
    run_diff = None
    if prior:
        try:
            run_diff = rundiff_mod.compare(os.path.join(hist_dir, prior[-1]), f)
            cpath = p("changes.csv")
            rundiff_mod.write_csv(run_diff, cpath)
            written.append(cpath)
        except Exception as exc:                      # noqa: BLE001
            print(f"  ! could not compare with the previous run: {type(exc).__name__}: {exc}")
            run_diff = None

    # Queue only the domains that actually deserve a DA/PA lookup. This is the
    # whole payoff of staging: you paste 6 domains into a checker, not 20.
    still = [d for d in eligible if metric_map.get(d, {}).get("da") in (None, "")]
    metrics_mod.write_queue(still, queue_path, 100)

    # ---- console summary ----------------------------------------------
    print("\n" + "=" * 72)
    print(f"  RESULTS  ({len(rows)} links in {elapsed:.0f}s, avg score {summary['avg_score']})")
    print("=" * 72)
    print("  HTTP     200 live {:<5} 3xx {:<5} 404/410 {:<5} 5xx {:<4} blocked {:<4} error {}".format(
        summary["http_200"], summary["http_3xx"], summary["http_404"],
        summary["http_5xx"], summary["http_blocked"], summary["http_err"]))
    print("  Tiers    A {:<5} B {:<5} C {:<5} D {}".format(
        summary["tiers"].get("A", 0), summary["tiers"].get("B", 0),
        summary["tiers"].get("C", 0), summary["tiers"].get("D", 0)))
    if summary["links_checked"]:
        print("  Links    {} of {} still on the page, {} followed".format(
            summary["links_live"], summary["links_checked"], summary["links_followed"]))
    print("  DA data  {} of {} domains".format(summary["with_metrics"], len(all_domains)))
    if summary.get("links_sitewide") or summary.get("links_incontent"):
        print("  Placement {} in-content, {} sitewide boilerplate".format(
            summary.get("links_incontent", 0), summary.get("links_sitewide", 0)))
    if summary.get("in_network"):
        print("  Networks {} domain(s) inside {} detected cluster(s)".format(
            summary["in_network"], len(net.get("clusters", []))))
    n_master = sum(1 for r in rows if r.get("in_master"))
    if n_master:
        spammy = sum(1 for r in rows if r.get("in_master")
                     and "spam" in (r.get("master_status") or "").lower())
        print("  Known    {} of {} already on your master list ({} marked spammy there)".format(
            n_master, len(rows), spammy))
    if anchor_rep and anchor_rep.get("warnings"):
        print("  Anchors  " + anchor_rep["warnings"][0][:80])
    print("  " + "-" * 68)
    for v in report_mod.VERDICT_ORDER:
        c = summary["verdicts"].get(v, 0)
        if c:
            print(f"  {v:<11} {c:>5}")
    print("  " + "-" * 68)
    print(f"  disavow.txt        {n_dis} domain(s)  (TOXIC only - verify before uploading)")
    if dis_diff["have_existing"]:
        print(f"  disavow_diff.txt   +{len(dis_diff['added'])} added, "
              f"-{len(dis_diff['removed'])} would be REMOVED -> use disavow_merged.txt")
    n_render = sum(1 for r in rows if r.get("rendered") and r.get("link_found")
                   and not r.get("browser_readable"))
    if n_render:
        print(f"  browser re-check   {n_render} link(s) were live after all (JS-rendered)")
    n_unblocked = sum(1 for r in rows if r.get("browser_readable"))
    if n_unblocked:
        print(f"  browser re-check   {n_unblocked} page(s) refused the crawler but were "
              f"readable in a browser")
    n_arch = sum(1 for r in rows if r.get("archive_link_found"))
    if n_arch:
        print(f"  archive            {n_arch} dead page(s) recovered with your old anchor")
    n_sw = sum(1 for r in rows if r.get("sitewide_ratio", 0) >= 1.0
               and r.get("sitewide_sampled", 0) >= 2)
    if n_sw:
        print(f"  sitewide           {n_sw} link(s) confirmed on every sampled page")
    print(f"  outreach_list.csv  {n_out} link(s) worth an email")
    if still:
        print(f"\n  {len(still)} domain(s) still have no DA/PA.")
        print(f"  Paste the batches in {os.path.basename(queue_path)} into a bulk DA-PA checker,")
        print(f"  save the result into input/metrics/, then re-run to fill them in.")
    if run_diff and run_diff["n_changed"]:
        print("\n  Since the previous run:")
        print(rundiff_mod.console_summary(run_diff))
    elif run_diff:
        print("\n  Nothing changed since the previous run.")

    print("\n  Reports:")
    for f in written:
        print(f"    - {os.path.basename(f)}")
    print(f"\n  Folder: {out_dir}\n")


if __name__ == "__main__":
    main()
