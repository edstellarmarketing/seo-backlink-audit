"""
Hosting-network lookup, to tell shared hosting apart from one operator's box.

The PBN detector groups domains by shared IP. That signal is genuinely useful
and genuinely ambiguous: cheap shared hosting really does put thousands of
unrelated sites behind one address, so "same IP" on its own is not evidence of
anything. Knowing WHO owns the address is what resolves it -- forty domains on
a single IP at a big shared host is ordinary; forty domains on one IP inside a
small VPS range is a footprint.

Uses RDAP, which is the public successor to whois: keyless, free, no account.
Results cache to disk, keyed by IP, because they effectively never change.

If the lookup is unavailable -- no network, rate limited, switched off in
config -- everything degrades quietly: the ASN column is empty and clustering
falls back to the signals it had before.
"""

import json
import os
import re
import threading
import time

import requests

# RDAP bootstrap. ARIN redirects to the right registry for non-ARIN space,
# and requests follows that, so one endpoint covers the whole address space.
RDAP_URL = "https://rdap.arin.net/registry/ip/{ip}"

# Two very different kinds of "shared" address, and conflating them loses
# information in both directions.
#
# MASS_SHARED: CDNs and mass shared hosting, where one IP fronts thousands of
# unrelated customers. "Same IP" here means nothing at all.
MASS_SHARED = (
    r"cloudflare|cloudflarenet|akamai|fastly|amazon|aws|google|microsoft|azure|"
    r"incapsula|imperva|sucuri|stackpath|bunny|keycdn|alibaba|tencent|"
    r"godaddy|namecheap|hostgator|bluehost|siteground|dreamhost|wpengine|"
    r"shopify|squarespace|wix|automattic|wordpress|unified layer|newfold|"
    r"endurance|a2 hosting|ionos|1and1|strato|hostinger|namesilo"
)

# VPS_DEDICATED: providers where one IP normally belongs to ONE customer's
# machine. Several "unrelated" sites on a single address here is a footprint,
# not a coincidence -- which is exactly how three local-news sites sharing one
# Hetzner IP were caught. Treating these as shared hosting would have
# discounted the strongest signal in that batch.
VPS_DEDICATED = (
    r"hetzner|contabo|vultr|linode|digitalocean|ovh|scaleway|upcloud|"
    r"hostwinds|ramnode|leaseweb|liquidweb|interserver|buyvm|racknerd|"
    r"oracle|choopa|constant company|servarica|netcup"
)

SHARED_HOSTING_HINTS = re.compile(MASS_SHARED, re.IGNORECASE)
VPS_HINTS = re.compile(VPS_DEDICATED, re.IGNORECASE)


class AsnCache:
    def __init__(self, path: str, enabled: bool = True, timeout: float = 8.0,
                 max_lookups: int = 300):
        self.path = path
        self.enabled = bool(enabled)
        self.timeout = float(timeout)
        self.max_lookups = int(max_lookups)
        self.data = {}
        self._lock = threading.Lock()
        self._locks = {}
        self.lookups = 0
        self.failures = 0
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

    def _ip_lock(self, ip):
        with self._lock:
            if ip not in self._locks:
                self._locks[ip] = threading.Lock()
            return self._locks[ip]

    @staticmethod
    def _parse(payload: dict) -> dict:
        """Pull the few fields we care about out of an RDAP response."""
        name = str(payload.get("name") or "")[:80]
        handle = str(payload.get("handle") or "")[:40]
        org = ""
        for ent in payload.get("entities") or []:
            roles = [str(r).lower() for r in (ent.get("roles") or [])]
            if not any(r in roles for r in ("registrant", "administrative", "owner")):
                continue
            for item in ent.get("vcardArray", [None, []])[1] or []:
                if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
                    org = str(item[3])[:80]
                    break
            if org:
                break
        cidr = ""
        for c in payload.get("cidr0_cidrs") or []:
            v = c.get("v4prefix") or c.get("v6prefix")
            if v:
                cidr = f"{v}/{c.get('length')}"
                break
        if not cidr and payload.get("startAddress"):
            cidr = f"{payload['startAddress']}-{payload.get('endAddress','')}"
        label = org or name or handle
        # A VPS provider match wins over a shared-hosting match: some names hit
        # both patterns, and mislabelling a VPS as shared hosting throws away
        # the shared-IP signal entirely.
        is_vps = bool(label and VPS_HINTS.search(label))
        return {
            "net_name": name,
            "net_handle": handle,
            "net_org": org,
            "net_range": cidr[:60],
            "shared_host": bool(label and SHARED_HOSTING_HINTS.search(label)) and not is_vps,
            "vps_host": is_vps,
        }

    EMPTY = {"net_name": "", "net_handle": "", "net_org": "", "net_range": "",
             "shared_host": False, "vps_host": False}

    def lookup(self, ip: str) -> dict:
        if not self.enabled or not ip or ":" in ip:
            return dict(self.EMPTY)
        with self._lock:
            if ip in self.data:
                return dict(self.data[ip])
            if self.lookups >= self.max_lookups:
                return dict(self.EMPTY)

        lock = self._ip_lock(ip)
        with lock:
            with self._lock:
                if ip in self.data:
                    return dict(self.data[ip])
                self.lookups += 1
            rec = dict(self.EMPTY)
            try:
                r = requests.get(RDAP_URL.format(ip=ip), timeout=self.timeout,
                                 headers={"Accept": "application/rdap+json"})
                if r.status_code == 200:
                    rec = self._parse(r.json())
                else:
                    with self._lock:
                        self.failures += 1
            except (requests.RequestException, ValueError):
                with self._lock:
                    self.failures += 1
            with self._lock:
                self.data[ip] = rec
            return dict(rec)

    def stats(self):
        with self._lock:
            shared = sum(1 for v in self.data.values() if v.get("shared_host"))
            named = sum(1 for v in self.data.values() if v.get("net_org") or v.get("net_name"))
            return {"cached_ips": len(self.data), "lookups": self.lookups,
                    "failures": self.failures, "identified": named,
                    "shared_hosts": shared}


def annotate(rows: list, cache: AsnCache) -> None:
    """Attach hosting info to every row that has an IP."""
    for r in rows:
        ip = (r.get("ip") or "").strip()
        info = cache.lookup(ip) if ip else dict(AsnCache.EMPTY)
        r.update(info)
