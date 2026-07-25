#!/usr/bin/env python3
"""Static file server for the Playwright e2e suite.

Replaces a bare ``python -m http.server --directory ui``. Same stdlib-only
constraint (every machine that can run the bot already has python; the suite
deliberately avoids pulling in a second toolchain just to serve files), but with
two fixes that the CLI form cannot express:

1. ``request_queue_size`` — ``socketserver.TCPServer`` defaults the listen
   backlog to **5**. Playwright runs 8 workers by default, each booting a page
   that immediately requests ~30 assets (KaTeX, DOMPurify, Prism, the ES-module
   graph, five woff2 faces). That burst overflows a backlog of 5 and the OS
   REFUSES connections, so a page would come up missing e.g.
   ``vendor/katex/auto-render.min.js`` — ``net::ERR_CONNECTION_REFUSED``. The
   frontend then never finished bootstrapping, which surfaced as a grab-bag of
   unrelated-looking failures across the suite (a click doing nothing, axe
   scoring a half-rendered DOM, a screenshot of an unstyled page). This was the
   real cause of the suite's long-standing flakiness; the fixed ~250ms
   post-goto waits merely hid it some of the time.

2. ``SO_REUSEADDR`` + an explicit "ready" line on stdout, so Playwright's
   ``webServer.url`` probe doesn't race a TIME_WAIT socket from a prior run.

Usage: python -u scripts/serve-ui.py [port] [directory]
"""

from __future__ import annotations

import functools
import socketserver
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# The whole point of this file — a backlog deep enough for every Playwright
# worker to boot a page at once. 5 (the stdlib default) is far too small.
socketserver.TCPServer.request_queue_size = 256


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Threading server that reuses the address and reaps worker threads."""

    allow_reuse_address = True
    daemon_threads = True


class QuietHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler minus the per-request stderr spam.

    Playwright pipes the server's stdio into its own output; ~30 request lines
    per page x 100+ pages buries the actual test results.
    """

    # Parameter is named `format` to match BaseHTTPRequestHandler's signature
    # (renaming it breaks the override contract — Pyright flags it).
    def log_message(self, format: str, *args: object) -> None:
        pass

    def log_error(self, format: str, *args: object) -> None:
        # Keep genuine errors (4xx/5xx) visible — those are worth seeing.
        super().log_message(format, *args)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5173
    directory = sys.argv[2] if len(sys.argv) > 2 else "ui"

    handler = functools.partial(QuietHandler, directory=directory)
    with QuietThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        # Explicit ready marker (stdout, unbuffered via -u) for the humans
        # reading Playwright's piped server output.
        print(
            f"serving {directory}/ on http://127.0.0.1:{port} "
            f"(backlog={socketserver.TCPServer.request_queue_size})",
            flush=True,
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
