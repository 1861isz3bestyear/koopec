# Copyright 2026 anchored-vwam-backtest contributors
"""Snapshot oscillators on one shared chronological axis."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
from snapshot_tunnel.bitget import growth_momentum
from snapshot_tunnel.oi_divergence import DivergenceSettings, divergence_series

from gui_calculator.bitget_view import load_bitget_growth
from gui_calculator.options_profile_chart import style_options_chart
from gui_calculator.snapshot_margin import (
    load_margin_history,
    load_public_margin_history,
)
from gui_calculator.snapshot_oi import oi_state_chart
from gui_calculator.snapshot_oi_data import load_snapshot_oi
from gui_calculator.snapshot_oscillator import (
    limit_order_oscillator_rate,
    load_limit_order_history,
    load_price_history,
    saved_depth_history,
)

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot

    from gui_calculator.view_types import IndicatorUI


def snapshot_dashboard_chart(snapshot: Snapshot, *, days: int) -> go.Figure:
    """Build four aligned panels with a common cutoff and time cursor.

    Returns:
        A shared-axis figure, including reference levels on empty panels.

    """
    chart = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.4, 0.2, 0.2, 0.2],
        vertical_spacing=0.075,
        subplot_titles=[
            "Price",
            "Limit orders oscillator",
            "Margin loan oscillator",
            "OI divergence oscillator",
        ],
    )
    _ = chart.update_layout(
        shapes=[
            {
                "type": "line",
                "x0": snapshot.timestamp,
                "x1": snapshot.timestamp,
                "xref": "x",
                "y0": 0,
                "y1": 1,
                "yref": "paper",
                "line": {"color": "#9333ea", "width": 2, "dash": "dash"},
            },
        ]
    )
    for row, label in enumerate(
        (f"{snapshot.asset}USDT", "Bid share %", "Margin rate", "Divergence"),
        start=1,
    ):
        _ = chart.update_yaxes(title_text=label, row=row, col=1)
    for row, thresholds in ((2, (30, 70)), (3, (38, 62))):
        _ = chart.update_yaxes(range=[0, 100], row=row, col=1)
        for level in (*thresholds, 50):
            _ = chart.add_hline(
                y=level,
                line_dash="dot",
                row=row,
                col=1,
                exclude_empty_subplots=False,
            )
    _ = chart.update_yaxes(range=[-0.1, 1.1], tickvals=[0, 1], row=4, col=1)
    chart = style_options_chart(chart)
    _ = chart.update_layout(
        title=f"{snapshot.asset} · snapshot oscillators",
        height=1000,
        hovermode="x unified",
        hoversubplots="axis",
        hoverdistance=-1,
        spikedistance=-1,
        showlegend=False,
        margin={"l": 80, "r": 30, "t": 100, "b": 70},
    )
    _ = chart.update_xaxes(
        type="date",
        range=[snapshot.timestamp - timedelta(days=days), snapshot.timestamp],
        matches="x",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        showticklabels=True,
    )
    return chart


def _add_limit_orders(
    chart: go.Figure, snapshot: Snapshot, *, days: int
) -> None:
    """Load recorded depth without reconstructing unavailable observations."""
    uploaded = st.file_uploader(
        f"{snapshot.asset}USDT recorded limit-order depth CSV",
        type=["csv"],
        key=f"snapshot_limit_order_depth_{snapshot.asset}",
        help=(
            "Full books: time,available_at,side,price,quantity; UTC-aware"
            " timestamps."
        ),
    )
    books = (
        load_limit_order_history(
            uploaded.getvalue().decode("utf-8-sig"), snapshot, days=days
        )
        if uploaded is not None
        else saved_depth_history(snapshot, days=days)
    )
    _ = chart.add_trace(
        go.Scatter(
            x=[book.available for book in books],
            y=[limit_order_oscillator_rate(book) for book in books],
            name="Limit orders",
            mode="lines+markers",
            connectgaps=False,
        ),
        row=2,
        col=1,
    )
    if not books:
        _ = st.info("No recorded limit-order depth in this snapshot window.")


def _add_margin(chart: go.Figure, snapshot: Snapshot, *, days: int) -> None:
    """Keep either borrowing source on the selected snapshot's cutoff."""
    source = st.selectbox(
        "Margin loan source",
        ("Bitget public loan growth", "OKX ratio / recorded balances"),
        key="snapshot_margin_source",
    )
    if source == "Bitget public loan growth":
        period = "24h" if days == 1 else "30d"
        if st.button("Refresh margin data", key="refresh_snapshot_margin"):
            load_bitget_growth.clear(snapshot.asset, period=period)
        history = tuple(
            point
            for point in load_bitget_growth(snapshot.asset, period=period)
            if point.timestamp <= snapshot.timestamp
        )
        values = growth_momentum(history, period=period)
        cadence = "hourly" if period == "24h" else "daily"
        _ = st.caption(
            f"Bitget loan growth observations update {cadence}. "
            "Select 24 hours for hourly updates; Week and Month use daily data."
        )
        if history:
            _ = st.caption(
                "Latest margin observation: "
                f"{history[-1].timestamp.isoformat()}; "
                f"raw loan growth: {history[-1].growth:g}."
            )
        if not any(value is not None for value in values):
            _ = st.info(
                "Margin momentum needs 14 consecutive observations. "
                "No warmed-up values are available in this window."
            )
        trace = go.Scatter(
            x=[point.timestamp for point in history],
            y=[
                value if value is not None else float("nan") for value in values
            ],
            name="Margin loan growth momentum",
            connectgaps=False,
        )
    else:
        uploaded = st.file_uploader(
            f"{snapshot.asset}USDT recorded margin loan balances CSV",
            type=["csv"],
            key=f"snapshot_margin_loans_{snapshot.asset}",
            help=(
                "Columns: time,available_at,quote_loans,base_loans; USDT"
                " notionals."
            ),
        )
        loans = (
            load_margin_history(
                uploaded.getvalue().decode("utf-8-sig"), snapshot, days=days
            )
            if uploaded is not None
            else load_public_margin_history(snapshot, days=days)
        )
        trace = go.Scatter(
            x=[loan.available for loan in loans],
            y=[loan.rate for loan in loans],
            name="Margin borrowing share",
            connectgaps=False,
        )
    _ = chart.add_trace(trace, row=3, col=1)


