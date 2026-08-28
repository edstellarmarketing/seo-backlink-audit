"""
On-page analysis: is the backlink actually there, and is the page any good?

This is the part most cheap backlink tools skip, and it is the part that
matters most. A 200 OK only proves the page loads. It does not prove:
  * your link is still on it          (removed links are extremely common)
  * the link is followed              (nofollow passes no ranking signal)
  * Google is allowed to index it     (noindex = the link is invisible to SEO)
  * the page is content, not a link farm
"""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from seo_audit.analysis import domains as dom
from seo_audit.analysis import relevance as relevance_mod
from seo_audit.analysis import spamrules

_WS = re.compile(r"\s+")
_HIDDEN = re.compile(
    r"(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|"
    r"text-indent\s*:\s*-\d{4}|opacity\s*:\s*0(?!\.)|height\s*:\s*0px)",
    re.IGNORECASE,
)


# Containers that mean "this link is on every page of the site", not "someone
# chose to cite you in an article". Google devalues sitewide boilerplate links
# heavily, so an audit that scores a footer link the same as an editorial
# in-article mention is telling you something false.
BOILERPLATE_TAGS = {"footer", "nav", "aside", "header"}
BOILERPLATE_HINTS = re.compile(
    r"(footer|sidebar|side-bar|widget|blogroll|partner|sponsor|nav|menu|"
    r"breadcrumb|related-sites|link-list|linklist|directory|banner|advert)",
    re.IGNORECASE)
CONTENT_TAGS = {"article", "main"}
CONTENT_HINTS = re.compile(
    r"(article|post-content|entry-content|content-body|story|main-content|"
    r"post-body|blog-post|textwidget-none)", re.IGNORECASE)


def _placement(anchor_tag) -> str:
    """
    Classify where a link sits: 'in-content', 'boilerplate' or 'unknown'.

    Walks up the ancestor chain and takes the FIRST decisive signal, because
    the nearest container is the most meaningful: a <a> inside
    <article><aside class="related"> is boilerplate, not content.
    """
    for parent in list(anchor_tag.parents)[:8]:
        name = getattr(parent, "name", "") or ""
        if name in BOILERPLATE_TAGS:
            return "boilerplate"
        attrs = parent.attrs if hasattr(parent, "attrs") else {}
        ident = " ".join([
            " ".join(attrs.get("class", []) if isinstance(attrs.get("class"), list)
                     else [str(attrs.get("class", ""))]),
            str(attrs.get("id", "")),
            str(attrs.get("role", "")),
        ])
        if ident.strip():
            if BOILERPLATE_HINTS.search(ident):
                return "boilerplate"
            if CONTENT_HINTS.search(ident):
                return "in-content"
        if name in CONTENT_TAGS:
            return "in-content"
        if name == "body":
            break
    return "unknown"


def _target_hosts(target_site: str, aliases=None) -> set:
    """Build the set of registered domains that count as 'my site'."""
    hosts = set()
    for t in [target_site] + list(aliases or []):
        if not t:
            continue
        reg = dom.registered_domain(str(t))
        if reg:
            hosts.add(reg)
    return hosts


def _visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    return _WS.sub(" ", soup.get_text(" ", strip=True))


