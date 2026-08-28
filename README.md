# SEO Backlink Audit

Audit a list of backlinks and get one clear answer per link: **is it helping
you, doing nothing, or hurting you?**

Built for the case where you have a list of referring sites — `.edu`, `.org`,
Wikipedia, Glassdoor and a long tail of unknowns — and you need to sort the
keepers from the junk without opening hundreds of pages by hand.

---

## How it works: staged, cheapest-first

Work runs in stages, and a link that fails a stage does not go on to the next
one. That ordering is the economy of the whole thing — authority metrics are
the expensive stage, so they only ever run on links that already passed
everything before them.

```
Stage 1   Is the page live?           dead domain / 404 / broken TLS   ->  STOP
   |                                  no content scan, no DA lookup
   v
Stage 2   Is the PAGE content clean?   casino / parked / link farm      ->  STOP
   |                                  noindex / cloaked link           ->  STOP
   v
Stage 3   Is the HOME PAGE clean?      expired-domain flip              ->  STOP
   |                                  (clean article, casino homepage)
   v
Stage 4   DA / PA / Spam Score         only what survived stages 1-3
```

**Stage 3 is the one that earns its keep.** Someone buys a lapsed domain that
still carries your link on an old article and repoints the site at an online
casino. The article still reads fine; the site around it is spam. Checking only
the linking page misses that completely.

On a real batch of 20 referring domains this took DA/PA lookups from 20 down to
**5** — the other 15 were already dead or already spam. `output\da_pa_queue.txt`
therefore contains only the survivors: you check 5 domains, not 20.

Every stage is switchable in `config.yaml` under `pipeline:`, and the report
records which stage each link reached and why it stopped.

---

## What it checks

**1. HTTP status — every code, told apart properly**

| Result | Meaning |
|---|---|
| `LIVE` | 200 |
| `REDIRECT_PERM` / `REDIRECT_TEMP` | 301/308 vs 302/303/307, with the full hop chain and where it lands |
| `DEAD` | 404 and other 4xx |
| `GONE` | 410 |
| `BLOCKED` | 401 / 403 — the page exists but refused us, so it is **not** called dead |
| `SERVER_ERROR` | 5xx — usually temporary, so not called dead either |
| `RATE_LIMITED` | 429 |
| `DNS_ERROR` | The domain does not resolve at all — gone, not just the page |
| `SSL_ERROR` | Resolves and answers, but the certificate is untrusted. **Not** dead |

The first response is captured **without** following redirects, so a 301 is
reported as a 301 rather than the 200 it eventually reaches. When a URL on a
subdomain fails, the root domain is probed too, so you can tell *"this page
broke"* from *"the whole site is gone"*.

**2. Domain trust tier**

| Tier | What it means |
|---|---|
| **A** | Institutional — `.gov` `.edu` `.mil` `.int` and country variants (`.ac.uk`, `.edu.au`, `.gob.pe`, `.gov.in`…). Registration is restricted, so the signal is strong. |
| **B** | Curated high authority — Wikipedia, Glassdoor, Crunchbase, GitHub, major press, and 216 in total in `data/authority_domains.yaml`. Editable. |
| **C** | `.org` `.ngo` `.foundation` — a **weak** signal, deliberately below tier B. See below. |
| **D** | Everything else. Not bad, just unproven until DA/PA says otherwise. |

> **About `.org`:** it has been open registration since the 1990s. Anyone can
> buy one, and link networks buy them in bulk *precisely because* people assume
> `.org` means non-profit. So `.org` starts lower than a curated authority site
> and still goes through every spam check. Tier is a starting point, never the
> verdict — a hacked `.edu` serving casino text scores worse than a clean `.com`.

**3. Is your link actually still there?**

The check most cheap tools skip, and the one that matters most. A 200 OK only
proves the page loads. For every page the audit records whether your URL is
present, the anchor text, and the `rel` attributes — `nofollow`, `sponsored`,
`ugc` — plus whether the link is buried in a `display:none` block (cloaking).

**4. Link placement — in-content vs sitewide boilerplate**

