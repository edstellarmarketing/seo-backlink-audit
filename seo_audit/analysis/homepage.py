"""
Stage 3: the site's own home page, fetched once per origin.

Separated from the linking-page analysis because it answers a different
question -- not "is this page good" but "is the site around it still what it
claims to be".
"""

import threading
from urllib.parse import urlparse

from seo_audit.analysis import domains as dom
from seo_audit.analysis import page as page_mod
from seo_audit.net import fetch
from seo_audit.scoring import gate as gate_mod


class HomepageCache:
    """
    Fetches and scans each domain's home page ONCE, no matter how many links
    from that domain are in your list.

    Why bother scanning the home page at all? Because of the expired-domain
    flip: someone buys a lapsed domain that still has your link on an old
    article, and repoints the site at an online casino. The article can still
    look perfectly clean while the site around it is spam. Checking only the
    linking page misses that entirely.
    """

    def __init__(self, session, cfg, throttle, dns=None):
        self.session, self.cfg, self.throttle = session, cfg, throttle
        self.dns = dns
        self.cache = {}
        self._lock = __import__("threading").Lock()

    def get(self, origin: str, target: str, aliases) -> dict:
        """
        `origin` is the linking page's own scheme://host[:port]. We deliberately
        do NOT rebuild it as "https://" + registered_domain: that would drop the
        port and force HTTPS, so an http-only site or a non-standard port would
        look dead and get penalised for nothing. It also keeps the comparison
        honest -- for a link on blog.example.com the relevant home page is
        blog.example.com/, not example.com/.
        """
        with self._lock:
            if origin in self.cache:
                return dict(self.cache[origin])

        home_url = origin.rstrip("/") + "/"
        out = {"home_checked": True, "home_url": home_url}

        st = fetch.check_status(self.session, home_url, self.cfg, self.throttle, self.dns)
        out["home_status_code"] = st.get("status_code")
        out["home_status_verdict"] = st.get("status_verdict")
        out["home_error"] = st.get("error", "")

        if st.get("status_verdict") in gate_mod.REACHABLE:
            html, err = fetch.fetch_html(
                self.session, st.get("final_url") or home_url, self.cfg, self.throttle,
                verify=(False if st.get("tls_invalid") else None))
            if err:
                out["home_error"] = err
            else:
                a = page_mod.analyze(html, st.get("final_url") or home_url,
                                     target, aliases, self.cfg)
                out.update({
                    "home_title": a.get("page_title", ""),
                    "home_word_count": a.get("word_count", 0),
                    "home_outbound_links": a.get("outbound_links", 0),
                    "home_lang": a.get("lang", ""),
                    "home_generator": a.get("generator", ""),
                    "home_is_noindex": a.get("is_noindex", False),
                    "home_content_spam": a.get("content_spam", False),
                    "home_content_spam_total": a.get("content_spam_total", 0),
                    "home_content_spam_categories": a.get("content_spam_categories", ""),
                    "home_content_spam_keywords": a.get("content_spam_keywords", ""),
                    "home_parked_markers": a.get("parked_markers", ""),
                    "home_paid_link_markers": a.get("paid_link_markers", ""),
                    "home_link_directory_markers": a.get("link_directory_markers", ""),
                })

        with self._lock:
            self.cache[origin] = dict(out)
        return out


def origin_of(url: str) -> str:
    """scheme://host[:port] for a URL, preserving both scheme and port."""
    pr = urlparse(url if "://" in url else "https://" + url)
    if not pr.netloc:
        return ""
    return f"{pr.scheme or 'https'}://{pr.netloc}"


def _is_homepage(url: str) -> bool:
    """True when the URL is already the site root, so we need no second fetch."""
    pr = urlparse(url if "://" in url else "https://" + url)
    return pr.path.rstrip("/") == "" and not pr.query
