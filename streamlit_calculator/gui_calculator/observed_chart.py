# Copyright 2026 anchored-vwam-backtest contributors
"""Plot native-time oscillator histories on the shared market timeline."""

from __future__ import annotations

from datetime import UTC, tzinfo
from typing import TYPE_CHECKING

import plotly.graph_objects as go
from shared.time_utils import chart_times

if TYPE_CHECKING:
    from gui_calculator.observed_history import RecordedCharts


_COLORS = ("#007f91", "#b45309", "#7c3aed", "#be123c", "#047857")
_OI_STATE_PANEL = 7


def add_observed_oscillators(
    chart: go.Figure,
    history: RecordedCharts,
    *,
    subplots: bool = False,
    timezone: tzinfo = UTC,
) -> None:
    """Add each oscillator at its own receipts, retaining gaps and warmup."""
    for series, color in zip(history.oscillators, _COLORS, strict=True):
        trace = go.Scatter(
            x=chart_times(series.data["time"], timezone),
            y=series.data["value"],
            name=series.name,
            mode="lines",
            line={
                "color": color,
                "width": 1.5,
                "shape": "hv" if series.panel == _OI_STATE_PANEL else "linear",
                "dash": (
                    "dash" if series.name == "OI convergence state" else "solid"
                ),
            },
            connectgaps=False,
            hovertemplate="%{x}<br>"
            + series.name
            + ": %{y:.3f}<extra></extra>",
        )
        if subplots:
            _ = chart.add_trace(trace, row=series.panel - 1, col=1)
        else:
            trace.yaxis = f"y{series.panel + 2}"
            _ = chart.add_trace(trace)


def style_observed_chart(chart: go.Figure) -> go.Figure:
    """Use a compact terminal presentation for receipt-time line histories.

    Returns:
        White plotting cards, subtle dotted grids and readable numeric labels.

    """
    _ = chart.update_layout(
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": "Arial, sans-serif", "size": 12, "color": "#111827"},
        title_font={"size": 16, "color": "#111827"},
        title={"x": 0.025, "y": 0.985, "xanchor": "left", "yanchor": "top"},
        margin={"l": 75, "r": 30, "t": 125, "b": 45},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": "#ffffff",
            "bordercolor": "#d1d5db",
            "font": {"color": "#111827", "size": 12},
        },
        legend={
            "maxheight": 60,
            "orientation": "h",
            "x": 0,
            "y": 1.025,
            "yanchor": "bottom",
            "font": {"size": 11, "color": "#111827"},
        },
    )
    _ = chart.update_xaxes(
        gridcolor="#e5e7eb",
        griddash="dot",
        zeroline=False,
        showline=False,
        tickfont={"size": 11, "color": "#374151"},
        hoverformat="%d %b %Y %H:%M:%S UTC",
    )
    _ = chart.update_yaxes(
        gridcolor="#e5e7eb",
        griddash="dot",
        showline=False,
        tickfont={
            "family": "ui-monospace, monospace",
            "size": 11,
            "color": "#374151",
        },
        zerolinecolor="#d1d5db",
        zerolinewidth=1,
    )
    return chart