Walking the link's ancestors tells an editorial in-article citation from a
footer/sidebar/blogroll link that appears on every page. Google discounts
sitewide boilerplate heavily, so scoring the two alike would tell you something
false. Detected containers include `<footer>`, `<nav>`, `<aside>` and any
class/id matching sidebar, widget, blogroll, partner, banner and friends.

**5. True sitewide detection, by sampling**

Placement is structural — it cannot tell you a link appears on 400 pages, which
is what "sitewide" actually means. So a few sibling pages per domain are fetched
and checked for the same link. A link on every sampled page is sitewide in fact,
and Google treats that as roughly one link, not four hundred.

**6. Indexability** — `meta robots noindex`, page-level `nofollow`,
`robots.txt` disallow, canonical mismatch. A `noindex` page is invisible to
Google, so a link on it is worth nothing however good the domain looks.

**7. Spam and toxicity** — 225 keywords across 7 categories, matched on the URL
*and* on visible page text.

- **Word boundaries** on Latin terms, so "Essex" never matches "sex" and
  "better" never matches "bet".
- **Non-Latin scripts** are matched as substrings instead, because `\b` is
  meaningless in Thai, Japanese and Chinese, which are written without spaces.
- **Two evidence tiers.** Most terms need a threshold of hits, because a real
  article can legitimately mention "casino" — Wikipedia's gambling article is
  not spam. A smaller set of terms has *no innocent reading* (`situs slot
  gacor`, `deneme bonusu`, `казино`, `온라인카지노`, `indoxxi`) and one hit is
  enough. Deliberately **not** in that set: `buy backlinks`, `link-farm`,
  `write-my-essay` — an SEO article warning people off them uses the same words.

Plus parked/for-sale domains, link-farm outbound counts, directory-submission
language, paid-link markers ("write for us", "sponsored post"), free-subdomain
and dynamic-DNS hosts, and frequently-abused TLDs.

**8. Content scan** — title, meta description, H1, word count, language, CMS /
generator, internal vs outbound link counts.

**9. Relevance, stemmed and synonym-aware**

The naive version fails exactly where it matters: a page about "staff
development programmes" is squarely relevant to a corporate-training site and
scores **zero** against the keyword "employee training". So:

- both sides are **stemmed**, collapsing programmes/programme/program and
  matching British spellings to American ones;
- **synonym groups** mean a concept can be expressed several ways and still
  register — concepts are scored, not strings;
- **fields are weighted**, because a term in the title or anchor text says far
  more than the same term buried in the body.

Still lexical, not semantic, and honest about that — but it no longer returns
zero for an obvious match. Configure under `content.relevance_synonyms`.

**10. Language mismatch** — set `content.expected_languages` and a page in
another language is flagged. A high-DA link from an Indonesian gambling blog is
not relevant to an English corporate-training site.

**11. Link-network (PBN) footprint**

Referring domains are grouped by shared IP, shared /24, CMS fingerprint and
templated title shape, and a cluster is only reported when **more than one**
signal lines up. The value is turning fifteen separate "meh" rows into one
obvious decision: these fifteen sites are one operator, not fifteen opinions.

A keyless **RDAP lookup** identifies who owns each IP, which is what makes the
shared-IP signal trustworthy: forty domains on one Cloudflare address is
ordinary hosting and is discounted automatically; forty on one small VPS is a
footprint. Hosting organisation becomes a clustering signal in its own right
for providers that are not big shared hosts.

**12. Anchor-text distribution**

Per-link anchor text is nearly useless; risk lives in the distribution. Anchors
are classified branded / naked-URL / keyword / generic / image-empty across the
whole profile, and you are warned when one anchor dominates or keyword anchors
outweigh branded ones. Only links actually found on a page are counted — an
anchor you cannot see is not part of your profile.

**13. Wayback recovery for dead links**

When a page 404s, "it's gone" is true but useless. The Wayback Machine
(keyless) is asked what the page used to be, and the snapshot is read for your
link and its anchor text. That turns a dead row into a usable pitch: *your 2023
guide linked to us as X; that page now 404s, here is where it should point.*

**14. DA / PA / Spam Score** — see below.

---

## Speed and reliability

