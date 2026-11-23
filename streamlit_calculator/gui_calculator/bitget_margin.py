# Copyright 2026 anchored-vwam-backtest contributors
"""Cache public Bitget borrow observations independently of presentation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st
from snapshot_tunnel.bitget import fetch_growth, fetch_rate

if TYPE_CHECKING:
    from snapshot_tunnel.bitget import Growth, LoanRate, Period


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
