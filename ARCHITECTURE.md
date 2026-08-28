# Architecture

Where things live and why. Read `README.md` first for what the tool does; this
is for changing it.

## The one idea

Everything is arranged around a single principle: **do the cheap check first,
and stop as soon as a link is disqualified.** DNS costs a millisecond, a HEAD
request costs a round trip, a page download costs a second, and an authority
lookup costs money or your clicking time. Any design that spends the expensive
one before the cheap one is wasting most of its work, because on a real
backlink list most links fail early.

That principle is why the code is split the way it is. `scoring/gate.py` is
small but load-bearing: it is the only place that decides whether a link goes
forward, so the rules are readable in one screen instead of scattered through
the fetch and scoring code.

## Flow of one run

```
cli.main()
  |
  ├─ appconfig       load config.yaml, then .env over the top
  ├─ inputs          read csv/xlsx/txt, auto-detect columns, de-duplicate
  |
  ├─ store.database  open data/audit.db (master list + history)
  |
  ├─ ThreadPoolExecutor over pipeline.audit_one       <- concurrent
  |    ├─ store.database        is this domain already on the master list?
  |    ├─ analysis.classify      trust tier from the domain
  |    ├─ analysis.spamrules     spam keywords in the URL
  |    ├─ net.resolve            DNS (cached per host)
  |    ├─ net.fetch              status + redirect chain via the fetch ladder
  |    ├─ net.fetch              root-domain probe, only if it failed
  |    ├─ analysis.page          STAGE 2: link, rel, indexability, content
  |    ├─ net.robots             robots.txt (cached per origin)
  |    ├─ analysis.sitewide      sample sibling pages (optional)
  |    ├─ analysis.homepage      STAGE 3 (cached per origin)
  |    └─ scoring.gate           does this reach stage 4?
  |
  ├─ net.render      sequential browser re-check of links that looked missing
  ├─ analysis.archive  Wayback lookup for dead links
  ├─ store.database    DA/PA you already own, if recent enough
  ├─ providers.metrics STAGE 4: DA/PA for whatever is left
  ├─ providers.asn     who hosts each IP
  ├─ scoring.network_footprint  cluster domains, then re-score
  ├─ scoring.score     composite score and verdict per row
  |
  ├─ store.database    record the run; remember newly-toxic domains
  └─ reporting.*      xlsx, html, csv, disavow, disavow diff, anchors,
                      networks, run diff, json -> history/
```

Two passes are deliberately **outside** the thread pool:

- **Rendering.** Playwright's sync API must be driven from the thread that
  created it, so it cannot be called from a pool worker. It is also slow. Both
  point the same way: collect the few URLs that need it, render them
  sequentially afterwards.
- **Network footprint.** Clustering needs every row before it can group
  anything, so it runs once at the end — and because a cluster changes a
  verdict, rows are re-scored after it.

## Package map

| Package | Owns | Depends on |
|---|---|---|
| `appconfig` | config.yaml and .env loading, `ROOT` | yaml only |
| `inputs` | reading backlink lists | `net.fetch` (URL normalising) |
| `pipeline` | the per-link stage order | analysis, net, scoring |
| `cli` | argument parsing, orchestration, output | everything |
| `net` | anything that touches the network | analysis.domains |
| `analysis` | reading and understanding a page | net.fetch, analysis.domains |
| `scoring` | turning signals into a decision | nothing outside scoring |
| `providers` | external data (DA/PA, hosting) | analysis.domains |
| `reporting` | everything written to disk | scoring.anchors |
| `store` | on-disk state that survives a run | analysis.domains |

The dependency direction is one-way: `scoring` never imports `net`, and
`reporting` never imports `analysis`. That is what keeps the scoring rules
testable without a network, which is why the suite can run offline.

## The seven caches

Each exists because something expensive would otherwise repeat. Three live for
the run; four persist on disk between runs, which is why the second audit of a
list is far cheaper than the first.

| Cache | Keyed by | Lifetime | Saves |
|---|---|---|---|
| `net.resolve.DnsCache` | host | the run | Connect timeouts on dead domains |
| `net.robots.RobotsCache` | scheme://host:port | the run | One fetch per origin, not per link |
| `analysis.homepage.HomepageCache` | scheme://host:port | the run | Stage 3 for every sibling link |
| `providers.metrics.MetricsCache` | registered domain | 30 days (disk) | Real money |
| `providers.asn.AsnCache` | IP | forever (disk) | RDAP round trips |
| `analysis.archive.ArchiveCache` | URL | forever (disk) | Wayback round trips |
| `store.resultcache.ResultCache` | URL | 24 h, opt-in (disk) | A run that dies at link 900 |

Keying is not incidental. `RobotsCache` and `HomepageCache` key on the full
origin, *not* the hostname: keying on host alone loses the port and conflates
the http and https origins, which are allowed to differ. That was a real bug —
it fetched `https://host:443/robots.txt` for a link on `http://host:8080`.

## Adding things

**A new spam vertical** → add terms to `analysis/spamrules.py`. Put a term in
`UNAMBIGUOUS` only if it has no innocent reading; if an article warning people
off the practice would use the same words, leave it on the threshold.

**A new authority domain** → `data/authority_domains.yaml`. Re-read on change,
no restart.

**A new gate rule** → `scoring/gate.py`, then a `gcase(...)` in the test suite.
Keep it consistent with `spam_evidence` in `scoring/score.py`, or a row can be
scored TOXIC while still passing the gate.

**A new "your sheet is wrong" case** → add it to `master_disagreement()` in
`reporting/report.py`, give it an entry in `DISAGREEMENT_TEXT`, and if it needs
its own action, add it to `ACTIONS` and to the early return in `action_group()`.

