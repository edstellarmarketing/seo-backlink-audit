"""robots.txt fetching and caching, keyed per origin."""

import threading
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


class RobotsCache:
    """
    Fetch and cache robots.txt per ORIGIN (scheme + host + port).

    Keying on the bare hostname would be wrong twice over: it loses the port
    (so http://host:8080 would read robots.txt from https://host:443) and it
    conflates the http and https origins, which are allowed to differ.
    """

    def __init__(self, session, cfg):
        self.session, self.cfg = session, cfg
        self.cache = {}
        self._lock = __import__("threading").Lock()

    @staticmethod
    def _origin(url: str) -> str:
        pr = urlparse(url if "://" in url else "https://" + url)
        if not pr.netloc:
            return ""
        return f"{pr.scheme or 'https'}://{pr.netloc}"

    def blocked(self, url: str) -> bool:
        origin = self._origin(url)
        if not origin:
            return False

        with self._lock:
            known = origin in self.cache
        if not known:
            rp = RobotFileParser()
            try:
                r = self.session.get(
                    origin + "/robots.txt",
                    timeout=min(10, self.cfg.get("network", {}).get("timeout", 20)),
                    verify=self.cfg.get("network", {}).get("verify_ssl", True),
                    allow_redirects=True,
                )
                # No robots.txt, or an error page, means "nothing disallowed".
                if r.status_code == 200 and len(r.content) < 500_000:
                    rp.parse(r.text.splitlines())
                else:
                    rp = None
            except Exception:                        # noqa: BLE001
                rp = None
            with self._lock:
                self.cache[origin] = rp

        rp = self.cache.get(origin)
        if rp is None:
            return False
        try:
            return not rp.can_fetch("Googlebot", url)
        except Exception:                            # noqa: BLE001
            return False
