# Copyright 2026 anchored-vwam-backtest contributors
"""Hourly Bybit contract OI paired with completed snapshot-bounded prices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import requests
import streamlit as st
from shared.validation import (
    json_object,
    numeric_string,
    object_list,
    object_mapping,
    string,
)
from snapshot_tunnel.oi_divergence import InterestSample, MarketSample

from gui_calculator.snapshot_price_data import load_price_history

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot


_HOUR_MS = 3_600_000


def parse_interest_page(payload: str) -> tuple[tuple[InterestSample, ...], str]:
    """Validate reverse-chronological exchange OI and its pagination cursor.

    Returns:
        Positive hourly base-asset OI samples and the next cursor.

    Raises:
        ValueError: If Bybit reports an error or timestamps are invalid.

    """
    body = json_object(payload)
    if body.get("retCode") != 0:
        msg = (
            f"Bybit OI request failed: {body.get('retMsg', 'invalid response')}"
        )
        raise ValueError(msg)
    result = object_mapping(body["result"])
    samples: list[InterestSample] = []
    for raw in object_list(result["list"]):
        row = object_mapping(raw)
        stamp = string(row["timestamp"])
        if not stamp.isdecimal() or int(stamp) <= 0 or int(stamp) % _HOUR_MS:
            msg = "OI timestamps must be positive hourly epoch milliseconds."
            raise ValueError(msg)
        sample = InterestSample(
            timestamp=datetime.fromtimestamp(int(stamp) / 1000, tz=UTC),
            value=numeric_string(row["openInterest"]),
        )
        if samples and sample.timestamp >= samples[-1].timestamp:
            msg = "Bybit OI page must be strictly reverse chronological."
            raise ValueError(msg)
        samples.append(sample)
    return tuple(samples), string(result.get("nextPageCursor", ""))


def fetch_interest_history(
    session: requests.Session, snapshot: Snapshot, *, days: int
) -> tuple[InterestSample, ...]:
    """Download all hourly OI pages within the snapshot observation window.

    Returns:
        Chronological samples, allowing one minute for publication.

    """
    return fetch_interest_window(
        session, asset=snapshot.asset, end=snapshot.timestamp, days=days
    )


def fetch_interest_window(
    session: requests.Session,
    *,
    asset: Literal["BTC", "ETH"],
    end: datetime,
    days: int,
) -> tuple[InterestSample, ...]:
    """Download hourly OI independently of options-chain availability.

    Returns:
        Chronological OI through the requested window with publication lag.

    Raises:
        ValueError: If pagination repeats, overlaps or leaves the window.

    """
    start = end - timedelta(days=days)
    end -= timedelta(minutes=1)
    samples: list[InterestSample] = []
    cursor = ""
    seen: set[str] = set()
    while True:
        response = session.get(
            "https://api.bybit.com/v5/market/open-interest",
            params={
                "category": "linear",
                "symbol": f"{asset}USDT",
                "intervalTime": "1h",
                "startTime": int(start.timestamp() * 1000),
                "endTime": int(end.timestamp() * 1000),
                "limit": 200,
                "cursor": cursor,
            },
            timeout=30,
        )
        response.raise_for_status()
        page, cursor = parse_interest_page(response.text)
        if any(not start <= item.timestamp <= end for item in page):
            msg = "Bybit OI observation falls outside the snapshot window."
            raise ValueError(msg)
        if page and samples and page[0].timestamp >= samples[-1].timestamp:
            msg = "Bybit OI pages overlap or fail to advance."
            raise ValueError(msg)
        samples.extend(page)
        if not page or not cursor:
            return tuple(reversed(samples))
        if cursor in seen:
            msg = "Bybit OI pagination repeated a cursor."
            raise ValueError(msg)
        seen.add(cursor)


@st.cache_data(ttl=300, show_spinner=False)
def load_snapshot_oi(
    snapshot: Snapshot, *, days: int
) -> tuple[MarketSample, ...]:
    """Join OI to candle closes at exact timestamps with extra warmup history.

    Returns:
        Matched hourly samples, including two days before the visible window.
        Missing matches remain gaps; no prices or OI are forward filled.

    """
    with requests.Session() as session:
        interest = fetch_interest_history(session, snapshot, days=days + 2)
    candles = load_price_history(snapshot, days=days + 2)
    prices = {candle.timestamp: candle.close for candle in candles}
    return tuple(
        MarketSample(interest=sample, price=prices[sample.timestamp])
        for sample in interest
        if sample.timestamp in prices
    )
