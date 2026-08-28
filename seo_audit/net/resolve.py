"""
DNS resolution, cached and shared across threads.

Two reasons this exists.

1. SPEED. On a real backlink list a large share of domains are simply gone.
   Without a DNS pre-check, each dead domain costs a full connect timeout --
   20 seconds by default, times retries. On a list of 1,247 domains where half
   are dead that is hours of pure waiting. getaddrinfo fails in milliseconds,
   so resolving first turns those hours into seconds.

2. PBN DETECTION. Once we know each domain's IP we can spot the footprint of a
   link network: forty "unrelated" sites sharing one address are not unrelated.

Resolution is cached per host for the life of the run, so a hundred links from
one domain cost one lookup.
"""

import socket
import threading


class DnsCache:
    def __init__(self, timeout: float = 5.0):
        self._cache = {}
        self._lock = threading.Lock()
        self._locks = {}
        self.timeout = timeout

    def _host_lock(self, host):
        with self._lock:
            if host not in self._locks:
                self._locks[host] = threading.Lock()
            return self._locks[host]

    def resolve(self, host: str) -> dict:
        """
        Returns {resolved: bool, ips: [str], dns_error: str}.

        IMPORTANT: a False here is a HINT, not a verdict. This resolver can be
        restricted or simply wrong -- exactly that happened with serock.info,
        which one network could not resolve while another fetched the page
        fine. So `fetch.check_status` never condemns a domain on this alone; it
        still makes an HTTP attempt and lets that be the arbiter. The cost is
        negligible, because a name that does not resolve fails an HTTP attempt
        in milliseconds too: it is domains that resolve and then hang that are
        slow, and those are unaffected.

        What the pre-check still buys: the IP for network-footprint detection,
        a clean error message, and skipping the HEAD/GET fallback dance.
        Never raises.
        """
        host = (host or "").strip().lower().rstrip(".")
        if not host:
            return {"resolved": False, "ips": [], "dns_error": "empty host"}

        with self._lock:
            if host in self._cache:
                return dict(self._cache[host])

        lock = self._host_lock(host)
        with lock:
            # Another thread may have filled it while we waited for the lock.
            with self._lock:
                if host in self._cache:
                    return dict(self._cache[host])

            old = socket.getdefaulttimeout()
            try:
                socket.setdefaulttimeout(self.timeout)
                infos = socket.getaddrinfo(host, None)
                ips = sorted({i[4][0] for i in infos})
                rec = {"resolved": True, "ips": ips, "dns_error": ""}
            except socket.gaierror as e:
                # -2 / -5 are "name does not resolve"; anything else is a
                # resolver problem on OUR side, which must not be reported as
                # "the domain is gone".
                msg = str(e)
                if e.errno in (socket.EAI_NONAME, -2, -5) or "not known" in msg or "No address" in msg:
                    rec = {"resolved": False, "ips": [],
                           "dns_error": "domain does not resolve (NXDOMAIN)"}
                else:
                    rec = {"resolved": False, "ips": [],
                           "dns_error": f"DNS lookup failed: {msg[:80]}"}
            except (socket.timeout, OSError) as e:
                rec = {"resolved": False, "ips": [],
                       "dns_error": f"DNS timeout/error: {type(e).__name__}"}
            finally:
                socket.setdefaulttimeout(old)

            with self._lock:
                self._cache[host] = rec
            return dict(rec)

    def stats(self):
        with self._lock:
            total = len(self._cache)
            ok = sum(1 for v in self._cache.values() if v["resolved"])
        return {"hosts": total, "resolved": ok, "unresolved": total - ok}


def subnet24(ip: str) -> str:
    """The /24 of an IPv4 address, for spotting same-block hosting."""
    if not ip or ":" in ip:
        return ""
    parts = ip.split(".")
    return ".".join(parts[:3]) + ".0/24" if len(parts) == 4 else ""
