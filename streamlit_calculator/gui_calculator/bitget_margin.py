# Copyright 2026 anchored-vwam-backtest contributors
"""Cache public Bitget borrow observations independently of presentation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import koopec_calculus
import requests
import streamlit as st
from snapshot_tunnel.bitget import Growth, LoanRate

if TYPE_CHECKING:
    from snapshot_tunnel.bitget import Period


def fetch_growth(asset: str, *, period: Period) -> tuple[Growth, ...]:
    """Fetch validated Bitget history using the local Rust adapter.

    Returns:
        Chronological growth observations available at receipt.

    """
    url, params = koopec_calculus.market_request(period, asset)
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    received_ms = int(datetime.now(UTC).timestamp() * 1_000)
    return tuple(
        Growth(
            timestamp=datetime.fromtimestamp(stamp / 1_000, UTC), growth=rate
        )
        for stamp, rate in koopec_calculus.bitget_growth(
            response.text, received_ms
        )
    )


def fetch_rate(asset: str) -> LoanRate:
    """Fetch the current Bitget loan quote through the Rust adapter.

    Returns:
        Validated current rates and their exchange timestamp.

    """
    url, params = koopec_calculus.market_request("rate", asset)
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    stamp, daily, annual = koopec_calculus.bitget_rate(response.text)
    return LoanRate(
        timestamp=datetime.fromtimestamp(stamp / 1_000, UTC),
        daily=daily,
        annual=annual,
    )


def growth_momentum(
    points: tuple[Growth, ...], *, period: Period
) -> tuple[float | None, ...]:
    """Convert growth timestamps and calculate momentum in Rust.

    Returns:
        One result per observation, including blanks for warmup and gaps.

    """
    return tuple(
        koopec_calculus.margin_momentum(
            period,
            [
                (round(point.timestamp.timestamp() * 1_000), point.growth)
                for point in points
            ],
        )
    )


@st.cache_data(ttl=60, show_spinner=False)
def load_bitget_growth(asset: str, *, period: Period) -> tuple[Growth, ...]:
    """Cache public loan growth to respect Bitget's one-request/second limit.

    Returns:
        Validated chronological growth history.

    """
    return fetch_growth(asset, period=period)


@st.cache_data(ttl=60, show_spinner=False)
def load_bitget_rate(asset: str) -> LoanRate:
    """Cache the current VIP0 interest quote independently from history.

    Returns:
        Current interest terms with their request timestamp.

    """
    return fetch_rate(asset)
