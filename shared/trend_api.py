"""Small local HTTP service the Aspect Calendar asks for a stock's current trend.

GET /trend?code=AMMN -> {"trend": ..., "since": ..., "last": ..., "src": ...}

When no price CSV exists yet for the code (see price_store.price_files), the
stock's whole daily history is downloaded from Yahoo Finance into db/prices/
first. The page calls it on hover, so the bubble can show "loading" and then the
trend without Streamlit rerunning (a rerun would rebuild the calendar iframe).

Listens on 127.0.0.1 only, on a free port chosen at start (start_trend_api()).
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from shared.price_store import PRICES_DIR, download_prices, price_files, trend_of_file

_lock = threading.Lock()          # one Yahoo download at a time
_cache: dict[tuple[str, float], dict] = {}


def trend_for(code: str) -> dict:
    """Trend of `code`, downloading its price history first when there is none."""
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,8}", code):
        return {"trend": "", "since": "", "last": "", "error": True, "msg": "kode tidak valid"}
    path = price_files().get(code)
    if path is None:
        with _lock:
            path = price_files().get(code)
            if path is None:
                res = download_prices([code], log=lambda _m: None)
                if not res["ok"]:
                    return {"trend": "", "since": "", "last": "", "error": True,
                            "msg": "Yahoo Finance tidak punya data harga"}
                path = PRICES_DIR / f"{code}.csv"
    key = (str(path), path.stat().st_mtime)
    if key not in _cache:
        _cache[key] = trend_of_file(path)
    return _cache[key]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path != "/trend":
            self.send_error(404)
            return
        code = parse_qs(url.query).get("code", [""])[0]
        try:
            body = trend_for(code)
        except Exception as exc:  # network error etc.
            body = {"trend": "", "since": "", "last": "", "error": True, "msg": str(exc)[:200]}
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # keep the Streamlit console quiet
        pass


def start_trend_api() -> int:
    """Start the service in a daemon thread; returns its port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="trend-api").start()
    return server.server_address[1]
