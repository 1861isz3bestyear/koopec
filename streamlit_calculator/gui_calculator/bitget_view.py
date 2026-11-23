# Copyright 2026 anchored-vwam-backtest contributors
"""Public Bitget growth oscillator for live and GEX snapshot dashboards."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
from snapshot_tunnel.options_model import Snapshot

from gui_calculator.bitget_margin import growth_momentum
from gui_calculator.bitget_margin import (
    load_bitget_growth as load_bitget_growth,
)
from gui_calculator.bitget_margin import load_bitget_rate as load_bitget_rate
from gui_calculator.oscillator_charts import (
    add_oscillator_trace,
    oscillator_chart,
)
from gui_calculator.oscillator_dashboard import oscillator_dashboard_html
from gui_calculator.snapshot_oscillator import load_price_history

if TYPE_CHECKING:
    from snapshot_tunnel.bitget import Period


def render_bitget_margin(snapshot: Snapshot, *, days: int) -> None:
    """Render growth momentum bounded by the selected options snapshot."""
    period: Period = "24h" if days == 1 else "30d"
    cutoff = min(snapshot.timestamp, datetime.now(UTC))
    start = cutoff - timedelta(days=days)
    if st.button("Refresh margin data", key="refresh_bitget_margin"):
        load_bitget_growth.clear(snapshot.asset, period=period)
        load_bitget_rate.clear(snapshot.asset)
    try:
        history = tuple(
            point
            for point in load_bitget_growth(snapshot.asset, period=period)
            if point.timestamp <= cutoff
        )
        values = growth_momentum(history, period=period)
    except (
        requests.RequestException,
        ValueError,
        TypeError,
        OverflowError,
    ) as exc:
        _ = st.warning(f"Bitget margin growth unavailable: {exc}")
        history, values = (), ()
    selected = [
        (point, value)
        for point, value in zip(history, values, strict=True)
        if point.timestamp >= start
    ]
    chart = oscillator_chart(
        title=f"{snapshot.asset} Bitget margin loan growth momentum(14)",
        price_label=f"{snapshot.asset}USDT · Bybit linear",
        thresholds=(38, 62),
    )
    try:
        prices = load_price_history(snapshot, days=days)
        _ = chart.add_trace(
            go.Scatter(
                x=[price.timestamp for price in prices],
                y=[price.close for price in prices],
                name="Price",
                line={"color": "#f59e0b"},
            ),
            row=1,
            col=1,
        )
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        _ = st.warning(f"Margin price history unavailable: {exc}")
    add_oscillator_trace(
        chart,
        [point.timestamp for point, _ in selected],
        [value for _, value in selected],
        thresholds=(38, 62),
    )
    _ = chart.update_traces(
        name="margin_loan_oscillator_rate", selector={"name": "Oscillator"}
    )
    _ = chart.update_layout(
        meta={"margin_source": "bitget_growth", "growth_period": period}
    )
    _ = chart.update_xaxes(range=[start, cutoff])
    _ = components.html(
        oscillator_dashboard_html(chart), height=1000, scrolling=True
    )
    _ = st.caption(
        "Source: Bitget public base-coin margin loan growth (cross + isolated)."
        " Momentum = 100 * sum(positive growth) / sum(absolute growth) over 14"
        " observations; flat windows = 50. First 13 observations and gaps are"
        " warmup. 24h uses hourly data; longer windows use 30d daily data."
        " Thresholds: 38/62. Exchange timestamps may be revised; this is"
        " snapshot-bounded public history, not a recorded receipt-time"
        " backtest."
    )
    if selected:
        _ = st.caption(
            f"Available observations: {selected[0][0].timestamp.isoformat()} — "
            f"{selected[-1][0].timestamp.isoformat()}; "
            f"latest raw growth: {selected[-1][0].growth:g}."
        )
    if not any(value is not None for _, value in selected):
        _ = st.info(
            "No warmed-up Bitget growth values in this snapshot window. Bitget"
            " retains at most 30 days; older snapshots need recorded data."
        )
    _render_current_rate(snapshot.asset)


def _render_current_rate(asset: str) -> None:
    """Keep the latest interest quote explicitly outside historical signals."""
    try:
        rate = load_bitget_rate(asset)
    except (
        requests.RequestException,
        ValueError,
        TypeError,
        OverflowError,
    ) as exc:
        _ = st.warning(f"Current Bitget loan rates unavailable: {exc}")
        return
    _ = st.caption(
        f"Current {asset} VIP0 loan rate: {rate.daily:.6%} daily / "
        f"{rate.annual:.4%} annual, fetched {rate.timestamp.isoformat()}. "
        "Live context only; excluded from historical oscillator calculations."
    )


@st.fragment(run_every="1m")
def render_live_bitget(asset: str) -> None:
    """Refresh the same public source before loading an options snapshot."""
    period = st.selectbox("Bitget growth history", ("24 hours", "30 days"))
    snapshot = Snapshot(
        timestamp=datetime.now(UTC),
        asset="BTC" if asset == "BTC" else "ETH",
        spot=1,
        options=(),
    )
    render_bitget_margin(snapshot, days=1 if period == "24 hours" else 30)


@st.fragment(run_every="1m")
def render_latest_bitget(snapshot: Snapshot, *, days: int) -> None:
    """Refresh lending and prices independently of the options snapshot."""
    current = replace(snapshot, timestamp=datetime.now(UTC))
    _ = st.caption(
        "Live margin data · refreshes every minute (growth cache: 1 minute). "
        "Week/month loan observations update daily at the exchange; "
        "prices use completed hourly candles. "
        f"Window ends {current.timestamp.isoformat()}."
    )
    render_bitget_margin(current, days=days)
