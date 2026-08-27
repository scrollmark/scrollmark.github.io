#!/usr/bin/env python3
"""Serve the built site locally — the no-Node fallback.

Prefer `npm run dev` (Eleventy's own server): it watches src/ and rebuilds,
so a layout edit shows up without a manual build. This exists for when you
want to serve _site/ without Node in the loop.

Two departures from `python3 -m http.server`, both learned the hard way:

  * Nothing is cached. The default server answers with Last-Modified, and a
    browser will happily keep an old styles.css after you have edited it —
    which reads exactly like a CSS change that did not work, and costs ten
    minutes every time.

  * A missing path serves 404.html with a real 404 status, so the error page
    can be looked at rather than assumed.

Deliberately NOT emulated: extensionless URLs. GitHub Pages may resolve
/skills to skills.html, but this site links every page as .html and that has
not been observed in production yet. A dev server that quietly resolved paths
production might not would hide exactly the kind of break worth catching.

  python3 scripts/dev-server.py [port]
"""

from __future__ import annotations

import http.server
import pathlib
import sys

#: Serves the BUILD, not the sources. Run `npx eleventy` first, or use
#: `npm run dev`, which watches and rebuilds as you edit.
ROOT = pathlib.Path(__file__).resolve().parent.parent / "_site"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        page = ROOT / "404.html"
        if code == 404 and page.is_file():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4321
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler) as srv:
        print(f"serving {ROOT} at http://localhost:{port} (no cache)", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