**DNS pre-check.** Every host resolves once, before any HTTP request. A domain
that does not exist then costs about a millisecond instead of a full connect
timeout on every retry. On a list where half the domains are gone — normal for
an old profile — that is the difference between hours and minutes. Resolved IPs
feed the network-footprint detection, so the lookup pays for itself twice.
Disable with `--no-dns-precheck`.

**A failed DNS lookup is a hint, not a verdict.** The pre-check never condemns a
domain on its own — an HTTP attempt always follows, and that is what decides.
This is not theoretical: `serock.info` returned NXDOMAIN on one network while
another fetched the page perfectly. Manufacturing a dead domain is the worst
error this tool can make, because it sends you to disavow a working link. The
cost of insisting on confirmation is about a second per dead domain, measured —
a name that genuinely does not resolve fails an HTTP request just as fast. When
the resolver turns out to have been wrong, the report says so.

**The fetch ladder.** Each URL is tried as strict HTTPS, then HTTPS with
verification relaxed, then plain HTTP. The first attempt returning any HTTP
status wins, and a 404 stops the ladder immediately.

This exists because of a real false negative found while building this:
`pressreleasepoint.com` is a perfectly live site, but one client's TLS stack
could not complete its handshake and a single strict attempt reported it as
**dead**. Declaring a site gone because of *our* transport problem is the worst
error an audit can make — it sends you to disavow a working link. The ladder
reports `SSL_ERROR` / `Bad TLS cert?` / `No HTTPS?` instead of lying, and those
map to BLOCKED (unverifiable) rather than DEAD (gone).

**Browser re-check, for two different problems.** Both are cases where a plain
HTTP client is simply the wrong tool:

- **Links injected by JavaScript** are invisible to an HTTP fetch, so a live
  link reads as `LINK_LOST`.
- **Pages that refuse the crawler** — 401/403/429, or a failed TLS handshake —
  are often perfectly readable in a browser. In one real batch **5 of 30
  domains returned 403** to the crawler while loading fine for a human. Without
  the retry they stay `BLOCKED`: not judged, and quietly left for you.

Either case gets one browser attempt. A page that refuses the crawler but reads
in a browser is promoted out of `BLOCKED` and judged on the browser's view, with
the original status kept in the report so nothing is hidden. This runs as a
short **sequential** pass after the concurrent one, because Playwright's sync
API must be driven from a single thread and only a handful of pages ever need
it. Optional: without Playwright the audit says so and changes nothing.
Switch off with `--no-render` or `pipeline.render_blocked: false`.

**Adaptive rate-limit backoff.** A fixed delay is the wrong shape for a real
list. Most hosts are fine at the configured pace; a few start answering 429 or
503, and without adaptation the run keeps hammering exactly the hosts that asked
it to stop — which is how you get an IP blocked and a column of false DEADs.
Each 429/503 doubles that host's delay (honouring `Retry-After`, up to a
ceiling) and each clean response decays it back.

**Resume.** Completed rows are written to `cache/results_cache.json` as the run
proceeds, so a 1,200-link run that dies at link 900 keeps its 900 results.

```bat
python -m seo_audit --resume      REM reuse rows younger than pipeline.resume_hours
python -m seo_audit --fresh       REM clear the cache and start over
```

Resume is off unless you ask for it, because "the link was alive yesterday" is
not the same claim as "the link is alive". `resume_hours: 0` means do not reuse.

---

## Install

Needs Python 3.10+.

```bat
cd "C:\Users\Surya\Desktop\AI Agents\SEO Agent Backlink Audit"
pip install -r requirements.txt
```

Optional, for the browser re-check and the report UI test:

```bat
pip install playwright
playwright install chromium
```

Verify the install — 262 assertions against a local fixture server, no internet
needed:

```bat
python tests\run_tests.py
```

You want `ALL CHECKS PASSED`. The report's filter dropdowns are JavaScript,
which that suite cannot exercise. To check the interactivity for real, run an
audit first so there is a report to test, then:

```bat
python -m seo_audit --limit 5
python tests\verify_report_ui.py
```

