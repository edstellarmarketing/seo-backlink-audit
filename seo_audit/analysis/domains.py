"""
Domain parsing without third-party dependencies.

`tldextract` needs a network fetch (or a bundled snapshot) of the Public Suffix
List. To keep this project dependency-light and offline-safe we ship a curated
suffix list covering every TLD you are realistically going to see in a backlink
profile, plus the multi-label suffixes that matter for SEO classification
(co.uk, edu.pe, ac.in, eu.org ...).

Why this matters: getting the registered domain wrong breaks everything
downstream. `zootecnia.uncp.edu.pe` must resolve to `uncp.edu.pe`, not `edu.pe`
and not `pe`. `bing.520.edu.pl` must resolve to `520.edu.pl`.
"""

from urllib.parse import urlparse

# --------------------------------------------------------------------------
# Multi-label public suffixes (longest match wins).
# --------------------------------------------------------------------------
MULTI_SUFFIXES = {
    # United Kingdom
    "co.uk", "org.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk", "sch.uk",
    "ac.uk", "gov.uk", "mod.uk", "nhs.uk", "police.uk", "judiciary.uk",
    # Ireland / Europe
    "gov.ie", "ac.ie", "co.at", "or.at", "ac.at", "gv.at",
    "com.de", "co.de", "gouv.fr", "asso.fr", "com.fr", "tm.fr",
    "com.es", "edu.es", "gob.es", "org.es", "nom.es",
    "com.it", "edu.it", "gov.it", "co.nl", "gov.nl",
    "com.pl", "edu.pl", "gov.pl", "org.pl", "net.pl", "waw.pl", "info.pl",
    "com.ua", "edu.ua", "gov.ua", "org.ua", "net.ua", "kiev.ua",
    "com.ru", "edu.ru", "gov.ru", "org.ru", "net.ru", "ac.ru", "msk.ru",
    "com.ro", "org.ro", "com.gr", "edu.gr", "gov.gr", "org.gr",
    "com.pt", "edu.pt", "gov.pt", "org.pt", "com.cy", "ac.cy", "gov.cy",
    "com.hr", "com.mt", "edu.mt", "gov.mt", "co.rs", "edu.rs", "gov.rs",
    "com.tr", "edu.tr", "gov.tr", "org.tr", "net.tr", "k12.tr", "bel.tr",
    "com.se", "org.se", "com.no", "com.dk", "com.fi", "com.is",
    # Asia-Pacific
    "co.in", "net.in", "org.in", "ac.in", "edu.in", "gov.in", "res.in",
    "firm.in", "gen.in", "ind.in", "mil.in", "nic.in",
    "com.pk", "edu.pk", "gov.pk", "org.pk", "net.pk", "ac.pk",
    "com.bd", "edu.bd", "gov.bd", "org.bd", "net.bd", "ac.bd",
    "com.np", "edu.np", "gov.np", "org.np", "com.lk", "edu.lk", "gov.lk",
    "co.jp", "ac.jp", "go.jp", "or.jp", "ne.jp", "gr.jp", "ed.jp", "lg.jp",
    "co.kr", "ac.kr", "go.kr", "or.kr", "re.kr", "ne.kr", "kr.com",
    "com.cn", "edu.cn", "gov.cn", "net.cn", "org.cn", "ac.cn", "mil.cn",
    "com.tw", "edu.tw", "gov.tw", "org.tw", "net.tw", "idv.tw",
    "com.hk", "edu.hk", "gov.hk", "org.hk", "net.hk", "idv.hk",
    "com.sg", "edu.sg", "gov.sg", "org.sg", "net.sg", "per.sg",
    "com.my", "edu.my", "gov.my", "org.my", "net.my",
    "co.id", "ac.id", "or.id", "go.id", "sch.id", "web.id", "my.id",
    "com.ph", "edu.ph", "gov.ph", "org.ph", "net.ph",
    "com.vn", "edu.vn", "gov.vn", "org.vn", "net.vn", "ac.vn",
    "co.th", "ac.th", "go.th", "or.th", "in.th", "net.th",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "asn.au", "id.au",
    "co.nz", "net.nz", "org.nz", "ac.nz", "govt.nz", "school.nz", "geek.nz",
    "com.kh", "edu.kh", "gov.kh", "com.mm", "com.bn", "edu.bn",
    "com.mo", "edu.mo", "gov.mo", "com.kz", "edu.kz", "gov.kz",
    "com.uz", "com.ge", "edu.ge", "com.mn", "edu.mn", "gov.mn",
    # Middle East
    "com.sa", "edu.sa", "gov.sa", "org.sa", "net.sa", "med.sa", "sch.sa",
    "com.ae", "ac.ae", "gov.ae", "org.ae", "net.ae", "sch.ae",
    "co.il", "ac.il", "gov.il", "org.il", "net.il", "muni.il", "k12.il",
    "com.qa", "edu.qa", "gov.qa", "org.qa", "net.qa",
    "com.kw", "edu.kw", "gov.kw", "org.kw", "com.bh", "edu.bh", "gov.bh",
    "com.om", "edu.om", "gov.om", "com.jo", "edu.jo", "gov.jo",
    "com.lb", "edu.lb", "gov.lb", "com.iq", "edu.iq", "gov.iq",
    "ac.ir", "co.ir", "gov.ir", "org.ir", "sch.ir",
    # Africa
    "co.za", "org.za", "ac.za", "gov.za", "net.za", "web.za", "edu.za",
    "com.ng", "edu.ng", "gov.ng", "org.ng", "net.ng", "sch.ng",
    "com.eg", "edu.eg", "gov.eg", "org.eg", "net.eg", "sci.eg",
    "co.ke", "ac.ke", "go.ke", "or.ke", "sc.ke", "ne.ke",
    "com.gh", "edu.gh", "gov.gh", "org.gh",
    "co.tz", "ac.tz", "go.tz", "or.tz", "co.ug", "ac.ug", "go.ug",
    "com.et", "edu.et", "gov.et", "org.et",
    "com.dz", "edu.dz", "gov.dz", "ac.ma", "co.ma", "gov.ma", "press.ma",
    "com.tn", "edu.tn", "gov.tn", "org.tn", "ac.mu", "co.mu", "gov.mu",
    "co.zw", "ac.zw", "gov.zw", "co.zm", "ac.zm", "gov.zm",
    "com.cm", "gov.cm", "com.sn", "gouv.sn", "com.ci", "gouv.ci",
    "co.bw", "ac.bw", "gov.bw", "co.mz", "ac.mz", "gov.mz",
    "com.na", "edu.na", "com.ao", "edu.ao", "gov.ao",
    # Americas
    "com.br", "net.br", "org.br", "edu.br", "gov.br", "art.br", "blog.br",
    "adv.br", "eng.br", "med.br", "esp.br", "ind.br", "inf.br", "jus.br",
    "com.mx", "edu.mx", "gob.mx", "org.mx", "net.mx",
    "com.ar", "edu.ar", "gob.ar", "org.ar", "net.ar", "int.ar", "mil.ar",
    "com.co", "edu.co", "gov.co", "org.co", "net.co", "mil.co", "nom.co",
    "com.pe", "edu.pe", "gob.pe", "org.pe", "net.pe", "nom.pe", "mil.pe",
    "com.ve", "edu.ve", "gob.ve", "org.ve", "net.ve", "web.ve",
    "com.ec", "edu.ec", "gob.ec", "org.ec", "net.ec", "fin.ec", "med.ec",
    "com.cl", "gob.cl", "gov.cl", "com.uy", "edu.uy", "gub.uy", "org.uy",
    "com.py", "edu.py", "gov.py", "org.py", "com.bo", "edu.bo", "gob.bo",
    "com.do", "edu.do", "gob.do", "org.do", "com.gt", "edu.gt", "gob.gt",
    "com.sv", "edu.sv", "gob.sv", "com.hn", "edu.hn", "gob.hn",
    "com.ni", "edu.ni", "gob.ni", "com.pa", "edu.pa", "gob.pa", "ac.pa",
    "com.cu", "edu.cu", "gob.cu", "com.pr", "edu.pr", "gov.pr",
    "co.cr", "ac.cr", "go.cr", "ed.cr", "fi.cr", "or.cr",
    "com.jm", "edu.jm", "gov.jm", "com.tt", "edu.tt", "gov.tt",
    "com.bz", "edu.bz", "gov.bz", "com.bs", "edu.bs", "gov.bs",
    "com.bb", "edu.bb", "gov.bb", "com.gy", "edu.gy", "gov.gy",
    "com.ai", "com.ag", "com.vc", "com.lc", "com.gd", "com.dm", "com.kn",
    # Generic / free-hosting suffixes that are true public suffixes
    "eu.org", "us.org", "za.org", "ae.org", "us.com", "uk.com", "eu.com",
    "gb.com", "de.com", "jpn.com", "br.com", "cn.com", "ru.com", "sa.com",
    "se.com", "uy.com", "no.com", "hu.com", "qc.com", "gr.com",
    "github.io", "gitlab.io", "netlify.app", "vercel.app", "pages.dev",
    "workers.dev", "herokuapp.com", "firebaseapp.com", "web.app",
    "azurewebsites.net", "cloudfront.net", "s3.amazonaws.com",
    "blogspot.com", "wordpress.com", "tumblr.com", "weebly.com",
    "wixsite.com", "squarespace.com", "webflow.io", "notion.site",
    "substack.com", "medium.com", "ghost.io", "hashnode.dev",
    "myshopify.com", "bigcartel.com", "sites.google.com",
    "on.aws", "amplifyapp.com", "surge.sh", "neocities.org",
    "readthedocs.io", "glitch.me", "repl.co", "replit.app",
    "000webhostapp.com", "altervista.org", "byethost.com", "hostinger.site",
    "infinityfreeapp.com", "epizy.com", "freehostia.com", "awardspace.net",
}

