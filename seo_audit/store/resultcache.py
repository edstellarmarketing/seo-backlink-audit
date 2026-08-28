"""
Resume support for long runs.

A 1,247-link audit takes a while. If it dies at link 900 -- laptop sleeps, wifi
drops, someone closes the window -- losing all 900 results is unacceptable, so
completed rows are written to disk as the run proceeds and can be reused on the
next run.

Deliberately conservative: resume is OFF unless you ask for it (`--resume`),
and cached rows expire, because "the link was alive yesterday" is not the same
claim as "the link is alive".
"""

import json
import os
import threading
import time


class ResultCache:
    def __init__(self, path: str, max_age_hours: float = 24.0):
        self.path = path
        # max_age_hours <= 0 means "do not reuse anything". Treating 0 as
        # "never expires" would be a nasty surprise: someone setting
        # resume_hours: 0 plainly wants fresh checks, not eternal ones.
        self.max_age = float(max_age_hours) * 3600
        self.data = {}
        self._lock = threading.Lock()
        self._dirty = 0
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self.data = {}

    def get(self, url: str):
        if self.max_age <= 0:
            return None
        rec = self.data.get(url)
        if not rec:
            return None
        if (time.time() - rec.get("_cached_at", 0)) > self.max_age:
            return None
        row = dict(rec)
        row.pop("_cached_at", None)
        row["from_cache"] = True
        return row

    def put(self, url: str, row: dict, autosave_every: int = 25):
        with self._lock:
            rec = {k: v for k, v in row.items() if not k.startswith("_")}
            rec["_cached_at"] = time.time()
            self.data[url] = rec
            self._dirty += 1
            due = self._dirty >= autosave_every
        if due:
            self.save()

    def save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, default=str)
                os.replace(tmp, self.path)
                self._dirty = 0
            except OSError as e:
                print(f"  ! could not write resume cache: {e}")

    def clear(self):
        with self._lock:
            self.data = {}
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass

    def __len__(self):
        return len(self.data)