It picks up the newest HTML report in `output\`, or takes a path as an argument.

There is a third check, for the documentation itself:

```bat
python tests\check_docs.py
```

It verifies every number this README asserts, every CLI flag, every output file
and the project layout against the actual code, and fails if any of them has
drifted. Run it after changing anything that these docs describe.

That drives the actual dropdowns and asserts they narrow the table, combine
with AND, work with the search box, reset, sort both ways and raise no JS
errors. Skips cleanly if Playwright is absent.

---

## First-run housekeeping

If you are upgrading from the earlier flat layout, run `cleanup.bat` once. It
removes the superseded `src\` folder and any `__pycache__`, leaves your
`output\`, `history\`, `cache\` and `input\` alone, and finishes by running
the test suite so you can see nothing broke.

---

## Quick start

**1. Set your own site** in `config.yaml`:

```yaml
target_site: "edstellar.com"
```

**2. URLs and bare domains both work, and can be mixed in one file.**

| You give it | It audits | You get |
|---|---|---|
| `https://site.com/article` | that page | everything, including whether your link is still there, its anchor text and whether it is in-article or in the footer |
| `site.com` | the home page | status, tier, spam, content, home page, DA/PA — but *not* link verification, because there is no linking page to check |

Referring **page** URLs are worth the extra effort: link verification,
placement and anchor text are the most valuable checks in the pipeline and they
all need the page the link sits on. Ahrefs and Search Console both export a
"Referring page" column.

Drop a `.csv`, `.xlsx` or `.txt` into `input/`. Column names are auto-detected,
so most exports from Ahrefs / Semrush / Search Console work as-is:

| Column | Aliases |
|---|---|
| URL *(required)* | `url`, `link`, `backlink`, `source url`, `referring page`, `website`, `domain` |
| Target | `target`, `target url`, `destination`, `link to`, `your url` |
| Anchor | `anchor`, `anchor text`, `keyword` |
| Notes | `notes`, `note`, `comment` |

**3. Run it:**

```bat
run.bat                                    REM everything in input\
python -m seo_audit                        REM same thing
python -m seo_audit -i input\sites.csv     REM one file
python -m seo_audit --urls a.com b.org     REM ad-hoc list
python -m seo_audit --limit 20             REM first 20 only, for a trial run
python audit.py --limit 20                 REM if you prefer a script path
```

Every flag:

