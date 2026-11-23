# Copyright 2026 anchored-vwam-backtest contributors
"""Load completed underlying candles for the options terminal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import requests
import streamlit as st
from snapshot_tunnel.options_model import (
    CandleClose,
    Snapshot,
    parse_candle_closes,
)

from gui_calculator.data_sources import fetch_bybit_klines


def load_completed_candles(
    snapshot: Snapshot, *, now: datetime
) -> tuple[CandleClose, ...]:
    """Fetch up to 24 hours of completed one-minute Bybit candles.

    Returns:
        Validated closes at or after the selected observation.

    """
    start = max(snapshot.timestamp, now - timedelta(days=1))
    if start >= now:
        return ()
    frame = fetch_bybit_klines(
        f"{snapshot.asset}USDT",
        "1m",
        start_ms=int(start.replace(second=0, microsecond=0).timestamp() * 1000),
        end_ms=int(now.timestamp() * 1000),
    )
    if frame.empty:
        return ()
    closes = pd.DataFrame({
        "timestamp": (
            pd.to_datetime(frame["time"], utc=True) + pd.Timedelta(minutes=1)
        ),
        "close": frame["close"],
    })
    candles = parse_candle_closes(closes.to_csv(index=False))
    return tuple(
        candle for candle in candles if start <= candle.timestamp <= now
    )


def render_candle_source(snapshot: Snapshot) -> tuple[CandleClose, ...]:
    """Render manual upload or automatically load candles after collection.

    Returns:
        Completed candles, or an empty tuple with a visible status.

    """
    uploaded = st.file_uploader(
        "Completed underlying candles CSV (timestamp, close)",
        type=["csv"],
        key="options_gex_candles",
    )
    automatic = (
        st.session_state.get("options_data_source")
        == "Saved history / Deribit API"
        and st.session_state.get(f"options_candles_ready_{snapshot.asset}")
        is True
    )
    candles: tuple[CandleClose, ...] = ()
    try:
        if uploaded is not None:
            return parse_candle_closes(uploaded.getvalue().decode("utf-8-sig"))
        if automatic:
            candles = load_completed_candles(snapshot, now=datetime.now(UTC))
    except (
        requests.RequestException,
        ValueError,
        OverflowError,
        UnicodeError,
    ) as exc:
        _ = st.error(f"Candle data unavailable: {exc}")
        return ()
    if automatic:
        _ = st.caption(
            f"Automatically loaded {len(candles)} completed 1m candles · "
            f"Bybit {snapshot.asset}USDT linear · last 24h, after snapshot. "
            "Refreshes every minute; CSV upload overrides automatic data."
        )
        if not candles:
            _ = st.info(
                "Candle check complete. No completed 1m candles are available "
                "after this snapshot yet. The next check is in one minute."
            )
        return candles
    _ = st.caption(
        "Candles load automatically after a successful Deribit fetch. "
        "You can also upload completed candles as CSV."
    )
    return ()
