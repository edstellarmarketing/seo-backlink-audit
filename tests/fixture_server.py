"""
Local fixture server for verifying the audit pipeline end-to-end.

Serves deliberately-crafted pages covering every case the auditor must handle,
so you can prove the logic works without depending on the live internet or on
a third party's site staying the same.

    python tests/fixture_server.py 8765     # then open http://127.0.0.1:8765/
"""

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGET = "https://www.edstellar.com/courses/leadership"


def _page(title, body, head=""):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{title}</title>{head}</head><body>{body}</body></html>")


FILLER = ("Corporate training programmes help employees build practical skills. "
          "Our workshop covers leadership, communication and upskilling for teams. ") * 18

PAGES = {
    # A healthy, working backlink: followed, relevant, real content.
    "/good": _page(
        "Corporate Training Resources",
        f"<article><h1>Corporate Training Resources</h1><p>{FILLER}</p>"
        f'<p>We recommend <a href="{TARGET}">Edstellar leadership training</a> for teams.</p>'
        "</article>"
        '<nav><a href="/internal-a">More</a><a href="/internal-b">Guides</a></nav>'
        '<a href="https://example.com/x">External ref</a>',
        '<meta name="robots" content="index, follow">'),

    # Link present and followed, but only in the sitewide footer -- Google
    # discounts boilerplate links heavily, so this must not score like /good.
    "/sitewide": _page(
        "Local Business Blog",
        f"<article><h1>An Unrelated Article</h1><p>{FILLER}</p></article>"
        f'<footer><p>Partners: <a href="{TARGET}">Edstellar</a></p></footer>'),

    # Link present but rel=nofollow -> passes no ranking signal.
    "/nofollow": _page(
        "Training Links",
        f"<h1>Useful Training Links</h1><p>{FILLER}</p>"
        f'<p><a href="{TARGET}" rel="nofollow noopener">Edstellar corporate training</a></p>'),

    # rel=sponsored plus "write for us" / "guest post" paid-link markers.
    "/sponsored": _page(
        "Partner Feature",
        f"<h1>Partner Feature</h1><p>{FILLER}</p>"
        f'<p>Sponsored post: <a href="{TARGET}" rel="sponsored">Edstellar</a></p>'
        "<p>Write for us and submit a guest post to our blog.</p>"),

    # Page is alive but the link was removed -> LINK_LOST, an outreach job.
    "/removed": _page(
        "Training Resources (updated)",
        f"<h1>Training Resources</h1><p>{FILLER}</p>"
        '<p>See also <a href="https://someone-else.com/x">another provider</a>.</p>'),

    # noindex: Google never sees the link, so it is worth nothing.
    "/noindex": _page(
        "Hidden Resource Page",
        f'<h1>Resources</h1><p>{FILLER}</p><p><a href="{TARGET}">Edstellar</a></p>',
        '<meta name="robots" content="noindex, follow">'),

    # Bad neighbourhood: gambling content around the link.
    "/casino": _page(
        "Best Online Casino Bonus 2026",
        "<h1>Best Casino Bonus</h1>"
        "<p>Play casino games, poker and roulette. Huge jackpot slots and betting "
        "offers. Our sportsbook has the best casino bonus. Casino, casino, poker, "
        "roulette, baccarat and betting every day. Jackpot!</p>"
        f'<p><a href="{TARGET}">training</a></p>'),

    # Parked / expired / for-sale domain.
    "/parked": _page(
        "example - domain for sale",
        "<h1>This domain is for sale</h1><p>Buy this domain today. Inquire now.</p>"),

    # Link farm: 340 outbound links plus directory-submission language.
    "/linkfarm": _page(
        "Free Web Directory - Submit Your Site",
        "<h1>Web Directory</h1><p>Submit your site to our free directory. Add url now.</p>"
        + "".join(f'<a href="https://site{i}.example/">Site {i}</a> ' for i in range(340))
        + f'<a href="{TARGET}">Edstellar</a>'),

    # Thin content.
    "/thin": _page("Links", f'<h1>Links</h1><p><a href="{TARGET}">Edstellar</a></p>'),

    # The link exists only after JavaScript runs. The plain fetcher sees no
    # link here and would report LINK_LOST; the render fallback finds it.
    "/jslink": _page(
        "Client-Rendered Resources",
        f"<article><h1>Resources</h1><p>{FILLER}</p><div id=\"slot\"></div></article>"
        "<script>document.addEventListener('DOMContentLoaded',function(){"
        "document.getElementById('slot').innerHTML="
        "'<p>See <a href=\"" + TARGET + "\">Edstellar training</a> for details.</p>';"
        "});</script>"),

    # Link buried in a display:none block -> cloaking.
    "/hidden": _page(
        "Article",
        f"<h1>Article</h1><p>{FILLER}</p>"
        f'<div style="display:none"><a href="{TARGET}">Edstellar</a></div>'),
}

