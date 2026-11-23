# Copyright 2026 anchored-vwam-backtest contributors
"""Recorded limit-order imbalance at the selected options observation."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
from shared.order_book import BookSnapshot, parse_book_history
from shared.tunnel_oscillators import (
    limit_order_oscillator_rate as limit_order_oscillator_rate,
)

from gui_calculator.options_store import load_snapshots
from gui_calculator.oscillator_charts import (
    add_oscillator_trace,
    oscillator_chart,
)
from gui_calculator.oscillator_dashboard import oscillator_dashboard_html
from gui_calculator.snapshot_price_data import (
    load_price_history as load_price_history,
)

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot


def load_limit_order_history(
    content: str, snapshot: Snapshot, *, days: int
) -> tuple[BookSnapshot, ...]:
    """Validate complete books and retain only timely, available observations.

    Returns:
        Fresh books received within the selected snapshot window.

    """
    history = parse_book_history(content, maximum_age=timedelta(seconds=10))
    start = snapshot.timestamp - timedelta(days=days)
    return tuple(
        book
        for book in history.snapshots
        if start <= book.observed <= book.available <= snapshot.timestamp
        and book.fresh(history.maximum_age)
    )


def saved_depth_history(
    snapshot: Snapshot, *, days: int
) -> tuple[BookSnapshot, ...]:
    """Load causal recorded books for the selected asset and snapshot window.

    Returns:
        Saved depth, including the displayed snapshot's attached book.

    """
    start = snapshot.timestamp - timedelta(days=days)
    observations = (*load_snapshots(), snapshot)
    books = {
        item.order_book.available: item.order_book
        for item in observations
        if item.asset == snapshot.asset
        and item.order_book is not None
        and start
        <= item.order_book.observed
        <= item.order_book.available
        <= snapshot.timestamp
        and item.order_book.fresh(timedelta(seconds=10))
    }
    return tuple(books[time] for time in sorted(books))


def render_snapshot_oscillator(snapshot: Snapshot) -> None:
    """Show real price history and recorded resting limit-order liquidity."""
    if not st.toggle(
        "Show limit order oscillator", key="snapshot_limit_order_rate"
    ):
        return
    period = st.selectbox("Oscillator history", ("Week", "Month"))
    days = 7 if period == "Week" else 30
    uploaded = st.file_uploader(
        f"{snapshot.asset}USDT recorded limit-order depth CSV",
        type=["csv"],
        key=f"snapshot_limit_order_depth_{snapshot.asset}",
        help=(
            "Full books: time,available_at,side,price,quantity. Use consistent "
            "depth, UTC-aware timestamps, and base-asset quantities."
        ),
    )
    try:
        books = (
            load_limit_order_history(
                uploaded.getvalue().decode("utf-8-sig"), snapshot, days=days
            )
            if uploaded is not None
            else saved_depth_history(snapshot, days=days)
        )
        with st.spinner("Loading completed Bybit hourly candles…"):
            candles = load_price_history(snapshot, days=days)
    except (requests.RequestException, ValueError, OverflowError) as exc:
        _ = st.warning(f"Limit order oscillator unavailable: {exc}")
        return
    chart = oscillator_chart(
        title=(
            f"{snapshot.asset} limit_order_oscillator_rate · {period.lower()}"
        ),
        price_label=f"{snapshot.asset}USDT · Bybit linear",
    )
    start = snapshot.timestamp - timedelta(days=days)
    visible = [
        i for i, candle in enumerate(candles) if candle.timestamp >= start
    ]
    times = [candles[i].timestamp for i in visible]
    _ = chart.add_trace(
        go.Scatter(
            x=times,
            y=[candles[i].close for i in visible],
            name="Price",
            line={"color": "#f59e0b"},
        ),
        row=1,
        col=1,
    )
    try:
        rates: list[float | None] = [
            limit_order_oscillator_rate(book) for book in books
        ]
    except (ValueError, OverflowError) as exc:
        _ = st.warning(f"Limit order oscillator unavailable: {exc}")
        return
    add_oscillator_trace(chart, [book.available for book in books], rates)
    _ = chart.update_yaxes(
        title_text="limit_order_oscillator_rate", row=2, col=1
    )
    _ = chart.update_traces(
        name="limit_order_oscillator_rate", selector={"name": "Oscillator"}
    )
    _ = chart.update_xaxes(range=[start, snapshot.timestamp])
    if not books:
        _ = chart.update_layout(
            annotations=[{
                "text": (
                    "No recorded limit-order depth · upload historical books"
                ),
                "x": 0.5,
                "y": 0.2,
                "xref": "paper",
                "yref": "paper",
                "showarrow": False,
            }]
        )
    _ = components.html(
        oscillator_dashboard_html(chart), height=1000, scrolling=True
    )
    _ = st.caption(
        "limit_order_oscillator_rate = 100 * bid notional / (bid + ask"
        " notional). Each level contributes price * quantity in USDT; 50 ="
        " balanced, above 70 = bid dominant, below 30 = ask dominant. Recorded"
        " full books use receipt times and a 10-second freshness limit; no"
        " future or late-received depth is plotted. Window ends at options"
        f" snapshot {snapshot.timestamp.isoformat()}. Bybit supplies completed"
        " 1h price candles, not historical depth. The reference provider's"
        " exact formula is unspecified. Threshold zones indicate liquidity"
        " dominance and do not execute trades."
    )
    if not books:
        _ = st.info(
            "No recorded limit-order depth in this snapshot window. "
            "New live snapshots record depth automatically. Upload older "
            "complete books for the selected market; "
            "price candles cannot reconstruct resting limit orders."
        )
    if not visible:
        _ = st.info("No completed price candles in this snapshot window.")
