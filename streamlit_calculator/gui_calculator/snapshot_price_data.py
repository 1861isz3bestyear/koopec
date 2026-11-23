# Copyright 2026 anchored-vwam-backtest contributors
"""Fetch snapshot-bounded completed price history without UI imports."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st
from snapshot_tunnel.options_model import CandleClose, parse_candle_closes

from gui_calculator.data_sources import fetch_bybit_klines

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot


@st.cache_data(ttl=300, show_spinner=False)
def load_price_history(
    snapshot: Snapshot, *, days: int
) -> tuple[CandleClose, ...]:
    """Load completed hourly price candles within the selected window.

    Returns:
        Validated chronological candles available by snapshot receipt time.

    """
    start = snapshot.timestamp - timedelta(days=days)
    frame = fetch_bybit_klines(
        f"{snapshot.asset}USDT",
        "1h",
        start_ms=int(start.timestamp() * 1000),
        end_ms=int(snapshot.timestamp.timestamp() * 1000),
    )
    if frame.empty:
        return ()
    closes = pd.DataFrame({
        "timestamp": (
            pd.to_datetime(frame["time"], utc=True) + pd.Timedelta(hours=1)
        ),
        "close": frame["close"],
    })
    return tuple(
        candle
        for candle in parse_candle_closes(closes.to_csv(index=False))
        if candle.timestamp <= snapshot.timestamp
    )
