# Copyright 2026 anchored-vwam-backtest contributors
"""Native Python chart for held OI divergence at a selected GEX snapshot."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
from snapshot_tunnel.oi_divergence import (
    DivergenceSeries,
    DivergenceSettings,
    divergence_series,
)

from gui_calculator.options_profile_chart import style_options_chart
from gui_calculator.snapshot_oi_data import load_snapshot_oi

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot

    from gui_calculator.view_types import IndicatorUI


def oi_state_chart(
    series: DivergenceSeries, snapshot: Snapshot, *, days: int
) -> go.Figure:
    """Build synchronized price, signed OI momentum and binary state panels.

    Returns:
        A native Plotly figure with state transitions at detection time.

    """
    chart = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.5, 0.3, 0.2],
        vertical_spacing=0.04,
    )
    for row, name, times, values, color in (
        (
            1,
            "Price",
            [point.sample.interest.timestamp for point in series.points],
            [point.sample.price for point in series.points],
            "#f59e0b",
        ),
        (
            2,
            "OI change % · 12 bars · SMA 3",
            [point.available for point in series.points],
            [
                point.rate if point.rate is not None else float("nan")
                for point in series.points
            ],
            "#64748b",
        ),
        (
            3,
            "OI divergence state",
            [point.available for point in series.points],
            [
                float(value) if value is not None else float("nan")
                for value in series.states
            ],
            "#9333ea",
        ),
    ):
        for index in reversed(range(1, len(times))):
            if times[index] - times[index - 1] > timedelta(hours=1):
                times.insert(index, times[index] - timedelta(hours=1))
                values.insert(index, float("nan"))
        _ = chart.add_trace(
            go.Scatter(
                x=times,
                y=values,
                name=name,
                mode="lines",
                connectgaps=False,
                line={
                    "color": color,
                    "shape": (
                        "hv" if name == "OI divergence state" else "linear"
                    ),
                },
            ),
            row=row,
            col=1,
        )
    _add_detection_markers(chart, series)
    _ = chart.update_yaxes(title_text=f"{snapshot.asset}USDT", row=1, col=1)
    _ = chart.update_yaxes(title_text="OI change %", row=2, col=1)
    _ = chart.add_hline(y=0, line_dash="dot", row=2, col=1)
    _ = chart.update_yaxes(
        title_text="Divergence",
        range=[-0.1, 1.1],
        tickvals=[0, 1],
        ticktext=["0 · No divergence", "1 · Divergence"],
        row=3,
        col=1,
    )
    _ = chart.update_layout(
        title=f"{snapshot.asset} OI divergence · snapshot history",
        height=800,
        hovermode="x unified",
        showlegend=True,
    )
    chart = style_options_chart(chart)
    _ = chart.update_xaxes(
        range=[snapshot.timestamp - timedelta(days=days), snapshot.timestamp]
    )
    return chart


def _add_detection_markers(chart: go.Figure, series: DivergenceSeries) -> None:
    """Explain each detected comparison without placing state at past peaks."""
    for state, color, symbol in (
        (1, "#9333ea", "diamond"),
        (0, "#007f91", "circle"),
    ):
        signals = [signal for signal in series.signals if signal.state == state]
        descriptions: list[str] = []
        for signal in signals:
            current = signal.current.point.sample.interest.timestamp
            previous = signal.previous.point.sample.interest.timestamp
            oi_time = series.points[
                signal.current.oi_index
            ].sample.interest.timestamp
            descriptions.append(
                f"{signal.label}<br>Price swing: {current.isoformat()}<br>OI"
                f" extreme: {oi_time.isoformat()}<br>Detected:"
                f" {signal.detected.isoformat()}<br>Previous price swing:"
                f" {previous.isoformat()}<br>OI: {signal.previous.rate:.3f}% →"
                f" {signal.current.rate:.3f}%"
            )
        _ = chart.add_trace(
            go.Scatter(
                x=[signal.detected for signal in signals],
                y=[state] * len(signals),
                name=(
                    "Divergence detected" if state else "Confirmation detected"
                ),
                mode="markers",
                marker={"color": color, "symbol": symbol, "size": 9},
                text=descriptions,
                hovertemplate="%{text}<extra></extra>",
            ),
            row=3,
            col=1,
        )


def render_snapshot_oi(snapshot: Snapshot) -> None:
    """Offer an opt-in Python-only oscillator alongside snapshot indicators."""
    if not st.toggle(
        "Show OI divergence oscillator", key="snapshot_oi_divergence"
    ):
        return
    period = st.selectbox(
        "OI oscillator history", ("24 hours", "Week", "Month"), index=1
    )
    days = {"24 hours": 1, "Week": 7, "Month": 30}[period]
    settings = DivergenceSettings(
        min_swing_percent=st.number_input(
            "OI minimum price swing (%)",
            min_value=0.0,
            value=0.1,
            step=0.01,
        ),
        min_oi_change=st.number_input(
            "OI minimum oscillator change (percentage points)",
            min_value=0.0,
            value=0.05,
            step=0.01,
        ),
    )
    try:
        with st.spinner(
            "Loading snapshot-aligned Bybit OI and completed hourly candles…"
        ):
            series = divergence_series(
                load_snapshot_oi(snapshot, days=days), settings=settings
            )
    except (
        requests.RequestException,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
    ) as exc:
        _ = st.warning(f"OI divergence oscillator unavailable: {exc}")
        return
    _show_oi_series(series, snapshot, days=days, chart_ui=st)


def _show_oi_series(
    series: DivergenceSeries,
    snapshot: Snapshot,
    *,
    days: int,
    chart_ui: IndicatorUI,
) -> None:
    """Present held state, its age and the assumptions behind the history."""
    _ = chart_ui.plotly_chart(
        oi_state_chart(series, snapshot, days=days), use_container_width=True
    )
    stale = bool(
        series.points
        and snapshot.timestamp - series.points[-1].available
        >= timedelta(hours=1)
    )
    current = series.states[-1] if series.states and not stale else None
    status = "No signal yet" if current is None else str(current)
    if stale:
        status = "Unavailable (data gap)"
    _ = st.metric(
        "OI divergence state",
        status,
    )
    if current is not None and series.signals:
        _ = st.caption(
            "Latest qualifying comparison detected:"
            f" {series.signals[-1].detected.isoformat()}. State holds until"
            " another qualifying comparison."
        )
    _ = st.caption(
        "1 = divergence; 0 = no divergence (confirmation). State holds until"
        " the next qualifying comparison; before the first signal or after"
        " missing data it is unavailable. Price higher high + lower OI high,"
        " or lower low + higher OI low, indicates divergence. Matching"
        " directions indicate confirmation. Price swings use 2 bars per side;"
        " OI extrema match within ±1 bar. States change 2 bars after the price"
        " swing, plus an assumed 1-minute OI publication delay. Momentum ="
        " SMA(3) of 100 * (contract OI / OI 12 hours ago - 1). Uses base-asset"
        " Bybit linear OI and completed 1h closes, with 2 extra days for"
        " initialization. Gaps reset warmup and state. Exchange historical"
        " data may be revised; publication receipt times are not recorded."
        " Participation context, not a reversal forecast or trading signal."
        f" Window ends at options snapshot {snapshot.timestamp.isoformat()}."
    )
    if current is None:
        _ = st.info(
            "No qualifying OI swing comparison yet in the available continuous"
            " history."
        )