# --------------------------------------------------------------------------
# Free-subdomain / dynamic-DNS hosts.
# A "domain" on one of these is not really a domain the linker owns -- it's a
# free subdomain. Very common in low-quality/auto-generated link networks.
# Treated as a spam signal rather than a suffix.
# --------------------------------------------------------------------------
FREE_SUBDOMAIN_HOSTS = {
    # dynamic DNS
    "zapto.org", "no-ip.org", "no-ip.com", "noip.me", "ddns.net",
    "dyndns.org", "dynu.net", "hopto.org", "myftp.org", "myftp.biz",
    "serveblog.net", "servebeer.com", "servegame.com", "serveftp.com",
    "serveminecraft.net", "sytes.net", "redirectme.net", "webhop.me",
    "bounceme.net", "freedynamicdns.net", "gotdns.ch", "3utilities.com",
    # free subdomain / free hosting
    "eu.org", "us.org", "altervista.org", "000webhostapp.com", "epizy.com",
    "byethost.com", "freehostia.com", "awardspace.net", "infinityfreeapp.com",
    "hostinger.site", "neocities.org", "glitch.me", "repl.co",
    "blogspot.com", "wordpress.com", "tumblr.com", "weebly.com",
    "wixsite.com", "webnode.page", "jimdosite.com", "yolasite.com",
    "mystrikingly.com", "simplesite.com", "webs.com", "ucoz.com",
    "livejournal.com", "over-blog.com", "canalblog.com", "webflow.io",
}