| Flag | Does |
|---|---|
| `--input FILE`, `-i` | One specific `.csv` / `.xlsx` / `.txt` instead of everything in `input\` |
| `--urls A B C`, `-u` | Audit these URLs directly, no file needed |
| `--config FILE`, `-c` | Use a different config file |
| `--outdir DIR`, `-o` | Write reports somewhere other than `output\` |
| `--workers N`, `-w` | Override `network.concurrency` for this run |
| `--limit N` | Audit only the first N links — use this for your first real run |
| `--no-content` | Skip the page download: status + tier only. Much faster |
| `--no-metrics` | Skip the DA/PA stage entirely |
| `--no-render` | Skip the browser re-check for links that look missing |
| `--no-sitewide` | Skip sitewide sampling |
| `--no-archive` | Skip Wayback lookups for dead links |
| `--no-dns-precheck` | Skip DNS pre-resolution (slower on lists with dead domains) |
| `--queue-only` | Just write `da_pa_queue.txt` and stop, without auditing |
| `--resume` | Reuse cached rows from an interrupted run |
| `--fresh` | Clear the resume cache before starting |
| `--existing-disavow FILE` | Your currently-uploaded disavow file, to diff against |
| `--compare OLD.json NEW.json` | Diff two earlier runs and exit — no auditing |
| `--import-master FILE` | Import a master domain sheet into the database (repeatable) |
| `--db-stats` | Print what the database holds and exit |
| `--no-db` | Ignore the database for this run |
| `--rerun RUN.json` | Re-audit the links from a previous run |
| `--only VERDICTS` | With `--rerun`, only these verdicts, e.g. `BLOCKED,DEAD` |
| `--history DOMAIN` | Show everything the database knows about one domain, and exit |

A useful pattern on a large list: `--no-content` for a fast status sweep, then a
full run restricted to whatever survived.

**4. Read `output\`:**

| File | What it is |
|---|---|
| `backlink_audit_<time>.html` | Visual dashboard. Opens with **What needs doing** — one action per link, each box filtering the table. Then **eight filter dropdowns** — next action, verdict, HTTP status, trust tier, pipeline stage, link placement, link network, master list — combined with AND, plus search, Reset, click-to-sort columns, Copy URLs and Export CSV of whatever is on screen, and a live "N of M shown" count. Every row carries a severity stripe and a score meter, and **clicking a row expands the full findings** for that link. `/` focuses search, `Esc` resets. |
| `backlink_audit_<time>.xlsx` | Workbook: Summary, All links, one sheet per verdict, one per HTTP status group, Authority (A+B), Sitewide links, Anchor text, Link networks. Colour-coded, auto-filtered, frozen headers, 86 columns. |
| `backlink_audit_<time>.csv` | Flat data for anything else. |
| `disavow.txt` | Google disavow file — **TOXIC rows only**. See the warning below. |
| `disavow_diff.txt` | What this run would add, and what it would **remove**, versus your live file. |
| `disavow_merged.txt` | The safe file to upload: your existing entries plus this run's. |
| `changes.csv` | What changed since the previous run. |
| `outreach_list.csv` | Links worth an email, prioritised by DA. |
| `anchor_text.csv` | Anchor distribution, share of profile, type, warnings. |
| `link_networks.csv` | Detected PBN clusters and the signals they share. |
| `da_pa_queue.txt` | Survivors still missing DA/PA, in paste-ready batches. |
| `backlink_audit_<time>.json` | Everything, machine-readable. Copied to `history/` for diffing. |

---

## Your master list, in a database

The project keeps one SQLite file, `data/audit.db`. It holds your master
disavow sheet — around 10,400 domains with DA, Spam Score and a
Spammy / No Issues status — plus every run's results.

Import your sheet once:

```bat
python -m seo_audit --import-master "Master Disavow Sheet  Edstellar Domain Data.csv"
python -m seo_audit --db-stats
```

Column names are auto-detected, so any export of the sheet works. Re-importing
updates existing domains rather than duplicating them, and keeps the date each
one was first recorded. The real sheet has two side-by-side blocks of
Domain/DA/SS/Status columns with the second one empty; the importer takes the
first of each and ignores the duplicates.

### When your sheet and the live check disagree

This is the payoff of re-checking domains you already know, and it happens for
real: `anibookmark.com` sits on your sheet as **No Issues**, while its live
pages carry Parimatch, Mostbet and Bet7k Casino links. That contradiction is a
finding in its own right — it tells you *which rows have gone stale*.

Both directions are surfaced as their own action, ahead of the generic one:

| Flagged as | Means | What to do |
|---|---|---|
| **Recorded clean, now toxic** | Sheet says No Issues, live check found spam | Disavow it *and* correct the row |
| **Recorded clean, now dead** | Sheet says No Issues, domain or page is gone | Update the row |
| **Recorded spammy, now clean** | Sheet says Spammy, nothing is wrong now | You may be disavowing it for nothing — check |

Rows carry a **sheet out of date** tag, and the master-list panel says how many
contradict your records.

### What a match does, and what it deliberately does not do

Every audited link is matched against the list on both its exact host and its
registered domain, so a sheet entry for `blog.example.com` still flags a link on
`example.com`, and vice versa. A match gets an **existing data** tag in the
dashboard, coloured by the status you gave it, and a "Master list" filter lets
you show only what is new to you.

**A match never skips a check.** Status, HTTPS, the redirect chain, the link
itself, the page content and the home page are re-checked every run for every
domain, however well you know it — the entire question is whether it changed
since you last looked. A domain you marked "No Issues" last year that has since
been flipped to a casino will be reported as toxic.

The one thing reuse applies to is **DA and Spam Score**, and only while they are
recent:

```yaml
database:
  reuse_metrics_days: 30
