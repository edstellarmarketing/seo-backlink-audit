"""
JavaScript rendering fallback.

`requests` + BeautifulSoup sees the HTML the server sent. A growing number of
sites inject links client-side -- a React blog, a cookie-gated body, a lazy
"related links" widget -- and for those the link is genuinely on the page for a
human and genuinely absent from the HTML we downloaded. The audit would report
LINK_LOST on a link that is fine, which is the same class of error as calling a
live site dead: it sends you to do work that does not need doing.

So: when the target link is missing from a page that loaded fine, re-check that
one page in a real browser.

WHY THIS IS A SEPARATE SEQUENTIAL PASS
--------------------------------------
Playwright's sync API is not thread-safe -- it must be driven from the thread
that created it, so it cannot be called from inside the audit's thread pool.
It is also far slower than an HTTP GET. Both point the same way: collect the
handful of URLs that need rendering during the concurrent pass, then render
them one after another afterwards. Typically that is a few links out of
hundreds, so the cost is small and predictable.

Playwright is optional. Without it this module reports that and changes nothing.
"""


def available() -> tuple:
    """(is_available, message)"""
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False, ("Playwright is not installed - skipping JS rendering. "
                       "Install with: pip install playwright && playwright install chromium")
    return True, ""


def render_many(urls: list, cfg: dict, wait_ms: int = 1200) -> dict:
    """
    Render each URL in a real browser and return {url: (html, error)}.

    One browser for the whole batch; one page per URL so a hung page cannot
    poison the next. Never raises -- every failure comes back as an error
    string against its URL.
    """
    ok, msg = available()
    if not ok:
        return {u: ("", msg) for u in urls}
    if not urls:
        return {}

    from playwright.sync_api import sync_playwright

    net = cfg.get("network", {}) or {}
    timeout_ms = int(float(net.get("timeout", 20)) * 1000)
    ua = net.get("user_agent") or None
    ignore_https = not bool(net.get("verify_ssl", True))

    out = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--disable-dev-shm-usage"])
            ctx = browser.new_context(
                user_agent=ua,
                ignore_https_errors=True if ignore_https else False,
                viewport={"width": 1280, "height": 900},
            )
            for url in urls:
                page = None
                try:
                    page = ctx.new_page()
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    # Give client-side rendering a moment. networkidle is
                    # tempting but hangs on sites with long-polling or ads.
                    page.wait_for_timeout(wait_ms)
                    out[url] = (page.content(), "")
                except Exception as e:                    # noqa: BLE001
                    out[url] = ("", f"render failed: {type(e).__name__}: {str(e)[:90]}")
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:                 # noqa: BLE001
                            pass
            ctx.close()
            browser.close()
    except Exception as e:                                # noqa: BLE001
        err = f"browser could not start: {type(e).__name__}: {str(e)[:90]}"
        for u in urls:
            out.setdefault(u, ("", err))
    return out
