"""
Wayback recovery for dead links.

When a page 404s the audit can say "gone" and stop, which is true but useless
for doing anything about it. What makes a reclamation email work is knowing
what the page WAS: its title, and the anchor text it used for your link. Then
the pitch stops being "you had a link to us somewhere" and becomes "your 2023
guide to X linked to us as Y; that page now 404s, here is where it should
point".

Uses the Wayback availability API (keyless, free) to find the closest snapshot,
then optionally fetches that snapshot and looks for your link in it.

Opt-in, cached, and quiet on failure -- if archive.org is unreachable the DEAD
verdict stands exactly as before.
"""

import json
import os
import threading

import requests

AVAILABILITY = "https://archive.org/wayback/available"


class ArchiveCache:
    EMPTY = {
        "archive_available": False,
        "archive_url": "",
        "archive_date": "",
        "archive_title": "",
        "archive_link_found": False,
        "archive_anchor": "",
        "archive_note": "",
    }

    def __init__(self, path: str, enabled: bool = True, timeout: float = 12.0,
                 max_lookups: int = 200, fetch_snapshot: bool = True):
        self.path = path
        self.enabled = bool(enabled)
        self.timeout = float(timeout)
        self.max_lookups = int(max_lookups)
        self.fetch_snapshot = bool(fetch_snapshot)
        self.data = {}
        self._lock = threading.Lock()
        self.lookups = 0
        self.found = 0
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.data = {}

    def save(self):
        if not self.data:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def recover(self, url: str, session, cfg, target: str, aliases) -> dict:
        if not self.enabled or not url:
            return dict(self.EMPTY)
        with self._lock:
            if url in self.data:
                return dict(self.data[url])
            if self.lookups >= self.max_lookups:
                return dict(self.EMPTY)
            self.lookups += 1

        rec = dict(self.EMPTY)
        try:
            r = requests.get(AVAILABILITY, params={"url": url},
                             timeout=self.timeout,
                             headers={"User-Agent": "BacklinkAudit/2.0"})
            r.raise_for_status()
            snap = ((r.json().get("archived_snapshots") or {}).get("closest") or {})
            if snap.get("available") and snap.get("url"):
                rec["archive_available"] = True
                rec["archive_url"] = snap["url"]
                ts = str(snap.get("timestamp") or "")
                rec["archive_date"] = (f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
                                       if len(ts) >= 8 else ts)
                with self._lock:
                    self.found += 1
            else:
                rec["archive_note"] = "no snapshot in the Wayback Machine"
        except (requests.RequestException, ValueError) as e:
            rec["archive_note"] = f"archive lookup failed: {type(e).__name__}"

        # Read the snapshot to recover the title and the anchor text used.
        if rec["archive_available"] and self.fetch_snapshot and target:
            try:
                from seo_audit.net import fetch as fetch_mod
                from seo_audit.analysis import page as page_mod
                html, err = fetch_mod.fetch_html(session, rec["archive_url"], cfg, None)
                if not err and html:
                    a = page_mod.analyze(html, rec["archive_url"], target, aliases, cfg)
                    rec["archive_title"] = a.get("page_title", "")[:200]
                    rec["archive_link_found"] = bool(a.get("link_found"))
                    rec["archive_anchor"] = a.get("anchor_texts", "")[:200]
                    if rec["archive_link_found"]:
                        rec["archive_note"] = (
                            f"snapshot from {rec['archive_date']} still shows your link"
                            + (f' as "{rec["archive_anchor"][:60]}"'
                               if rec["archive_anchor"] else "")
                            + " - use this in your outreach")
                    else:
                        rec["archive_note"] = (
                            f"snapshot from {rec['archive_date']} exists but shows no link "
                            f"to you - the link may have been removed before the page died")
                else:
                    rec["archive_note"] = f"snapshot found but not readable ({err or 'empty'})"
            except Exception as e:                  # noqa: BLE001
                rec["archive_note"] = f"snapshot read failed: {type(e).__name__}"

        with self._lock:
            self.data[url] = rec
        return dict(rec)

    def stats(self):
        with self._lock:
            return {"lookups": self.lookups, "snapshots_found": self.found,
                    "cached": len(self.data)}
