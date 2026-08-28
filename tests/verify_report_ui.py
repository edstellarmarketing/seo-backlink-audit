"""
Functionally verify the HTML report's interactive filters in a real browser.

The other test suite proves the report FILE is written and contains the right
markup. It cannot prove the dropdowns actually filter anything -- that is
JavaScript, and only a browser can answer it. This does.

    python tests/verify_report_ui.py                    # newest report in output/
    python tests/verify_report_ui.py path/to/report.html

Needs Playwright, which is optional:  pip install playwright && playwright install chromium
If it is missing the script says so and exits 0, so it never breaks your build.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright is not installed - skipping the browser UI check.")
    print("  pip install playwright && playwright install chromium")
    sys.exit(0)


def newest_report() -> str:
    """The most recent HTML report in output/, or '' if there is none."""
    out_dir = os.path.join(ROOT, "output")
    if not os.path.isdir(out_dir):
        return ""
    reports = [os.path.join(out_dir, f) for f in os.listdir(out_dir)
               if f.endswith(".html")]
    if not reports:
        return ""
    return max(reports, key=os.path.getmtime)


PATH = sys.argv[1] if len(sys.argv) > 1 else newest_report()
if not PATH or not os.path.exists(PATH):
    print("No HTML report found to check.\n"
          "Run an audit first:  python -m seo_audit --limit 5\n"
          "Or point this at one: python tests/verify_report_ui.py path/to/report.html")
    sys.exit(0)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {got}" + ("" if ok else f" (wanted {want})"))
    if not ok:
        fails.append(label)


print(f"Checking {os.path.basename(PATH)} in a headless browser...")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page()
    pg.goto("file://" + os.path.abspath(PATH))

    total = pg.locator("#tb tr.row").count()
    visible = lambda: pg.eval_on_selector_all(
        "#tb tr.row", "els => els.filter(e => e.style.display !== 'none').length")
    count_text = lambda: pg.inner_text("#count")

    print(f"\nLoaded report: {total} rows")
    check("all rows visible initially", visible(), total)

    selects = pg.locator(".fsel select")
    n_sel = selects.count()
    check("eight dropdowns rendered", n_sel, 8)
    groups = pg.eval_on_selector_all(
        ".fsel select", "els => els.map(e => e.getAttribute('data-g'))")
    check("dropdown groups", groups,
          ["action", "verdict", "status", "tier", "stage", "placement",
           "network", "known"])

    # --- pick real options rather than assuming which verdicts exist ---
    # A small report may contain no TOXIC rows at all, so hard-coding option
    # values makes this test fail on perfectly good output. Read what the
    # dropdowns actually offer and drive those.
    def options_for(group):
        return pg.eval_on_selector_all(
            f'select[data-g="{group}"] option',
            "els => els.map(e => e.value).filter(v => v !== 'ALL')")

    v_opts = options_for("verdict")
    s_opts = options_for("status")
    check("verdict dropdown offers real options", len(v_opts) > 0, True)
    check("status dropdown offers real options", len(s_opts) > 0, True)

    # --- one filter narrows, and only matching rows survive ---
    first_v = v_opts[0]
    pg.select_option('select[data-g="verdict"]', first_v)
    n_v = visible()
    check(f"verdict={first_v} narrows or holds", 0 < n_v <= total, True)
    shown_v = pg.eval_on_selector_all(
        "#tb tr.row", "els => [...new Set(els.filter(e=>e.style.display!=='none')"
                  ".map(e=>e.getAttribute('data-verdict')))]")
    check(f"only {first_v} rows shown", shown_v, [first_v])
    check("count text updates", f"of {total} shown" in count_text(), True)
    check("active-filter note shown", "filter(s) active" in count_text(), True)
    check("select marked active",
          pg.eval_on_selector('select[data-g="verdict"]',
                              "e => e.classList.contains('active')"), True)

    # --- two dropdowns combine with AND ---
    pg.select_option('select[data-g="verdict"]', "ALL")
    first_s = s_opts[0]
    pg.select_option('select[data-g="status"]', first_s)
    n_s = visible()
    pg.select_option('select[data-g="verdict"]', first_v)
    n_both = visible()
    check("combining two filters never widens the result", n_both <= n_s, True)
    rows_both = pg.eval_on_selector_all(
        "#tb tr.row", "els => els.filter(e=>e.style.display!=='none')"
                  ".map(e=>[e.getAttribute('data-status'),e.getAttribute('data-verdict')])")
    check("every visible row matches BOTH filters",
          all(r == [first_s, first_v] for r in rows_both), True)

    # --- search stacks on top of the dropdowns ---
    pg.select_option('select[data-g="verdict"]', "ALL")
    pg.fill("#q", "zzz-no-such-text-zzz")
    check("nonsense search shows nothing", visible(), 0)
    pg.fill("#q", "")
    check("clearing the search restores the filtered set", visible(), n_s)

    # --- reset ---
    pg.click("#reset")
    check("reset restores all rows", visible(), total)
    check("reset clears the search box", pg.input_value("#q"), "")
    check("reset clears every dropdown",
          pg.eval_on_selector_all(".fsel select", "els => els.every(e => e.value === 'ALL')"),
          True)
    check("no dropdown left marked active",
          pg.eval_on_selector_all(".fsel select",
                                  "els => els.every(e => !e.classList.contains('active'))"),
          True)

    # --- master-list tagging ---
    known_opts = options_for("known")
    check("master-list filter offers options", len(known_opts) > 0, True)
    tagged = pg.locator(".tag:has-text('existing data')").count()
    fresh = pg.locator(".tag:has-text('new domain')").count()
    check("every row is tagged known or new", tagged + fresh >= total, True)

    # --- action queue drives the table ---
    todos = pg.locator(".todo-item")
    n_todo = todos.count()
    check("action queue rendered", n_todo >= 1, True)
    if n_todo:
        todos.nth(0).click()
        pg.wait_for_timeout(120)
        n_after = visible()
        check("clicking an action filters the table", 0 < n_after <= total, True)
        check("it set the action dropdown",
              pg.eval_on_selector('select[data-g="action"]', "e => e.value") != "ALL", True)
        pg.click("#reset")

    # --- expandable row detail ---
    check("every data row has a detail row",
          pg.locator("#tb tr.detail").count(), total)
    check("detail starts hidden",
          pg.eval_on_selector("#tb tr.detail", "e => e.classList.contains('show')"), False)
    pg.locator("#tb tr.row").nth(0).click()
    pg.wait_for_timeout(120)
    check("clicking a row opens its detail",
          pg.eval_on_selector("#tb tr.detail", "e => e.classList.contains('show')"), True)
    check("detail has content",
          pg.eval_on_selector("#tb tr.detail .dwrap", "e => e.innerText.trim().length > 20"), True)
    pg.locator("#tb tr.row").nth(0).click()
    pg.wait_for_timeout(120)
    check("clicking again closes it",
          pg.eval_on_selector("#tb tr.detail", "e => e.classList.contains('show')"), False)

    # --- severity stripe and score meter encode state in form ---
    check("rows carry a verdict class",
          pg.eval_on_selector("#tb tr.row", "e => /\\bv-[a-z_]+/.test(e.className)"), True)
    check("score meter rendered", pg.locator("#tb tr.row .meter i").count() >= total, True)

    # --- empty state ---
    pg.fill("#q", "zzz-definitely-not-present-zzz")
    pg.wait_for_timeout(120)
    check("empty state appears when nothing matches",
          pg.eval_on_selector("#empty", "e => e.style.display !== 'none'"), True)
    pg.click("#reset")
    check("empty state hides again",
          pg.eval_on_selector("#empty", "e => e.style.display === 'none'"), True)

    # --- keyboard shortcuts ---
    pg.keyboard.press("/")
    check("slash focuses the search box",
          pg.eval_on_selector("#q", "e => e === document.activeElement"), True)
    pg.fill("#q", "a")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(120)
    check("Escape clears the search", pg.input_value("#q"), "")
    check("Escape restores every row", visible(), total)

    # --- export controls exist and are wired ---
    check("Copy URLs button present", pg.locator("#copyurls").count(), 1)
    check("Export CSV button present", pg.locator("#csvbtn").count(), 1)
    check("rows carry export data",
          pg.eval_on_selector("#tb tr.row",
                              "e => !!e.getAttribute('data-url') && !!e.getAttribute('data-csv')"), True)

    # --- sorting ---
    if total >= 2:
        pg.click("table.main th:nth-child(4)")   # Score column
        first = pg.eval_on_selector("#tb tr.row td:nth-child(4)", "e => e.innerText.trim()")
        pg.click("table.main th:nth-child(4)")
        second = pg.eval_on_selector("#tb tr.row td:nth-child(4)", "e => e.innerText.trim()")
        # Identical scores can legitimately sort to the same first row, so only
        # a genuine ordering change proves the sort ran.
        scores = pg.eval_on_selector_all(
            "#tb tr.row td:nth-child(4)", "els => els.map(e => e.innerText.trim())")
        check("score column sorts both ways",
              first != second or len(set(scores)) == 1, True)
    else:
        print("  [skip] score sorting needs at least 2 rows")

    # --- no console errors ---
    errs = []
    pg2 = b.new_page()
    pg2.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg2.on("pageerror", lambda e: errs.append(str(e)))
    pg2.goto("file://" + os.path.abspath(PATH))
    pg2.wait_for_timeout(400)
    check("no JavaScript errors", errs, [])

    b.close()

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED: {fails}")
    sys.exit(1)
print("ALL BROWSER CHECKS PASSED")
