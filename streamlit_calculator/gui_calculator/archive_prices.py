# Copyright 2026 anchored-vwam-backtest contributors
"""Download optional detailed prices for a selected options archive window."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd
import requests
import streamlit as st
from snapshot_tunnel.options_model import CandleClose, parse_candle_closes

from gui_calculator.data_sources import INTERVALS, fetch_bybit_klines

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot


@dataclass(frozen=True, kw_only=True)
class PriceRequest:
    """Identify the market, resolution and exact observation window."""

    asset: str
    interval: str
    start: datetime
    end: datetime


@dataclass(frozen=True, kw_only=True)
class DownloadedPrices:
    """Keep downloaded candles associated with their requested scope."""

    request: PriceRequest
    candles: tuple[CandleClose, ...]


def load_archive_prices(
    request: PriceRequest, *, now: datetime
) -> tuple[CandleClose, ...]:
    """Load validated closes, excluding incomplete and out-of-window bars.

    Returns:
        Completed price observations within the selected snapshot period.

    """
    end = min(request.end, now)
    if request.start >= end:
        return ()
    duration = INTERVALS[request.interval]["delta"]
    frame = fetch_bybit_klines(
        f"{request.asset}USDT",
        request.interval,
        start_ms=int((request.start - duration).timestamp() * 1000),
        end_ms=int(end.timestamp() * 1000),
    )
    if frame.empty:
        return ()
    closes = pd.DataFrame({
        "timestamp": pd.to_datetime(frame["time"], utc=True) + duration,
        "close": frame["close"],
    })
    return tuple(
        candle
        for candle in parse_candle_closes(closes.to_csv(index=False))
        if request.start <= candle.timestamp <= end
    )


def render_archive_prices(
    snapshots: tuple[Snapshot, ...],
) -> tuple[CandleClose, ...]:
    """Download only on request and retain prices across chart interactions.

    Returns:
        Prices matching the current scope, or no overlay when unavailable.

    """
    if not st.toggle("Show detailed downloaded price history"):
        return ()
    interval = st.selectbox("Price candle interval", list(INTERVALS), index=3)
    request = PriceRequest(
        asset=snapshots[0].asset,
        interval=interval,
        start=min(snapshot.timestamp for snapshot in snapshots),
        end=max(snapshot.timestamp for snapshot in snapshots),
    )
    _ = st.caption(
        f"Bybit {request.asset}USDT linear perpetual · {interval} closes · "
        f"{request.start.isoformat()} to {request.end.isoformat()}. "
        "Market prices may differ from the options snapshot spot reference. "
        "Options metrics remain calculated only at recorded snapshot times."
    )
    if st.button("Download price history", key="archive_download_prices"):
        try:
            with st.spinner("Downloading historical prices…"):
                st.session_state["archive_prices"] = DownloadedPrices(
                    request=request,
                    candles=load_archive_prices(request, now=datetime.now(UTC)),
                )
        except (requests.RequestException, ValueError, OverflowError) as exc:
            st.session_state["archive_prices"] = None
            _ = st.error(f"Price download failed: {exc}")
    saved = st.session_state.get("archive_prices")
    if not isinstance(saved, DownloadedPrices) or saved.request != request:
        _ = st.info("Download prices for the selected period and interval.")
        return ()
    if not saved.candles:
        _ = st.info("No completed price candles are available in this period.")
        return ()
    _ = st.caption(
        f"{len(saved.candles):,} completed candles loaded. Missing candles "
        "are not filled; the line connects available closes."
    )
    _ = st.download_button(
        "Save price history CSV",
        pd.DataFrame({
            "timestamp": [candle.timestamp for candle in saved.candles],
            "close": [candle.close for candle in saved.candles],
        }).to_csv(index=False),
        file_name=f"{request.asset.lower()}_{interval}_price_history.csv",
        mime="text/csv",
    )
    return saved.candles