```

Recorded within that window and the number is reused, so the domain never
reaches the paste-and-import queue. Older than that and it goes back into the
queue for a refresh, because a two-year-old DA is not worth trusting. You
already own DA for ~10,400 domains, so in practice the queue only ever contains
genuinely unknown or genuinely stale ones.

After each run, domains the audit newly judges toxic are remembered on the list
(`learn_from_runs`), so next week's audit already knows about them. It only ever
fills a *blank* status — a decision you made by hand is never overwritten.

Turn any of it off with `--no-db`, or `database.enabled: false`.

---

## Verdicts

| Verdict | Meaning | What to do |
|---|---|---|
| **GOOD** | Working for you | Nothing |
| **REVIEW** | Mixed signals | Look at it yourself |
| **LOW_VALUE** | Harmless but passes nothing (nofollow / noindex / thin) | **Do not disavow.** You just get nothing from it. |
| **TOXIC** | Real spam signals | Verify, then disavow |
| **LINK_LOST** | Page is alive, your link was removed | Send an email — outreach, not a disavow |
| **DEAD** | 404 / 410 / no DNS | Ask for a fix, redirect it, or drop it |
| **BLOCKED** | 401 / 403 / 429 / 5xx / broken TLS — could not read it | Open it in a browser, or re-run later |

> **The LOW_VALUE / TOXIC split is the point.** Disavowing a merely useless link
> is a well-known way to hurt your own rankings. `disavow.txt` therefore
> contains **only** TOXIC rows — never LOW_VALUE, LINK_LOST or DEAD.
> Sanity-check every line before you upload. For a site on a free-subdomain host
> the exact host is disavowed (`spammer1.zapto.org`), never the whole provider.

### Before you upload a disavow file

Search Console keeps exactly **one** disavow file per property, and uploading
**replaces** it wholesale. A fresh file generated with no knowledge of the
current one is genuinely dangerous: every domain you disavowed last quarter and
that this run did not re-examine silently stops being disavowed.

So point the audit at your live file and it will tell you what changes:

```bat
python -m seo_audit --existing-disavow "C:\path\to\current-disavow.txt"
```

`disavow_diff.txt` splits it into **added**, **removed** and **unchanged**.
Read the removals hardest — "not in this run's input" is not the same as "no
longer toxic" — then upload `disavow_merged.txt`, which adds without dropping.

---

## The weekly rhythm

A scheduled task sends a Friday-morning reminder (9:00 AM IST) with the
commands to run and what to read, in order. It runs in the cloud, so it prompts
rather than audits — the audit itself needs your machine, its network and its
files.

The Friday routine is:

1. Drop this week's list in `input\`
2. `run.bat`
3. Read `output\` — the newest HTML report, then `changes.csv`, then
   `disavow_diff.txt`
4. If `da_pa_queue.txt` is not empty, paste those batches into a checker and
   drop the result into `input\metrics\`, then re-run

Reply to the reminder to change the day, the time or its contents.

---

## Tracking change over time

Every run writes its JSON into `history/`, and each run automatically diffs
itself against the previous one. `changes.csv` and the console answer the
questions a single snapshot cannot:

- which links **died** since last time
- whose **link was removed** from a page that still loads
- what **went nofollow**
- which domains **turned toxic**, and which **cleared**
- what **recovered**
- **new** referring domains, and ones that vanished from your input

### Re-checking just the awkward ones

Some links come back `BLOCKED` or `DEAD` for reasons that pass — a temporary
5xx, a rate limit, a certificate being renewed. Re-audit only those, straight
from the previous run, without touching the rest:

```bat
python -m seo_audit --rerun history\run_20260828_1228.json --only BLOCKED,DEAD
```

And to see one domain's whole trajectory — what your sheet says about it, and
every verdict it has ever had:

```bat
python -m seo_audit --history anibookmark.com
```

### Comparing two runs

To compare two specific runs without auditing anything:

```bat
python -m seo_audit --compare history\run_A.json history\run_B.json
compare.bat                       REM does the two most recent automatically
```

Links are matched on URL and domains are reported separately, because a
referring page moving to a new URL looks like a death plus a birth at the link
level while the relationship is intact at the domain level. You want both views.

---

## DA / PA / Spam Score

### Why the free checkers cannot be scripted

`tools.guestpostlinks.net` protects its form with **Cloudflare Turnstile** and
**FingerprintJS**; `dapachecker.org` states its free tier uses a **CAPTCHA**.
Automating those submissions means defeating bot detection — it would break the
moment they rotate the challenge, and this project does not do it. Two honest
routes instead.

### Route 1 — paste and import (free, default)

`config.yaml` → `metrics.provider: "import"`

1. Run the audit once. It writes `output\da_pa_queue.txt` with the **surviving**
   domains already split into paste-ready batches.
2. Open a bulk checker and paste one batch — that is what these tools are for:
   - <https://tools.guestpostlinks.net/bulk-da-pa-checker-tool/> (100/batch, no CAPTCHA)
   - <https://www.dapachecker.org/>
   - <https://dapacheckerpro.com/>
3. Save or copy the result table into `input\metrics\` — `.csv`, `.xlsx` or a
   plain-text paste. **Columns are auto-detected**, and all three tools' formats
   are supported. README-style files in that folder are skipped, so instructions
   are never parsed as data.
4. Re-run. Results cache for 30 days, so no domain is checked twice.

### Route 2 — an API (fully automated)

Rename `.env.example` to `.env`, add a key, set `metrics.provider`:

| Provider | Service | Notes |
|---|---|---|
| `moz` | Moz Links API | Genuine DA, PA and Spam Score |
| `dataforseo` | DataForSEO Backlinks | Cheap pay-per-call. Returns *its own* rank (0–1000), rescaled to 0–100 and labelled as such |
| `rapidapi` | Any RapidAPI DA/PA endpoint | **dapacheckerpro sells its own bulk DA/PA/SS API there** — the same data, via the authorised route |

Credentials live in `.env`, never in `config.yaml`. A missing key falls back to
`import` rather than failing. **These three providers have never been exercised
against real credentials** — expect to debug the first call.

---

## Tuning

Everything lives in `config.yaml`; no code changes needed.

- `target_site`, `target_aliases` — what counts as "your" link
- `network.concurrency` — default 8. **Lower to 3–4 if sites start blocking you.**
- `network.delay_per_host`, `max_delay_per_host`, `backoff_recover` — politeness and backoff
- `pipeline.staged`, `check_homepage`, `metrics_only_for_passing`, `noindex_fails_gate`
- `pipeline.dns_precheck`, `dns_timeout`
- `pipeline.render_js`, `render_wait_ms` — browser re-check
- `pipeline.render_blocked` — also retry pages that refused the crawler
- `pipeline.sitewide_sample` — pages sampled per domain (0 = off)
- `pipeline.archive_dead_links`, `archive_max_lookups`
- `pipeline.resume_hours`
- `scoring.tier_base` — starting score per tier
- `scoring.da_weight` — how much real DA outvotes the tier guess (default 0.5)
- `scoring.thresholds` — GOOD / REVIEW cut-offs
- `scoring.penalties` — every deduction, individually adjustable
- `content.relevance_keywords`, `relevance_synonyms`, `expected_languages`
- `content.outbound_warn` / `outbound_bad` — link-farm thresholds
- `network_footprint.min_cluster`, `penalty_per_cluster`, `asn_lookup`
- `anchors.brand_terms`, `max_single_anchor_share`, `max_keyword_share`
- `output.existing_disavow` — your live disavow file
- `database.enabled`, `database.path`
- `database.reuse_metrics_days` — how recent a stored DA must be to be reused
- `database.learn_from_runs` — remember newly-toxic domains
- `database.record_runs` — keep every run's rows for trend queries

Add niche authority sites to `data/authority_domains.yaml`; spam keywords live
in `seo_audit/analysis/spamrules.py`. After changing any rule, re-run
`python tests\run_tests.py`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Lots of `ERROR` / timeouts | Drop `network.concurrency` to 3, raise `network.timeout` |
| Lots of `BLOCKED` (403) | Sites are refusing the crawler. Nothing is wrong with your links — spot-check a few in a browser |
| SSL errors behind a corporate proxy | Set `network.verify_ssl: false` |
| A live site reported dead | Check `Reached via` and `Bad TLS cert?` — the ladder records how it was reached. Genuine DNS failures show as `DNS_ERROR` |
| Live link reported `LINK_LOST` | Install Playwright so the browser re-check can run; the link may be injected by JavaScript |
| `no DA/PA data` on everything | `metrics.provider` is `none`, or `input\metrics\` is empty |
| Fake DA values appeared | Only put real checker exports in `input\metrics\` |
| Run died part-way | Re-run with `--resume` |
| Excel file will not open | Close any existing copy first; Excel locks the file |
| Slow | `--no-content` for a status-only pass, then a full run on what survives |
| Rate limited | The run backs off automatically; the summary reports which hosts pushed back |

---

## Project layout

```
config.yaml                 all settings
.env.example                credential template -> rename to .env
requirements.txt
run.bat / compare.bat       Windows launchers
cleanup.bat                 removes the old src/ folder and caches
push_to_github.bat          push this project to a private GitHub repo
COMMIT_MSG.txt              the commit message that script uses
.gitignore                  keeps secrets, the database and output out of git
audit.py                    convenience launcher (python -m seo_audit is the real one)

