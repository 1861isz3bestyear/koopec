# Copyright 2026 anchored-vwam-backtest contributors
"""Collect and serialize complete Bybit books alongside options snapshots."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from time import sleep
from typing import TYPE_CHECKING

import koopec_calculus
from snapshot_tunnel.order_book import BookLevel, BookSnapshot
from snapshot_tunnel.validation import unix_microseconds

if TYPE_CHECKING:
    import requests

DEPTH_LIMIT = 50
LEVEL_WIDTH = 2
MAXIMUM_DEPTH_AGE = timedelta(seconds=10)
MAXIMUM_CLOCK_LEAD = timedelta(seconds=5)


def depth_csv(book: BookSnapshot) -> str:
    """Serialize a complete book with exchange and local receipt timestamps.

    Returns:
        Validatable depth CSV, with one row per price level.

    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(("time", "available_at", "side", "price", "quantity"))
    for side, levels in (("bid", book.bids), ("ask", book.asks)):
        writer.writerows(
            (
                book.observed.isoformat(),
                book.available.isoformat(),
                side,
                level.price,
                level.quantity,
            )
            for level in levels
        )
    return output.getvalue()


def parse_depth(
    payload: str, *, asset: str, received: datetime
) -> BookSnapshot:
    """Validate Bybit's full top-50 linear book and its receipt freshness.

    Returns:
        A two-sided, uncrossed, timely full book.

    """
    observed, bids, asks = koopec_calculus.parse_depth(
        payload, asset, unix_microseconds(received)
    )
    return BookSnapshot(
        observed=datetime.fromtimestamp(observed / 1_000, UTC),
        available=received,
        bids=tuple(
            BookLevel(price=price, quantity=quantity)
            for price, quantity in bids
        ),
        asks=tuple(
            BookLevel(price=price, quantity=quantity)
            for price, quantity in asks
        ),
    )


def fetch_depth(session: requests.Session, *, asset: str) -> BookSnapshot:
    """Download a full current book and record its actual local receipt time.

    Returns:
        Validated top-50 Bybit linear-contract depth.

    Raises:
        ValueError: If the request fails or exchange clocks disagree.

    """
    url, params = koopec_calculus.market_request("book", asset)
    response = session.get(url, params=params, timeout=(3, 5))
    response.raise_for_status()
    received = datetime.now(UTC)
    exchange_ms = koopec_calculus.depth_time(response.text, asset)
    observed = datetime.fromtimestamp(exchange_ms / 1_000, UTC)
    lead = observed - received
    if lead > MAXIMUM_CLOCK_LEAD:
        msg = (
            "Bybit book timestamp is more than 5 seconds ahead of the local "
            "clock. Synchronize the system clock and retry."
        )
        raise ValueError(msg)
    if lead > timedelta(0):
        # Wait for actual availability instead of rewriting exchange timestamps.
        sleep(lead.total_seconds())
        received = datetime.now(UTC)
    return parse_depth(response.text, asset=asset, received=received)
