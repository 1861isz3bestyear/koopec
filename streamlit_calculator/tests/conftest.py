# Copyright 2026 anchored-vwam-backtest contributors
"""Local HTTP market data for component and application tests."""

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, override
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@dataclass
class MarketHTTP:
    """Mutable HTTP fixture state for market-data tests."""

    start: int
    rows: list[list[str]]
    requests: list[dict[str, str]] = field(default_factory=list)
    fail_request: int | None = None
    page_size: int = 2
    url: str = ""


@pytest.fixture
def market_http() -> Generator[MarketHTTP]:
    """Provide a local market-data server.

    Yields:
        Mutable state for the running server.

    """
    start = int(pd.Timestamp("2026-01-01", tz="UTC").timestamp() * 1000)
    state = MarketHTTP(
        start=start,
        rows=[
            [
                str(start + i * 60000),
                str(open_),
                str(high),
                str(low),
                str(close),
                "10",
                str(close * 10),
            ]
            for i, (open_, high, low, close) in enumerate([
                (100, 100, 100, 100),
                (100, 101, 100, 101),
                (102, 102, 102, 102),
                (102, 102, 102, 102),
            ])
        ],
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = {
                k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()
            }
            state.requests.append(query)
            if len(state.requests) == state.fail_request:
                self.send_error(503, "temporary market outage")
                return
            rows = [
                r
                for r in state.rows
                if int(query["start"]) <= int(r[0]) <= int(query["end"])
            ]
            rows = sorted(rows, key=lambda r: int(r[0]), reverse=True)[
                : state.page_size
            ]
            data = json.dumps({"retCode": 0, "result": {"list": rows}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            _ = self.wfile.write(data)

        @override
        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}/v5/market/kline"
    state.start = start
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