input/                      drop your backlink lists here
  metrics/                  drop DA/PA checker exports here
output/                     reports land here
history/                    one JSON per run, for diffing
cache/                      DNS, metrics, ASN, archive and resume caches
data/authority_domains.yaml curated tier-B list (editable)
data/audit.db               your master list + run history (created on import)

seo_audit/
  __init__.py               package docstring and version
  __main__.py               makes `python -m seo_audit` work
  appconfig.py              config.yaml + .env loading
  inputs.py                 reading backlink lists
  pipeline.py               the per-link stages, in order
  cli.py                    entry point and orchestration
  net/
    fetch.py                fetch ladder, status codes, adaptive throttle
    resolve.py              DNS resolution + caching
    robots.py               robots.txt, cached per origin
    render.py               browser fallback for JS-injected links
  analysis/
    domains.py              registered-domain parsing (no tldextract needed)
    classify.py             trust tiers
    page.py                 link verification, indexability, content
    homepage.py             stage 3
    spamrules.py            keyword and marker rules
    relevance.py            stemming, synonyms, field weighting
    sitewide.py             sibling-page sampling
    archive.py              Wayback recovery
  scoring/
    gate.py                 staged gating
    score.py                composite score and verdicts
    anchors.py              anchor distribution
    network_footprint.py    PBN clustering
  providers/
    metrics.py              DA/PA providers + import parser + cache
    asn.py                  hosting lookup (RDAP)
  reporting/
    report.py               xlsx / html / csv / disavow / outreach writers
    rundiff.py              run-over-run comparison
    disavow_diff.py         disavow safety diff
  store/
    database.py             SQLite: master list + run history
    resultcache.py          resume support

