# Copyright 2026 anchored-vwam-backtest contributors
"""Describe strike balance and wall distances without directional forecasts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from shared.option_levels import DEFAULT_LEVEL_RANGE, OptionLevelRange

from gui_calculator.options_profile_chart import style_options_chart
from gui_calculator.snapshot_balance import (
    ExtremumDistance as ExtremumDistance,
)
from gui_calculator.snapshot_balance import (
    SnapshotBalance as SnapshotBalance,
)
from gui_calculator.snapshot_balance import (
    StrikeBalance as StrikeBalance,
)
from gui_calculator.snapshot_balance import (
    snapshot_balance as snapshot_balance,
)

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot

type StrikeRegion = Literal["Below spot", "At spot", "Above spot"]


def snapshot_balance_chart(
    snapshot: Snapshot, *, level_range: OptionLevelRange = DEFAULT_LEVEL_RANGE
) -> go.Figure:
    """Build the custom snapshot instrument from measured exposures.

    Returns:
        Strike balance, signed wall distance and normalized net GEX panels.

    """
    balance = snapshot_balance(snapshot, level_range=level_range)
    chart = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=[
            "GEX by strike location",
            "Wall distance from spot",
            "Net / absolute GEX",
        ],
        horizontal_spacing=0.12,
    )
    for name, values, color in (
        ("Call GEX", [r.call for r in balance.regions], "#15803d"),
        ("Put GEX", [r.put for r in balance.regions], "#be123c"),
    ):
        _ = chart.add_trace(
            go.Bar(
                x=[r.region for r in balance.regions],
                y=values,
                name=name,
                marker_color=color,
                hovertemplate="%{x}: $%{y:,.0f}<extra>" + name + "</extra>",
            ),
            row=1,
            col=1,
        )
    walls = [
        (name, distance, color)
        for name, distance, color in (
            ("Put wall", balance.put_distance, "#be123c"),
            ("Call wall", balance.call_distance, "#15803d"),
        )
        if distance is not None
    ]
    walls.extend(
        (f"Extremum ${level.strike:,.2f}", level.percent, "#b45309")
        for level in balance.extremum_distances
    )
    _ = chart.add_trace(
        go.Bar(
            x=[name for name, _, _ in walls],
            y=[distance for _, distance, _ in walls],
            marker_color=[color for _, _, color in walls],
            texttemplate="%{y:+.2f}%",
            hovertemplate="%{x}: %{y:+.2f}%<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    _ = chart.add_trace(
        go.Bar(
            x=["Model balance"],
            y=[] if balance.net_percent is None else [balance.net_percent],
            marker_color="#0369a1",
            texttemplate="%{y:+.2f}%",
            hovertemplate="Net / absolute GEX: %{y:+.2f}%<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=3,
    )
    _ = chart.update_yaxes(title_text="USD / 1% move", row=1, col=1)
    _ = chart.update_yaxes(title_text="Distance (%)", row=1, col=2)
    _ = chart.update_yaxes(title_text="Balance (%)", range=[-100, 100], col=3)
    _ = chart.update_layout(
        title=f"{snapshot.asset} · Strike balance instrument",
        barmode="relative",
        height=460,
        legend={"orientation": "h", "y": -0.25},
        margin={"b": 100},
    )
    return style_options_chart(chart)
