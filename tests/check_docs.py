#!/usr/bin/env python3
"""
Check the documentation against the code.

Docs drift. Someone adds a report column, a CLI flag or a spam keyword and the
README keeps quoting last month's number, which is worse than quoting none at
all -- a confidently wrong count teaches the reader to distrust the whole
document.

So the claims worth checking are checked mechanically:

  * every number the docs assert (columns, keywords, tests, caches)
  * every CLI flag argparse actually defines
  * every output file the code actually writes
  * the project layout, against the real tree
  * no references to paths or commands that no longer exist

    python tests/check_docs.py

Exits non-zero on a mismatch, and says exactly what to change.
"""

import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []
CHECKS = [0]


def ok(label, condition, detail=""):
    CHECKS[0] += 1
    good = bool(condition)
    print(f"  [{'PASS' if good else 'FAIL'}] {label}" + (f" - {detail}" if not good and detail else ""))
    if not good:
        FAILS.append(f"{label}{' :: ' + detail if detail else ''}")


def read(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        return ""
    return open(path, encoding="utf-8").read()


def main():
    from seo_audit.analysis import classify, spamrules
    from seo_audit.reporting import report

    readme = read("README.md")
    arch = read("ARCHITECTURE.md")
    metrics_readme = read("input/metrics/README.txt")
    docs = {"README.md": readme, "ARCHITECTURE.md": arch,
            "input/metrics/README.txt": metrics_readme}

    print("=" * 74)
    print("  DOCUMENTATION vs CODE")
    print("=" * 74)

    # ---------------- asserted numbers ----------------
    print("\n  Numbers the docs assert:")
    columns = len(report.COLUMNS)
    keywords = sum(len(v) for v in spamrules.CATEGORIES.values())
    authority = len(set(classify.load_authority_domains()))
    caches = len({m for m in re.findall(r"class ([A-Za-z]+Cache)",
                                        "\n".join(read(f) for f in
                                                  glob.glob("seo_audit/**/*.py", recursive=True)))})
    cache_files = glob.glob(os.path.join(ROOT, "seo_audit", "**", "*.py"), recursive=True)
    caches = len({m for f in cache_files
                  for m in re.findall(r"class ([A-Za-z]+Cache)",
                                      open(f, encoding="utf-8").read())})

    for label, value, pattern in [
        ("report columns", columns, r"(\d+)\s+columns"),
        ("spam keywords", keywords, r"(\d+)\s+keywords"),
        ("authority domains", authority, r"~?(\d+)\s+more in"),
    ]:
        found = [int(m) for m in re.findall(pattern, readme)]
        ok(f"README states {value} {label}", value in found or not found,
           f"README says {found}, code says {value}")

    # test count is quoted in a few shapes
    quoted_tests = set(int(m) for m in re.findall(r"(\d+)\s+assertions", readme + arch))
    real_tests = int(subprocess.run(
        [sys.executable, os.path.join(ROOT, "tests", "run_tests.py")],
        capture_output=True, text=True, cwd=ROOT).stdout.count("[PASS]"))
    ok(f"assertion count is current ({real_tests})",
       not quoted_tests or quoted_tests == {real_tests},
       f"docs say {sorted(quoted_tests)}, suite reports {real_tests}")

    quoted_caches = set(int(m) for m in re.findall(r"(\w+|\d+) caches", readme + arch)
                        if m.isdigit())
    words = {"five": 5, "six": 6, "seven": 7, "eight": 8}
    quoted_caches |= {words[m.lower()] for m in re.findall(r"(\w+) caches", readme + arch)
                      if m.lower() in words}
    ok(f"cache count is current ({caches})",
       not quoted_caches or quoted_caches == {caches},
       f"docs say {sorted(quoted_caches)}, code has {caches}")

    # ---------------- CLI flags ----------------
    print("\n  CLI flags:")
    help_text = subprocess.run([sys.executable, "-m", "seo_audit", "--help"],
                               capture_output=True, text=True, cwd=ROOT).stdout
    real_flags = set(re.findall(r"(--[a-z][a-z-]+)", help_text)) - {"--help"}

    # Only count flags the README attributes to THIS tool. The docs also show
    # winget, pip, playwright and gh commands, whose flags are not ours --
    # "--id" from "winget install --id GitHub.cli" was being reported as an
    # invented flag.
    OTHER_TOOLS = re.compile(r"\b(winget|pip|playwright|gh|git|choco|apt|npm|python -m pip)\b")
    documented = set()
    for line in readme.splitlines():
        if OTHER_TOOLS.search(line) and "seo_audit" not in line and "audit.py" not in line:
            continue
        documented |= set(re.findall(r"(--[a-z][a-z-]+)", line))
    undocumented = sorted(real_flags - documented)
    ok("every flag appears in the README", not undocumented,
       f"missing: {undocumented}")
    invented = sorted(documented - real_flags - {"--help"})
    ok("the README invents no flags", not invented, f"not real: {invented}")

    # ---------------- output files ----------------
    print("\n  Output files:")
    cli = read("seo_audit/cli.py")
    written = set(re.findall(r'p\("([a-z_0-9]+\.[a-z]+)"\)', cli))
    for f in sorted(written):
        ok(f"{f} documented", f in readme)
    for stem in ("csv", "xlsx", "html", "json"):
        ok(f"backlink_audit_<time>.{stem} documented",
           f"backlink_audit_<time>.{stem}" in readme)

    # ---------------- layout ----------------
    print("\n  Project layout:")
    real_mods = sorted(
        os.path.relpath(f, ROOT).replace(os.sep, "/")
        for f in glob.glob(os.path.join(ROOT, "seo_audit", "**", "*.py"), recursive=True)
        if not f.endswith("__init__.py"))
    missing_layout = [m for m in real_mods
                      if os.path.basename(m) not in readme
                      and os.path.basename(m) not in arch]
    ok("every module is named in the docs", not missing_layout,
       f"missing: {missing_layout}")

    for d in ("input/", "output/", "history/", "cache/", "data/"):
        ok(f"{d} explained in the README", d.rstrip("/") in readme)

    # The docs themselves are excluded: a README listing its own filename is
    # noise, not information.
    self_docs = {"README.md", "ARCHITECTURE.md"}
    for f in sorted(x for x in os.listdir(ROOT)
                    if os.path.isfile(os.path.join(ROOT, x))
                    and not x.startswith(".") and x not in self_docs):
        ok(f"{f} mentioned in the README", f in readme)

    # ---------------- stale references ----------------
    print("\n  Stale references:")
    stale_patterns = [
        (r"python src[/\\]audit\.py", "old entry point python src/audit.py"),
        (r"src[/\\][a-z_]+\.py", "path into the removed src/ folder"),
        (r"sample_report", "removed sample_report folder"),
        (r"\b55 assertions\b", "outdated assertion count"),
        (r"\b118 assertions\b", "outdated assertion count"),
        (r"\b64 columns\b", "outdated column count"),
        (r"\b139 keywords\b", "outdated keyword count"),
    ]
    for name, text in docs.items():
        for pattern, why in stale_patterns:
            hits = re.findall(pattern, text)
            ok(f"{name}: no {why}", not hits, f"found {hits[:3]}")

    # ---------------- verdicts and statuses ----------------
    print("\n  Verdicts and statuses:")
    for v in report.VERDICT_ORDER:
        ok(f"verdict {v} documented", v in readme)
    for sv in ("DNS_ERROR", "SSL_ERROR", "REDIRECT_PERM", "RATE_LIMITED", "GONE"):
        ok(f"status {sv} documented", sv in readme)

    # ---------------- config keys ----------------
    print("\n  Config keys:")
    import yaml
    cfg = yaml.safe_load(read("config.yaml"))
    for section in ("pipeline", "network", "scoring", "content",
                    "network_footprint", "anchors", "metrics", "output", "database"):
        ok(f"config section '{section}' referenced", section in readme)
    for key in cfg.get("pipeline", {}):
        ok(f"pipeline.{key} documented", key in readme)
    for key in cfg.get("database", {}):
        ok(f"database.{key} documented", key in readme)

    print("\n" + "=" * 74)
    if FAILS:
        print(f"  {len(FAILS)} of {CHECKS[0]} DOC CHECK(S) FAILED")
        for f in FAILS:
            print(f"    - {f}")
        print("=" * 74)
        return 1
    print(f"  ALL {CHECKS[0]} DOC CHECKS PASSED")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