def _clean_host(url: str) -> str:
    """Extract a bare lower-case hostname from a URL or bare domain."""
    if not url:
        return ""
    s = url.strip()
    if "://" not in s:
        s = "http://" + s
    host = (urlparse(s).hostname or "").lower().strip(".")
    return host


def split_host(url: str):
    """
    Return (subdomain, domain, suffix) for a URL or bare domain.

    >>> split_host("https://zootecnia.uncp.edu.pe/x")
    ('zootecnia', 'uncp', 'edu.pe')
    >>> split_host("www.example.com")
    ('www', 'example', 'com')
    """
    host = _clean_host(url)
    if not host or host.replace(".", "").isdigit():   # bare IP address
        return ("", host, "")

    labels = host.split(".")
    # Drop a leading "www." before looking for the suffix. "www" is never a
    # meaningful subdomain, and leaving it in breaks every host whose parent is
    # itself in MULTI_SUFFIXES: www.medium.com would resolve to
    # "www.medium.com" rather than "medium.com", because medium.com is listed
    # as a free-subdomain host. That silently broke master-list matching and
    # mis-grouped domains in network clustering.
    if len(labels) > 2 and labels[0] == "www":
        labels = labels[1:]
    # Longest multi-label suffix wins: check 4 labels down to 2.
    for n in range(min(4, len(labels) - 1), 1, -1):
        cand = ".".join(labels[-n:])
        if cand in MULTI_SUFFIXES:
            return (".".join(labels[:-(n + 1)]), labels[-(n + 1)], cand)

    if len(labels) >= 2:
        return (".".join(labels[:-2]), labels[-2], labels[-1])
    return ("", host, "")


def registered_domain(url: str) -> str:
    """The domain you would buy / disavow, e.g. 'uncp.edu.pe'."""
    sub, dom, suf = split_host(url)
    return ".".join(p for p in (dom, suf) if p)


def suffix(url: str) -> str:
    """The public suffix, e.g. 'edu.pe' or 'com'."""
    return split_host(url)[2]


def subdomain(url: str) -> str:
    """Subdomain labels, 'www' included."""
    return split_host(url)[0]


def is_real_subdomain(url: str) -> bool:
    """True for blog.example.com, False for example.com and www.example.com."""
    sub = subdomain(url).replace("www", "").strip(".")
    return bool(sub)


def is_free_subdomain(url: str) -> bool:
    """
    True when the site lives on a free-subdomain or dynamic-DNS host,
    e.g. jtwxx1.zapto.org or pinoydailynews.altervista.org.
    """
    host = _clean_host(url)
    for h in FREE_SUBDOMAIN_HOSTS:
        if host.endswith("." + h):
            return True
    return False


def host_of(url: str) -> str:
    return _clean_host(url)