def _add_oi(chart: go.Figure, snapshot: Snapshot, *, days: int) -> None:
    """Retain held states, gaps and detection-time hover descriptions."""
    settings = DivergenceSettings(
        min_swing_percent=st.number_input(
            "OI minimum price swing (%)", min_value=0.0, value=0.1, step=0.01
        ),
        min_oi_change=st.number_input(
            "OI minimum oscillator change (percentage points)",
            min_value=0.0,
            value=0.05,
            step=0.01,
        ),
    )
    series = divergence_series(
        load_snapshot_oi(snapshot, days=days), settings=settings
    )
    original = oi_state_chart(series, snapshot, days=days)
    for trace in original.data:
        if isinstance(trace, go.Scatter) and trace.yaxis == "y3":
            _ = chart.add_trace(trace, row=4, col=1)


@st.fragment(run_every="1m")
def render_snapshot_dashboard(
    snapshot: Snapshot, *, chart_ui: IndicatorUI = st
) -> None:
    """Refresh the synchronized oscillator window every minute."""
    render_dashboard_window(snapshot, chart_ui=chart_ui)


def render_dashboard_window(
    snapshot: Snapshot, *, chart_ui: IndicatorUI = st
) -> None:
    """Render price and all three oscillators in one synchronized chart."""
    if not st.toggle("Show snapshot oscillators", key="snapshot_oscillators"):
        return
    period = st.selectbox(
        "Oscillator history", ("24 hours", "Week", "Month"), index=1
    )
    days = {"24 hours": 1, "Week": 7, "Month": 30}[period]
    timing = st.selectbox(
        "Oscillator data time",
        ("Latest available", "Selected options snapshot"),
        help=(
            "Latest refreshes all panels every minute independently of options."
        ),
    )
    reference = snapshot.timestamp
    if timing == "Latest available":
        snapshot = replace(snapshot, timestamp=datetime.now(UTC))
    chart = snapshot_dashboard_chart(snapshot, days=days)
    _ = chart.update_shapes(x0=reference, x1=reference, selector={"xref": "x"})
    for label, loader in (
        ("Price", _add_price),
        ("Limit orders", _add_limit_orders),
        ("Margin loan", _add_margin),
        ("OI divergence", _add_oi),
    ):
        try:
            loader(chart, snapshot, days=days)
        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
        ) as exc:
            _ = st.warning(f"{label} unavailable: {exc}")
    # Empty panels still need a hover target to keep the shared cursor active.
    for row, level in ((2, 50), (3, 50), (4, 0.5)):
        _ = chart.add_trace(
            go.Scatter(
                x=[
                    snapshot.timestamp - timedelta(days=days),
                    snapshot.timestamp,
                ],
                y=[level, level],
                mode="lines",
                opacity=0,
                hoverinfo="none",
                showlegend=False,
            ),
            row=row,
            col=1,
        )
    # Matched ranges synchronize zoom, but Plotly hover propagation requires
    # every panel to reference the very same time axis.
    _ = chart.update_traces(xaxis="x")
    _ = chart.update_yaxes(anchor="x")
    _ = chart_ui.plotly_chart(chart, use_container_width=True)
    _ = st.caption(
        "All panels share UTC time, zoom, pan and the data window ending "
        f"{snapshot.timestamp.isoformat()}. Mode: {timing}. Latest data "
        "refreshes every minute; week/month Bitget growth updates daily. "
        f"Dashed line: options snapshot {reference.isoformat()}. Historical"
        " snapshots mark their observation time. Limit orders: bid notional"
        " share (50 = balanced; zones 30/70). Margin: Bitget growth momentum"
        " or OKX/uploaded borrowing share (zones 38/62). OI: 1 = divergence, 0"
        " = confirmation; unavailable before detection or after gaps. States"
        " appear at detection time."
    )


def _add_price(chart: go.Figure, snapshot: Snapshot, *, days: int) -> None:
    """Use completed hourly prices at the same snapshot cutoff."""
    candles = load_price_history(snapshot, days=days)
    _ = chart.add_trace(
        go.Scatter(
            x=[point.timestamp for point in candles],
            y=[point.close for point in candles],
            name="Price",
            line={"color": "#f59e0b"},
            connectgaps=False,
        ),
        row=1,
        col=1,
    )
