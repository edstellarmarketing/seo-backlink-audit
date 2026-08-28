"""
HTTP fetching: status codes, redirect chains, and polite rate limiting.

Design notes
------------
* We deliberately capture the FIRST response without following redirects, so a
  301 is reported as a 301 -- not as the 200 it eventually lands on. That
  distinction is the whole point of a backlink status audit: a link pointing at
  a redirect still works for users but leaks a little authority and often means
  your URL structure changed.
* HEAD is tried first (cheap, no body). Many servers mishandle HEAD, so we fall
  back to GET on 4xx/405/501 or on any exception.
* A per-host lock + delay keeps us from hammering one server when a list has
  many URLs on the same domain -- that is what gets you blocked or rate-limited.
* 5xx is reported as SERVER_ERROR, distinct from DEAD (4xx). A 503 is often
  temporary; a 404 is not. Treating them the same makes you disavow live sites.
"""

import threading
import time
from collections import defaultdict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from seo_audit.analysis import domains as dom

# --------------------------------------------------------------------------
# Per-host politeness
# --------------------------------------------------------------------------
class HostThrottle:
    """
    Ensures a minimum gap between requests to the same host, and widens that gap
    automatically for hosts that push back.

    A fixed delay is the wrong shape for a real backlink list. Most hosts are
    fine at the configured pace; a handful start answering 429 or 503, and
    without adaptation the run keeps hammering exactly the hosts that asked it
    to stop -- which is how you get an IP blocked and a column of false DEADs.
    So each 429/503 doubles that host's delay (up to a ceiling) and each clean
    response decays it back toward the configured value.
    """

    def __init__(self, delay: float = 1.0, max_delay: float = 15.0,
                 recover: float = 0.85):
        self.base_delay = max(0.0, float(delay))
        self.max_delay = max(self.base_delay, float(max_delay))
        self.recover = min(max(float(recover), 0.1), 0.99)
        self._last = defaultdict(float)
        self._delay = {}                      # host -> current delay
        self._locks = defaultdict(threading.Lock)
        self._guard = threading.Lock()
        self.throttled_hosts = {}             # host -> peak delay reached
        self.pushback_count = 0

    # ---- read/write current delay for a host -------------------------
    def _delay_for(self, host: str) -> float:
        with self._guard:
            return self._delay.get(host, self.base_delay)

    def _set_delay(self, host: str, value: float):
        with self._guard:
            self._delay[host] = value
            if value > self.base_delay:
                prev = self.throttled_hosts.get(host, 0)
                self.throttled_hosts[host] = max(prev, value)

    def _lock_for(self, host):
        with self._guard:
            return self._locks[host]

    def wait(self, url: str):
        host = dom.host_of(url)
        if not host:
            return
        delay = self._delay_for(host)
        if delay <= 0:
            return
        lock = self._lock_for(host)
        with lock:
            elapsed = time.time() - self._last[host]
            if elapsed < delay:
                time.sleep(delay - elapsed)
            self._last[host] = time.time()

    # ---- feedback from responses -------------------------------------
    def note_response(self, url: str, status_code, retry_after=None):
        """
        Feed a status code back in. 429/503 widens this host's delay;
        anything healthy lets it decay back toward the configured pace.
        """
        host = dom.host_of(url)
        if not host:
            return
        current = self._delay_for(host)

        if status_code in (429, 503):
            with self._guard:
                self.pushback_count += 1
            wanted = max(current * 2, max(self.base_delay, 1.0) * 2)
            # Honour Retry-After when the server bothered to send one.
            try:
                if retry_after is not None:
                    wanted = max(wanted, min(float(retry_after), self.max_delay))
            except (TypeError, ValueError):
                pass
            self._set_delay(host, min(wanted, self.max_delay))
        elif status_code and 200 <= int(status_code) < 400 and current > self.base_delay:
            self._set_delay(host, max(self.base_delay, current * self.recover))

    def stats(self):
        with self._guard:
            return {
                "pushback_responses": self.pushback_count,
                "throttled_hosts": len(self.throttled_hosts),
                "worst_delay": round(max(self.throttled_hosts.values()), 1)
                               if self.throttled_hosts else self.base_delay,
                "hosts": dict(sorted(self.throttled_hosts.items(),
                                     key=lambda kv: -kv[1])[:8]),
            }


