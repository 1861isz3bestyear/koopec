# Copyright 2026 anchored-vwam-backtest contributors
"""Snapshot-by-snapshot analytics for imported options archives."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from snapshot_tunnel.gamma_search import search_flips

from gui_calculator.archive_prices import render_archive_prices
from gui_calculator.comparison_view import render_snapshot_comparison
from gui_calculator.options_profile_chart import (
    exposure_chart,
    style_options_chart,
)
from gui_calculator.snapshot_history import (
    snapshot_history as snapshot_history,
)

if TYPE_CHECKING:
    import pandas as pd
    from snapshot_tunnel.options_model import CandleClose, Snapshot

    from gui_calculator.view_types import IndicatorUI


def history_chart(
    history: pd.DataFrame, *, prices: tuple[CandleClose, ...] = ()
) -> go.Figure:
    """Plot price levels and exposure with separate units on a shared timeline.

    Returns:
        An interactive chart with visible recorded observations.

    """
    chart = make_subplots(rows=2, cols=1, shared_xaxes=True)
    for label, color in (
        ("Price", "#111827"),
        ("Gamma flip", "#0369a1"),
        ("Put 1", "#be123c"),
        ("Put 2", "#be123c"),
        ("Call 1", "#15803d"),
        ("Call 2", "#15803d"),
        ("Net GEX", "#7e22ce"),
    ):
        _ = chart.add_trace(
            go.Scatter(
                x=history["Timestamp (UTC)"],
                y=history[label],
                name=label,
                mode=(
                    "markers"
                    if label == "Price" and prices
                    else "lines+markers"
                ),
                connectgaps=False,
                line={"color": color},
                marker=(
                    {
                        "color": (
                            (history[label] >= 0).map(
                                {True: "#15803d", False: "#be123c"}
                            )
                        )
                    }
                    if label == "Net GEX"
                    else {"color": color}
                ),
            ),
            row=2 if label == "Net GEX" else 1,
            col=1,
        )
    if prices:
        _ = chart.add_trace(
            go.Scatter(
                x=[candle.timestamp for candle in prices],
                y=[candle.close for candle in prices],
                name="Downloaded price (Bybit close)",
                mode="lines",
                line={"color": "#a16207", "width": 2},
                connectgaps=False,
            ),
            row=1,
            col=1,
        )
    _ = chart.add_hline(y=0, row=2, col=1, line_color="#111827")
    _ = chart.update_layout(
        title="CSV archive · options snapshot history",
        template="plotly_white",
        height=700,
    )
    _ = chart.update_yaxes(title_text="Price (USD)", row=1, col=1)
    _ = chart.update_yaxes(title_text="Net GEX (USD / 1% move)", row=2, col=1)
    _ = chart.update_xaxes(title_text="Snapshot time (UTC)", row=2, col=1)
    return style_options_chart(chart)


def render_snapshot_history(
    snapshots: tuple[Snapshot, ...], chart_ui: IndicatorUI = st
) -> None:
    """Offer an optional timeline without changing single-snapshot analysis."""
    if not st.toggle("Show CSV archive history chart"):
        return

    def snapshot_label(index: int) -> str:
        return snapshots[index].timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    selected = st.multiselect(
        "Snapshots to chart (UTC)",
        range(len(snapshots)),
        default=list(range(len(snapshots))),
        format_func=snapshot_label,
    )
    if not selected:
        _ = st.info("Select at least one snapshot to chart.")
        return
    with st.spinner("Calculating archived snapshot levels…"):
        history = snapshot_history(
            tuple(snapshots[index] for index in selected)
        )
    prices = render_archive_prices(
        tuple(snapshots[index] for index in selected)
    )
    _ = chart_ui.plotly_chart(
        history_chart(history, prices=prices), use_container_width=True
    )
    _ = st.caption(
        "Each marker uses that snapshot's recorded spot, OI and IV across all"
        " expiries. Lines connect observations; they do not fill archive gaps."
        " Call 1/2 and Put 1/2 retain the independent P1/P2/N1/N2 ranks. Gamma"
        " flip is the nearest crossing in the strike search range; missing"
        " crossings remain blank. GEX assumes calls positive and puts negative."
        " Green GEX markers are positive; red markers are negative."
    )
    _ = st.dataframe(history, hide_index=True, use_container_width=True)
    render_snapshot_comparison(
        tuple(snapshots[index] for index in selected), chart_ui
    )
    render_daily_snapshot(
        tuple(snapshots[index] for index in selected), chart_ui
    )


def render_daily_snapshot(
    snapshots: tuple[Snapshot, ...], chart_ui: IndicatorUI = st
) -> None:
    """Show the original strike profile for a recorded snapshot on a day."""
    days = sorted(
        {snapshot.timestamp.astimezone(UTC).date() for snapshot in snapshots}
    )
    selected_day = st.selectbox("Archive day (UTC)", days, index=len(days) - 1)
    daily = sorted(
        (
            snapshot
            for snapshot in snapshots
            if snapshot.timestamp.astimezone(UTC).date() == selected_day
        ),
        key=lambda snapshot: snapshot.timestamp,
    )

    def snapshot_label(index: int) -> str:
        return daily[index].timestamp.astimezone(UTC).strftime("%H:%M:%S UTC")

    index = st.selectbox(
        "Day snapshot (UTC)", range(len(daily)), format_func=snapshot_label
    )
    snapshot = daily[index]
    _ = st.caption(
        f"Single snapshot: {snapshot.timestamp.isoformat()} · "
        f"{len(snapshot.options)} contracts. Exposure by strike and gamma "
        "flip search use this recorded chain."
    )
    chart = exposure_chart(snapshot, flip_search=search_flips(snapshot))
    _ = chart.update_layout(
        title=(
            f"{snapshot.asset} archive snapshot ·"
            f" {snapshot.timestamp.isoformat()}"
        )
    )
    _ = chart_ui.plotly_chart(chart, use_container_width=True)
