# Copyright 2026 anchored-vwam-backtest contributors
"""Shared price and momentum panels independent from live data sources."""

from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from gui_calculator.options_profile_chart import style_options_chart

if TYPE_CHECKING:
    from datetime import datetime


def oscillator_chart(
    *, title: str, price_label: str, thresholds: tuple[int, int] = (30, 70)
) -> go.Figure:
    """Build separate price and 0-100 oscillator panels with reference zones.

    Returns:
        An interactive chart ready for timestamped observations.

    """
    chart = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.64, 0.36],
        vertical_spacing=0.0,
    )
    for lower, upper, color in (
        (thresholds[0], thresholds[0] + 8, "rgba(22,163,74,0.12)"),
        (thresholds[1] - 8, thresholds[1], "rgba(220,38,38,0.12)"),
    ):
        _ = chart.add_hrect(
            y0=lower,
            y1=upper,
            fillcolor=color,
            line_width=0,
            row=2,
            col=1,
            exclude_empty_subplots=False,
        )
    for level, color in (
        (thresholds[0], "#16a34a"),
        (50, "#94a3b8"),
        (thresholds[1], "#dc2626"),
    ):
        _ = chart.add_hline(
            y=level,
            line_dash="dot",
            line_color=color,
            row=2,
            col=1,
            exclude_empty_subplots=False,
        )
    _ = chart.update_yaxes(title_text=price_label, side="right", row=1, col=1)
    _ = chart.update_yaxes(
        title_text="Oscillator",
        range=[0, 100],
        tickvals=[0, thresholds[0], 50, thresholds[1], 100],
        row=2,
        col=1,
    )
    _ = chart.update_layout(
        title=title, height=650, hovermode="x unified", showlegend=False
    )
    chart = style_options_chart(chart)
    _ = chart.update_xaxes(type="date", tickformat="%d %b", gridcolor="#f1f5f9")
    _ = chart.update_yaxes(gridcolor="#f1f5f9")
    return chart


def add_oscillator_trace(
    chart: go.Figure,
    times: list[datetime],
    values: list[float | None],
    *,
    thresholds: tuple[int, int] = (30, 70),
) -> None:
    """Draw the oscillator and highlight entries into its extreme zones."""
    plotted = [value if value is not None else float("nan") for value in values]
    _ = chart.add_trace(
        go.Scatter(
            x=times,
            y=plotted,
            name="Oscillator",
            mode="lines+markers" if len(values) == 1 else "lines",
            connectgaps=False,
            line={"color": "#64748b", "width": 2},
        ),
        row=2,
        col=1,
    )
    for side, color, symbol, threshold in (
        ("LONG", "#16a34a", "arrow-up", thresholds[0]),
        ("SHORT", "#dc2626", "arrow-down", thresholds[1]),
    ):
        active = [
            value is not None
            and (value <= threshold if side == "LONG" else value >= threshold)
            for value in values
        ]
        entries = [
            index
            for index in range(1, len(values))
            if active[index]
            and not active[index - 1]
            and values[index - 1] is not None
        ]
        _ = chart.add_trace(
            go.Scatter(
                x=times,
                y=[
                    value if extreme else float("nan")
                    for value, extreme in zip(plotted, active, strict=True)
                ],
                name=f"{side} zone",
                showlegend=False,
                connectgaps=False,
                line={"color": color, "width": 2},
            ),
            row=2,
            col=1,
        )
        _ = chart.add_trace(
            go.Scatter(
                x=[times[index] for index in entries],
                y=[plotted[index] for index in entries],
                name=f"{side} threshold entry",
                mode="markers+text",
                text=[side] * len(entries),
                textfont={"color": color},
                textposition=(
                    "bottom center" if side == "LONG" else "top center"
                ),
                marker={"color": color, "symbol": symbol, "size": 16},
            ),
            row=2,
            col=1,
        )