# Status-code fixtures, handled separately from the HTML pages.
STATUS_ROUTES = {
    "/404": (404, b"<h1>Not Found</h1>"),
    "/410": (410, b"<h1>Gone</h1>"),
    "/403": (403, b"<h1>Forbidden</h1>"),
    "/500": (500, b"<h1>Server Error</h1>"),
}

REDIRECTS = {
    "/redirect": "/good",
    "/chain1": "/chain2",
    "/chain2": "/chain3",
    "/chain3": "/good",
}
TEMP_REDIRECTS = {"/chain2"}          # served as 302, to mix permanent/temporary


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 plus an explicit close. Keep-alive on a test server only invites
    # the client's connection pool to hold a socket open, which stalls teardown.
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass                                   # keep test output readable

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _route(self):
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path == "/robots.txt":
            return self._send(200, b"User-agent: *\nDisallow: /blocked\n",
                              "text/plain; charset=utf-8")

        if path == "/":
            # A NORMAL home page. This matters: stage 3 scans the site root, so
            # if this listed the fixture paths verbatim ("/casino", "/linkfarm")
            # every single link's home-page check would trip on those words and
            # the whole suite would read as spam. The browsable index lives at
            # /_index instead.
            return self._send(200, _page(
                "Example Publisher",
                f"<article><h1>Example Publisher</h1><p>{FILLER}</p>"
                '<p>A small independent site about workplace learning.</p></article>'
                '<nav><a href="/about">About</a><a href="/contact">Contact</a></nav>'
            ).encode())

        if path == "/_index":
            links = "".join(f'<li><a href="{p}">{p}</a></li>' for p in sorted(PAGES))
            extra = "".join(f"<li>{p}</li>" for p in
                            list(STATUS_ROUTES) + list(REDIRECTS) + ["/blocked"])
            return self._send(200, _page("Fixtures", f"<ul>{links}{extra}</ul>").encode())

        if path in STATUS_ROUTES:
            code, body = STATUS_ROUTES[path]
            return self._send(code, body)

        if path in REDIRECTS:
            code = 302 if path in TEMP_REDIRECTS else 301
            return self._send(code, b"", headers={"Location": REDIRECTS[path]})

        if path == "/blocked":
            # Reachable and carries the link, but robots.txt disallows it.
            return self._send(200, _page(
                "Blocked by robots",
                f'<h1>Blocked</h1><p><a href="{TARGET}">Edstellar</a></p><p>{FILLER}</p>'
            ).encode())

        if path in PAGES:
            return self._send(200, PAGES[path].encode())

        return self._send(404, b"<h1>Not Found</h1>")

    do_GET = do_HEAD = lambda self: self._route()


class FixtureServer(ThreadingHTTPServer):
    """
    daemon_threads=True matters here. Without it, a connection that a requests
    connection pool is still holding open keeps a handler thread alive, and
    ThreadingHTTPServer.shutdown() then blocks forever waiting on that thread.
    """

    daemon_threads = True
    allow_reuse_address = True


def make_server(port: int) -> FixtureServer:
    return FixtureServer(("127.0.0.1", port), Handler)


def serve(port: int = 8765):
    srv = make_server(port)
    print(f"Fixture server on http://127.0.0.1:{port}/  "
          f"(index at /_index, Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        srv.server_close()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