tests/
  run_tests.py              262 assertions, no internet required
  check_docs.py             checks these docs against the code
  verify_report_ui.py       drives the report's filters in a real browser
  fixture_server.py         local pages covering every case
```

---

## Version control

`push_to_github.bat` initialises the repository, shows you exactly what will be
committed, and pushes to a private repo. It needs the GitHub CLI signed in
(`winget install --id GitHub.cli`, then `gh auth login`). Edit the `REPO` line
at the top if you want a different owner or name.

What `.gitignore` keeps out, and why:

| Excluded | Reason |
|---|---|
| `.env` | Your API keys. Never commit it. `.env.example` holds the blank template. |
| `data/*.db` | Git cannot diff a binary and it bloats history. `data/master_disavow_sheet.csv` **is** committed, so the database is one command away: `python -m seo_audit --import-master data\master_disavow_sheet.csv` |
| `cache/`, `output/`, `history/` | All regenerable. |
| `input/metrics/*` | Checker exports are scratch data. |

---

## Honest limits

- Scoring is **heuristic**. It triages hundreds of links fast so your attention
  goes where it is needed. It is not a substitute for looking at a page.
- **Always eyeball a link before disavowing it.** Disavow is a blunt instrument.
- DA / PA / Spam Score are third-party estimates, not Google signals. Google
  does not publish a domain authority metric.
- The three metrics providers are **unexercised against real credentials**.
- All 192 checks run against a local fixture server, not the live web. That is a
  stricter test of the logic, but it is not the same as a live run — start with
  `--limit 20`.
- Relevance is lexical, not semantic. It knows the synonyms you give it.
- `BLOCKED` means "we could not read it", not "it is bad".
- Sitewide sampling checks a few pages, not the whole site.
