# Copyright 2026 anchored-vwam-backtest contributors
"""Display independent oscillator evidence on the backtest price timeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go
from shared.time_utils import chart_times
from snapshot_tunnel.tunnel_flow import BOTH_DIRECTIONS

if TYPE_CHECKING:
    from datetime import tzinfo

    import pandas as pd


_STREAMS = (
    ("book", "Limit-order", "#007f91"),
    ("margin", "Margin-loan", "#b45309"),
    ("retest", "Retest", "#15803d"),
    ("oi", "OI divergence", "#7c3aed"),
    ("oi_momentum", "High OI momentum (either direction)", "#7c3aed"),
    ("oi_convergence", "OI convergence", "#7c3aed"),
    ("gex", "GEX state", "#1d4ed8"),
)


def add_tunnel_confirmations(
    chart: go.Figure, data: pd.DataFrame, *, timezone: tzinfo
) -> None:
    """Mark fresh enabled votes independently of GEX and executed trades."""
    for source, label, color in _STREAMS:
        column = f"tunnel_confirmation_{source}"
        if column not in data:
            continue
        markers = (
            ((1, "either breakout", "diamond"),)
            if source == "oi_momentum"
            else ((1, "long", "triangle-up"), (-1, "short", "triangle-down"))
        )
        for direction, side, symbol in markers:
            votes = (
                (direction, BOTH_DIRECTIONS)
                if source == "retest"
                else (direction,)
            )
            points = data.loc[data[column].isin(votes)]
            _ = chart.add_trace(
                go.Scatter(
                    x=chart_times(points["time"], timezone),
                    y=points["open"],
                    name=f"{label} confirms {side}",
                    mode="markers",
                    marker={
                        "symbol": symbol,
                        "color": color,
                        "size": 10,
                        "line": {"color": "#111827", "width": 1},
                    },
                    hovertemplate=(
                        "%{x}<br>"
                        f"{label} confirms {side}"
                        "<br>Opening quote: %{y}<extra></extra>"
                    ),
                )
            )