**A new master-sheet column** → add a pattern to `_COL` in
`store/database.py`, a column to the `master_domains` schema, and a field to
`lookup()`'s return. `AuditDb.__init__` runs the schema with `IF NOT EXISTS`,
so add new columns with an `ALTER TABLE` guarded by a try/except rather than
editing the CREATE.

**A new metrics provider** → subclass `BaseProvider` in `providers/metrics.py`
and register it in `build_provider`. Return `{registered_domain: {da, pa,
spam_score, ...}}` and let missing credentials fall back rather than raise.

**A new report column** → add to `COLUMNS` in `reporting/report.py`. Widths are
in the same file; the HTML table is separate and deliberately narrower.

**A new signal that should affect the score** → set the field in `analysis` or
`net`, add a penalty key to `config.yaml` under `scoring.penalties`, read it in
`scoring/score.py` via `P("your_key", default)`. Never hard-code a deduction.

## Testing

`tests/run_tests.py` — 262 assertions, no internet. It starts
`tests/fixture_server.py`, a local server with a page for every case the
auditor must handle: a healthy link, nofollow, sponsored, a removed link, a
noindex page, gambling content, a parked domain, a link farm, thin content, a
cloaked link, a JS-injected link, a sitewide footer link, 404, 410, 403, 500, a
301, a three-hop chain, and a robots-disallowed page.

Two things about that server are load-bearing and easy to break:

- `daemon_threads = True`. Without it, a socket still held by a requests
  connection pool keeps a handler thread alive and `shutdown()` blocks forever.
- The home page at `/` is a **normal page**. It used to list the fixture paths
  verbatim, which meant stage 3 read the words "casino" and "linkfarm" on every
  domain's home page and the entire suite came back as spam. The browsable
  index lives at `/_index`.

`tests/check_docs.py` — checks the documentation against the code: every number
the README asserts, every CLI flag argparse defines, every output file the code
writes, and the project layout. A confidently wrong count teaches readers to
distrust the whole document, so the numbers are verified rather than trusted.

`tests/verify_report_ui.py` — drives the report's filter dropdowns in headless
Chromium, because markup assertions cannot prove JavaScript works. It reads the
newest HTML report in `output/`, so run an audit before it. Optional; skips
cleanly without Playwright, and skips cleanly when there is no report yet.

## The database

`store/database.py`, one SQLite file, three tables: `master_domains` (your
sheet), `audit_runs` and `audit_links` (history). No server, no dependency —
sqlite3 ships with Python.

Two design points worth not undoing:

- **A master-list match tags, it does not gate.** It is tempting to skip a
  domain you have already ruled on, and it would be wrong: the reason to audit
  weekly is that domains change. A "No Issues" domain that has since been
  flipped to a casino must still surface. Only DA and Spam Score are ever
  reused.
- **Reuse has an age limit** (`reuse_metrics_days`, default 30). Reusing a DA
  figure indefinitely would quietly rot the audit while looking like it was
  working. Anything past the limit is returned by `stale_metrics()` and
  re-queued instead.

Connections are per-thread: sqlite3 objects cannot be shared across threads,
and lookups happen inside the audit's pool.

## Things that look wrong but are not

- **`analysis/relevance.py` omits `ization`, `isation`, `er`, `ers` and `est`
  from its suffix list.** They look like ordinary suffixes but wreck real words:
  organization → organ, centre → cent, leader → lead. Plain `s` already covers
  the plural case that mattered.
- **Non-ASCII spam keywords are matched without `\b`.** Word boundaries are
  defined against word characters, and Thai, Japanese and Chinese are written
  without spaces, so `\b` either never matches or matches in the wrong place.
- **5xx is not DEAD.** It is usually temporary. It maps to BLOCKED, meaning
  "not judged", so a transient outage cannot land a live site in your disavow.
- **A shared IP is discounted as a footprint signal.** Cheap shared hosting
  genuinely puts thousands of unrelated sites on one address, so the signal only
  counts once RDAP says the owner is *not* a large shared host.
- **The DNS pre-check never decides a domain is dead.** It looks like a
  short-circuit and is deliberately not one: `fetch.check_status` sets
  `dns_said_no` and carries on to HTTP, which is the arbiter. A resolver that is
  restricted or simply wrong would otherwise manufacture DEAD verdicts, and that
  is the one error class that costs you working links. Measured cost of the
  confirmation: about a second per genuinely dead domain.
- **`asn.py` has two hosting patterns, not one.** `SHARED_HOSTING_HINTS` covers
  CDNs and mass shared hosting, where one IP fronts thousands of customers and
  "same IP" means nothing. `VPS_HINTS` covers providers where one IP is normally
  one customer's box, and there a shared IP is a real footprint — which is how
  three local-news sites on a single Hetzner address were caught. A VPS match
  wins over a shared match, because mislabelling a VPS throws the signal away.
- **A browser-readable 403 is promoted out of BLOCKED.** The original status is
  kept in `original_status_code` / `original_status_verdict`, so the promotion is
  visible rather than silent.
- **`split_host()` strips a leading `www.` before matching suffixes.** Without
  it, any host whose parent is itself in `MULTI_SUFFIXES` breaks:
  `www.medium.com` resolved to `www.medium.com` rather than `medium.com`,
  because `medium.com` is listed as a free-subdomain host. That silently broke
  master-list matching and mis-grouped domains in clustering.
- **`disavow.txt` excludes DEAD and LOW_VALUE rows.** Disavowing a link that is
  merely useless is a known way to hurt your own rankings.
