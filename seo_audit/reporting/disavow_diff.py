"""
Diff a new disavow candidate against the file already uploaded.

Search Console keeps exactly ONE disavow file per property, and uploading
replaces it wholesale. That makes a fresh file generated with no knowledge of
the current one genuinely dangerous: every domain you disavowed last quarter
and that this run did not re-examine silently stops being disavowed.

So before you upload anything, you want three lists: what this run adds, what
it would remove, and what stays. Removals are the ones to look at hardest --
"not in this run's input" is not the same as "no longer toxic".
"""

import os
import re

_DOMAIN_LINE = re.compile(r"^\s*domain:\s*([^\s#]+)", re.IGNORECASE)


def parse(path_or_text: str, is_text: bool = False) -> set:
    """
    Read a disavow file into a set of entries. Accepts both `domain:x` lines
    and bare URLs, ignores comments and blanks -- Google's own format.
    """
    entries = set()
    if is_text:
        lines = (path_or_text or "").splitlines()
    else:
        if not path_or_text or not os.path.exists(path_or_text):
            return entries
        try:
            with open(path_or_text, encoding="utf-8-sig", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            return entries

    for raw in lines:
        line = raw.split("#")[0].strip()
        if not line:
            continue
        m = _DOMAIN_LINE.match(line)
        if m:
            entries.add("domain:" + m.group(1).strip().lower().lstrip("."))
        elif "." in line and " " not in line:
            entries.add(line.lower())          # a bare URL line
    return entries


def diff(existing_path: str, candidate_path: str) -> dict:
    old = parse(existing_path)
    new = parse(candidate_path)
    return {
        "existing_count": len(old),
        "candidate_count": len(new),
        "added": sorted(new - old),
        "removed": sorted(old - new),
        "unchanged": sorted(old & new),
        "merged": sorted(old | new),
        "have_existing": bool(old),
    }


def write_report(d: dict, path: str, merged_path: str | None = None) -> None:
    """Write a human-readable diff, and optionally a safe merged candidate."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Disavow diff\n#\n")
        if not d["have_existing"]:
            f.write("# No existing disavow file was supplied, so everything below is new.\n")
            f.write("# To compare against what is already live, download your current file\n")
            f.write("# from Search Console and pass it with --existing-disavow.\n#\n")
        f.write(f"# already uploaded : {d['existing_count']}\n")
        f.write(f"# this run proposes: {d['candidate_count']}\n")
        f.write(f"# added            : {len(d['added'])}\n")
        f.write(f"# removed          : {len(d['removed'])}\n")
        f.write(f"# unchanged        : {len(d['unchanged'])}\n#\n")

        f.write("\n## ADDED - new this run\n")
        f.writelines(e + "\n" for e in d["added"]) or None
        if not d["added"]:
            f.write("# (none)\n")

        f.write("\n## REMOVED - in your live file but NOT in this run\n")
        f.write("# Check each one. A domain missing from this run usually means it was\n")
        f.write("# not in your input list, NOT that it became safe. Dropping it from the\n")
        f.write("# upload silently un-disavows it.\n")
        f.writelines(e + "\n" for e in d["removed"]) or None
        if not d["removed"]:
            f.write("# (none)\n")

        f.write("\n## UNCHANGED\n")
        f.writelines(e + "\n" for e in d["unchanged"]) or None
        if not d["unchanged"]:
            f.write("# (none)\n")

    if merged_path:
        with open(merged_path, "w", encoding="utf-8") as f:
            f.write("# Merged disavow candidate - your existing entries PLUS this run's.\n")
            f.write("# This is the safe file to upload: it adds without dropping anything.\n")
            f.write("# Upload: https://search.google.com/search-console/disavow-links\n#\n")
            f.writelines(e + "\n" for e in d["merged"])