# --------------------------------------------------------------------------
# Session factory
# --------------------------------------------------------------------------
def make_session(cfg: dict) -> requests.Session:
    net = cfg.get("network", {})
    s = requests.Session()
    s.headers.update({
        "User-Agent": net.get("user_agent", "Mozilla/5.0 BacklinkAudit/2.0"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    retry = Retry(
        total=net.get("retries", 2),
        connect=net.get("retries", 2),
        read=net.get("retries", 2),
        backoff_factor=0.7,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["HEAD", "GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=net.get("concurrency", 8) * 2,
        pool_maxsize=net.get("concurrency", 8) * 2,
    )
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.max_redirects = net.get("max_redirects", 10)
    return s


def normalize_url(url: str) -> str:
    u = (url or "").strip().strip('"').strip("'")
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u.lstrip("/")
    return u


# --------------------------------------------------------------------------
# Status verdicts
# --------------------------------------------------------------------------
def status_verdict(code) -> str:
    """Map an HTTP status code to a coarse verdict."""
    if code is None:
        return "ERROR"
    if 200 <= code < 300:
        return "LIVE"
    if code in (301, 308):
        return "REDIRECT_PERM"
    if code in (302, 303, 307):
        return "REDIRECT_TEMP"
    if code in (300, 304):
        return "LIVE"
    if code in (401, 403):
        return "BLOCKED"       # exists but refuses us -- NOT dead
    if code == 410:
        return "GONE"
    if code == 429:
        return "RATE_LIMITED"
    if 400 <= code < 500:
        return "DEAD"
    if 500 <= code < 600:
        return "SERVER_ERROR"
    return "ERROR"


def error_verdict(error_text: str) -> str:
    """
    Classify a connection failure. This distinction matters: a domain with no
    DNS record is genuinely gone, but a domain whose TLS certificate is broken
    still exists and still serves - we simply could not read it. Calling the
    second one "dead" would have you disavowing a live site.
    """
    e = (error_text or "").lower()
    if "dns" in e or "does not resolve" in e:
        return "DNS_ERROR"
    if "ssl" in e or "certificate" in e:
        return "SSL_ERROR"
    return "ERROR"


def _short_error(exc: Exception) -> str:
    name = type(exc).__name__
    msg = str(exc)
    if "Name or service not known" in msg or "nodename nor servname" in msg:
        return "DNS: domain does not resolve"
    if "certificate verify failed" in msg or "SSLError" in name:
        return "SSL certificate error"
    if "Connection refused" in msg:
        return "connection refused"
    if "timed out" in msg.lower() or "Timeout" in name:
        return "timeout"
    if "Exceeded" in msg and "redirect" in msg.lower():
        return "too many redirects (redirect loop)"
    if "Connection aborted" in msg or "RemoteDisconnected" in msg:
        return "connection aborted by server"
    return f"{name}: {msg.split('(')[0].strip()[:110]}"


def _request(session, method, url, timeout, allow_redirects, verify, stream=False):
    return session.request(
        method, url, timeout=timeout, allow_redirects=allow_redirects,
        verify=verify, stream=stream,
    )


def _probe(session, url, timeout, verify):
    """
    One status probe with redirects NOT followed. HEAD first (cheap), falling
    back to GET for the many servers that mishandle HEAD.
    Returns (response, exception).
    """
    try:
        r = _request(session, "HEAD", url, timeout, False, verify)
        if r.status_code in (400, 403, 405, 406, 429, 501, 502):
            r = _request(session, "GET", url, timeout, False, verify, stream=True)
            r.close()
        return r, None
    except requests.RequestException:
        try:
            r = _request(session, "GET", url, timeout, False, verify, stream=True)
            r.close()
            return r, None
        except requests.RequestException as e:
            return None, e


def _ladder(url: str, base_verify: bool):
    """
    The order in which we try to reach a URL.

    This ladder exists because of a real false negative: pressreleasepoint.com
    is a perfectly live site, but one client's TLS stack could not complete its
    handshake, and a single strict HTTPS attempt reported it as dead. Declaring
    a site gone because of OUR transport problem is the worst kind of error in
    an audit -- it sends you to disavow a working link.

    So: strict HTTPS, then HTTPS with verification relaxed (tells cert problems
    apart from "server is down"), then plain HTTP (many older sites are
    http-only). The first attempt that returns ANY HTTP status wins; a 404 is a
    real answer and stops the ladder immediately.
    """
    from urllib.parse import urlparse, urlunparse
    pr = urlparse(url)
    https_url = urlunparse(("https",) + tuple(pr[1:]))
    http_url = urlunparse(("http",) + tuple(pr[1:]))

    if pr.scheme == "http":
        return [(http_url, base_verify, "http"),
                (https_url, base_verify, "https"),
                (https_url, False, "https-noverify")]
    return [(https_url, base_verify, "https"),
            (https_url, False, "https-noverify"),
            (http_url, base_verify, "http")]


def check_status(session, url: str, cfg: dict, throttle: HostThrottle | None = None,
                 dns=None) -> dict:
    """
    Check one URL's HTTP status and redirect chain. Never raises.

    Pass `dns` (a resolve.DnsCache) to short-circuit domains that do not
    resolve: a dead domain then costs one millisecond instead of a full
    connect timeout per retry.
    """
    net = cfg.get("network", {})
    timeout = net.get("timeout", 20)
    base_verify = net.get("verify_ssl", True)

    url = normalize_url(url)
    out = {
        "checked_url": url,
        "host": dom.host_of(url),
        "status_code": None,
        "status_verdict": "ERROR",
        "final_status": None,
        "final_url": "",
        "redirect_hops": 0,
        "redirect_chain": "",
        "redirect_offsite": False,
        "redirect_target_domain": "",
        "response_ms": None,
        "content_type": "",
        "error": "",
        "https": url.startswith("https://"),
        "scheme_used": "",
        "tls_invalid": False,
        "https_unavailable": False,
        "ip": "",
        "ips": "",
        "attempts": "",
        "dns_said_no": False,
    }
    if not url:
        out["error"] = "empty URL"
        return out

    # ---- DNS first: a domain that does not exist needs no HTTP at all ----
    if dns is not None:
        rec = dns.resolve(out["host"])
        out["ips"] = ", ".join(rec["ips"][:4])
        out["ip"] = rec["ips"][0] if rec["ips"] else ""
        if not rec["resolved"]:
            # A failed lookup is a hint, not a verdict. Our resolver may be
            # restricted -- serock.info resolved for one network and not
            # another -- and inventing a dead domain is the worst error this
            # tool can make, because it sends you to disavow a working link.
            # So we carry on and let the HTTP attempt decide. It costs almost
            # nothing: a name that genuinely does not resolve fails the request
            # in milliseconds as well.
            out["dns_said_no"] = True
            out["error"] = rec["dns_error"]

    t0 = time.time()
    resp, tried, first_err = None, [], None

    for attempt_url, verify, label in _ladder(url, base_verify):
        if throttle:
            throttle.wait(attempt_url)
        r, err = _probe(session, attempt_url, timeout, verify)
        tried.append(label if r is not None else f"{label}:fail")
        if r is not None:
            resp = r
            out["checked_url"] = attempt_url
            out["scheme_used"] = label
            out["https"] = attempt_url.startswith("https://")
            if label == "https-noverify":
                out["tls_invalid"] = True
            if label == "http" and url.startswith("https://"):
                out["https_unavailable"] = True
            break
        if first_err is None:
            first_err = err

    out["attempts"] = " -> ".join(tried)
    out["response_ms"] = int((time.time() - t0) * 1000)

    if resp is None:
        out["error"] = _short_error(first_err) if first_err else "connection failed"
        out["status_verdict"] = error_verdict(out["error"])
        # DNS and HTTP now agree the name is gone, which is a real DEAD.
        if out["dns_said_no"]:
            out["status_verdict"] = "DNS_ERROR"
            out["error"] = "domain does not resolve (confirmed by DNS and HTTP)"
        return out

    out["status_code"] = resp.status_code
    out["status_verdict"] = status_verdict(resp.status_code)
    if out["dns_said_no"]:
        # Our resolver was wrong. Worth recording rather than hiding, because
        # a resolver that lies once will lie again.
        out["error"] = ""
        out["dns_note"] = ("our DNS lookup failed but the site answered anyway - "
                           "the resolver, not the domain, was the problem")
    out["content_type"] = (resp.headers.get("Content-Type") or "").split(";")[0]
    out["server"] = (resp.headers.get("Server") or "")[:60]
    if throttle is not None:
        throttle.note_response(out["checked_url"], resp.status_code,
                               resp.headers.get("Retry-After"))

    verify_for_follow = not out["tls_invalid"] and base_verify

    # ---- follow redirects, so we know where the link actually lands ----
    if out["status_verdict"].startswith("REDIRECT"):
        if throttle:
            throttle.wait(out["checked_url"])
        try:
            r2 = _request(session, "GET", out["checked_url"], timeout, True,
                          verify_for_follow, stream=True)
            r2.close()
            hops = [h.url for h in r2.history] + [r2.url]
            out["final_url"] = r2.url
            out["final_status"] = r2.status_code
            out["redirect_hops"] = len(r2.history)
            out["redirect_chain"] = " -> ".join(hops)
            out["content_type"] = ((r2.headers.get("Content-Type") or "").split(";")[0]
                                   or out["content_type"])
            out["redirect_offsite"] = (
                dom.registered_domain(out["checked_url"]) != dom.registered_domain(r2.url))
            if out["redirect_offsite"]:
                out["redirect_target_domain"] = dom.registered_domain(r2.url)
        except requests.RequestException as e:
            out["final_url"] = resp.headers.get("Location", "")
            out["error"] = f"redirect target unreachable ({_short_error(e)})"
    else:
        out["final_url"] = out["checked_url"]
        out["final_status"] = resp.status_code

    return out


def check_root_domain(session, url: str, cfg: dict, throttle=None, dns=None) -> dict:
    """
    Probe the registered root domain. Used when a subdomain URL fails, to tell
    'this one page/subdomain broke' apart from 'the whole site is gone'.
    """
    root = dom.registered_domain(url)
    if not root:
        return {"root_domain": "", "root_verdict": "", "root_status": None, "root_note": ""}

    r = check_status(session, "https://" + root, cfg, throttle, dns)
    alive = r["status_verdict"] in ("LIVE", "REDIRECT_PERM", "REDIRECT_TEMP", "BLOCKED")
    if alive:
        note = f"Root domain {root} is reachable ({r['status_code']}) - the failure is limited to this page/subdomain."
    else:
        note = f"Root domain {root} is also down ({r['status_verdict']}) - the whole site is likely gone."
    return {
        "root_domain": root,
        "root_verdict": r["status_verdict"],
        "root_status": r["status_code"],
        "root_note": note,
    }


def fetch_html(session, url: str, cfg: dict, throttle=None, max_bytes: int = 900_000,
               verify: bool | None = None):
    """
    Download a page's HTML for analysis. Returns (html_str, error_str).
    Skips non-HTML content types and truncates very large pages.
    """
    net = cfg.get("network", {})
    timeout = net.get("timeout", 20)
    if verify is None:
        verify = net.get("verify_ssl", True)
    url = normalize_url(url)
    if not url:
        return "", "empty URL"

    if throttle:
        throttle.wait(url)
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True,
                        verify=verify, stream=True)
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype and "html" not in ctype and "xml" not in ctype and "text" not in ctype:
            r.close()
            return "", f"non-HTML content ({ctype.split(';')[0]})"
        raw = r.raw.read(max_bytes, decode_content=True) or b""
        enc = r.encoding or r.apparent_encoding or "utf-8"
        r.close()
        return raw.decode(enc, errors="ignore"), ""
    except requests.RequestException as e:
        return "", _short_error(e)
    except Exception as e:                      # noqa: BLE001 - never kill a run
        return "", f"read error: {type(e).__name__}"
