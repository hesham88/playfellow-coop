"""A tiny local server for the web arena: python demo/web/serve.py [port]. It listens on 127.0.0.1 only and sends JavaScript modules (.mjs) with the
JavaScript type. Python's own http.server on Windows sends .mjs as plain text, and a browser refuses to run a module sent that way (the page then
shows an empty canvas): found in the first real-browser run, so this file exists. A real host (Cloudflare, for example) sends the right type."""
from __future__ import annotations

import http.server
import sys
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript", ".js": "text/javascript", ".json": "application/json"}

    def end_headers(self):  # a local test server: never let the browser keep an old copy of a script
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).resolve().parent), **kwargs)


def main(argv: list[str] | None = None) -> int:
    port = int((argv or sys.argv[1:] or ["8765"])[0])
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:  # loopback only: never reachable from another machine
        print(f"http://127.0.0.1:{port}/index.html")
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