def analyze(html: str, page_url: str, target_site: str, aliases=None,
            cfg: dict | None = None) -> dict:
    """
    Parse a page and report everything relevant to a backlink audit.
    Never raises -- a malformed page returns an 'error' field instead.
    """
    cfg = cfg or {}
    content_cfg = cfg.get("content", {}) or {}
    out = {
        # link verification
        "link_found": False,
        "link_count": 0,
        "anchor_texts": "",
        "link_rel": "",
        "is_nofollow": False,
        "is_sponsored": False,
        "is_ugc": False,
        "is_followed": False,
        "link_target_urls": "",
        "link_in_hidden_block": False,
        "link_placement": "",
        "link_is_sitewide": False,
        # indexability
        "meta_robots": "",
        "is_noindex": False,
        "is_nofollow_page": False,
        "canonical": "",
        "canonical_mismatch": False,
        # content
        "page_title": "",
        "meta_description": "",
        "h1": "",
        "word_count": 0,
        "lang": "",
        "generator": "",
        "lang_mismatch": False,
        "outbound_links": 0,
        "internal_links": 0,
        "internal_urls": [],
        "total_links": 0,
        "outbound_ratio": 0.0,
        "hidden_text": False,
        "relevance_score": 0,
        "relevance_matched": "",
        "relevance_missing": "",
        # spam
        "content_spam": False,
        "content_spam_total": 0,
        "content_spam_categories": "",
        "content_spam_keywords": "",
        "parked_markers": "",
        "paid_link_markers": "",
        "link_directory_markers": "",
        "error": "",
    }
    if not html:
        out["error"] = "no HTML to analyse"
        return out

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:                       # noqa: BLE001
            out["error"] = f"parse failed: {type(e).__name__}"
            return out

    # ---------------- indexability -----------------------------------
    robots_vals = []
    for m in soup.find_all("meta"):
        name = (m.get("name") or m.get("property") or "").lower()
        if name in ("robots", "googlebot"):
            robots_vals.append((m.get("content") or "").lower())
    out["meta_robots"] = ", ".join(v for v in robots_vals if v)
    joined = out["meta_robots"]
    out["is_noindex"] = "noindex" in joined or "none" in joined
    out["is_nofollow_page"] = "nofollow" in joined or "none" in joined

    can = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, str) else " ".join(v)).lower())
    if can and can.get("href"):
        out["canonical"] = urljoin(page_url, can["href"])
        try:
            a = urlparse(out["canonical"])
            b = urlparse(page_url)
            out["canonical_mismatch"] = (a.netloc, a.path.rstrip("/")) != (b.netloc, b.path.rstrip("/"))
        except Exception:
            pass

    # ---------------- basic content ----------------------------------
    if soup.title and soup.title.string:
        out["page_title"] = _WS.sub(" ", soup.title.string).strip()[:300]
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if md and md.get("content"):
        out["meta_description"] = _WS.sub(" ", md["content"]).strip()[:400]
    h1 = soup.find("h1")
    if h1:
        out["h1"] = _WS.sub(" ", h1.get_text(" ", strip=True))[:250]
    gen = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
    if gen and gen.get("content"):
        out["generator"] = _WS.sub(" ", gen["content"]).strip()[:120]

    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        out["lang"] = str(html_tag["lang"])[:12]

    out["hidden_text"] = bool(_HIDDEN.search(html))

    text = _visible_text(soup)
    out["word_count"] = len(text.split())

    # ---------------- link inventory ---------------------------------
    page_reg = dom.registered_domain(page_url)
    targets = _target_hosts(target_site, aliases)

    internal = external = 0
    matches, anchors, rels, hrefs = 0, [], set(), []
    internal_urls = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(page_url, href)
        reg = dom.registered_domain(absolute)
        if not reg:
            continue
        if reg == page_reg:
            internal += 1
            # Keep a handful of internal URLs so sitewide sampling has
            # somewhere to look. Skip anchors back to this same page.
            if len(internal_urls) < 25 and absolute.split("#")[0] != page_url.split("#")[0]:
                internal_urls.append(absolute.split("#")[0])
        else:
            external += 1

        if reg in targets:
            matches += 1
            atext = _WS.sub(" ", a.get_text(" ", strip=True))[:120]
            anchors.append(atext or "[image/empty anchor]")
            rel = a.get("rel") or []
            rel = [rel] if isinstance(rel, str) else list(rel)
            for r in rel:
                for part in str(r).lower().split():
                    rels.add(part)
            hrefs.append(absolute)
            # where does this link sit? in-content beats boilerplate.
            place = _placement(a)
            if place == "in-content" or not out["link_placement"]:
                out["link_placement"] = place
            # is this link buried in a hidden container?
            for parent in list(a.parents)[:5]:
                style = (parent.get("style") or "") if hasattr(parent, "get") else ""
                if style and _HIDDEN.search(style):
                    out["link_in_hidden_block"] = True
                    break

    out["internal_links"] = internal
    out["internal_urls"] = list(dict.fromkeys(internal_urls))[:25]
    out["outbound_links"] = external
    out["total_links"] = internal + external
    out["outbound_ratio"] = round(external / max(1, internal + external), 3)

    out["link_count"] = matches
    out["link_found"] = matches > 0
    out["anchor_texts"] = " | ".join(dict.fromkeys(anchors))[:500]
    out["link_target_urls"] = " | ".join(dict.fromkeys(hrefs))[:600]
    out["link_rel"] = ", ".join(sorted(rels))
    out["is_nofollow"] = "nofollow" in rels
    out["is_sponsored"] = "sponsored" in rels
    out["is_ugc"] = "ugc" in rels
    out["is_followed"] = out["link_found"] and not (out["is_nofollow"] or out["is_sponsored"] or out["is_ugc"])

    out["link_is_sitewide"] = out["link_placement"] == "boilerplate"

    # ---------------- language ---------------------------------------
    expected = [str(x).lower().strip() for x in (content_cfg.get("expected_languages") or [])]
    if expected and out["lang"]:
        primary = out["lang"].lower().split("-")[0].strip()
        out["lang_mismatch"] = bool(primary) and primary not in [e.split("-")[0] for e in expected]

    # ---------------- spam / markers ---------------------------------
    cscan = spamrules.scan_content(text)
    out["content_spam"] = cscan["spammy"]
    out["content_spam_total"] = cscan["total"]
    out["content_spam_categories"] = ", ".join(cscan["categories"])
    out["content_spam_keywords"] = ", ".join(cscan["top_keywords"])

    markers = spamrules.scan_markers(text[:20000])
    out["parked_markers"] = ", ".join(markers["parked"][:3])
    out["paid_link_markers"] = ", ".join(markers["paid_link"][:3])
    out["link_directory_markers"] = ", ".join(markers["link_directory"][:3])

    # ---------------- topical relevance ------------------------------
    kws = content_cfg.get("relevance_keywords") or []
    if kws:
        rel = relevance_mod.score(
            {
                "title": out["page_title"],
                "h1": out["h1"],
                "meta": out["meta_description"],
                "anchor": out["anchor_texts"],
                "body": text[:8000],
            },
            kws,
            content_cfg.get("relevance_synonyms") or {},
        )
        out["relevance_score"] = rel["score"]
        out["relevance_matched"] = rel["detail"]
        out["relevance_missing"] = ", ".join(rel["missing"][:8])

    return out
