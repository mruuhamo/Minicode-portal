"""Local dev server for the Search API (no Functions host needed).

    python -m minicode.api serve [--port 7071]      # uses the same settings/env vars as the Function app
"""

from __future__ import annotations

import argparse
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from minicode.api.routes import Api, ApiRequest
from minicode.settings import AppSettings, Components


def make_handler(api: Api, cors_origin: str | None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self) -> None:
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            req = ApiRequest(self.command, parts.path, parse_qs(parts.query, keep_blank_values=True),
                             dict(self.headers.items()), self.rfile.read(length) if length else b"")
            resp = api.handle(req)
            payload = resp.json_bytes()
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                self.send_header(k, v)
            if cors_origin:
                self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PATCH = _dispatch  # noqa: N815

        def do_OPTIONS(self) -> None:  # noqa: N802 - CORS preflight for the week 4 SPA dev server
            self.send_response(204)
            if cors_origin:
                self.send_header("Access-Control-Allow-Origin", cors_origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.end_headers()

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m minicode.api", description="Minicode Search API dev server")
    parser.add_argument("command", choices=["serve"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7071)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = AppSettings.from_env()
    api = Api(Components(settings))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(api, os.environ.get("CORS_ORIGIN")))
    print(f"Search API on http://{args.host}:{args.port}/api  (AUTH_MODE={settings.auth_mode}, data={settings.data_dir})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
