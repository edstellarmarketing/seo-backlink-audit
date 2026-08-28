# TODO

Working list for the SEO Backlink Audit project. Check items off as they land.
Repo: https://github.com/edstellarmarketing/seo-backlink-audit (private)

---

## 1. Dashboard report — organized *and* simple to understand

Keep the HTML dashboard well structured, but make it readable for a
non-technical reader (someone who just wants to know *what to do*), not only
for an SEO specialist.

- [ ] Read `seo_audit/reporting/report.py` end to end; note the current layout,
      sections, filters, and column set.
- [ ] Open a real report (`output/batch30_20260828_1241.html`) and review it in
      the browser to judge clarity as-is.
- [ ] Lead with a plain-English summary: how many links, how many to disavow,
      how many are fine, how many need a look — in one glance.
- [ ] Use plain labels over jargon (or pair jargon with a one-line plain
      explanation). e.g. "Disavow" -> "Remove / reject this link".
- [ ] Make each row's recommended **action** the most prominent thing, with the
      reason in plain words underneath.
- [ ] Keep the eight filters, but group/label them so their purpose is obvious.
- [ ] Verify light/dark and responsive still hold after changes.
- [ ] Re-run `tests/verify_report_ui.py` (headless UI pass) — keep it green.

**Guardrail:** simplify presentation only — do not drop data or change what a
verdict means. Nothing here should alter audit *results*.

## 2. Fix issues in the logic (if found)

Audit the decision logic for real bugs, not style. Confirm each finding with a
concrete failing case before changing anything.

- [ ] `seo_audit/pipeline.py` — stage ordering and short-circuit: is a link ever
      condemned/cleared before the deciding stage runs?
- [ ] `seo_audit/scoring/gate.py` + `score.py` — thresholds, tie-breaks, and the
      "sheet says X but live check says Y" contradiction path.
- [ ] `seo_audit/scoring/anchors.py`, `network_footprint.py` — clustering and
      anchor-profile edge cases (empty input, single domain, duplicates).
- [ ] `seo_audit/analysis/*` — spam rules, homepage flip detection, relevance,
      domain/subdomain stripping (cross-check against `tests/run_tests.py`).
- [ ] `seo_audit/net/*` — fetch ladder, DNS-never-condemns rule, 5xx = BLOCKED
      (not DEAD), backoff.
- [ ] For every real bug: add/extend a case in `tests/` that fails first, then
      fix, then confirm the whole suite passes (`python tests/run_tests.py`).

**Guardrail:** the "deliberate choices worth not undoing" in `COMMIT_MSG.txt`
are intentional — don't reclassify them as bugs.

---

### Working method
- One concern per commit; push after each so progress is visible.
- Keep `python tests/run_tests.py` green throughout.
- Note anything deferred or out-of-scope here rather than silently dropping it.
