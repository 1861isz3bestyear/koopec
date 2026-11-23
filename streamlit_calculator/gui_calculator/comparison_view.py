# Copyright 2026 anchored-vwam-backtest contributors
"""Compare observed GEX structure without inferring dealer inventories."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import plotly.graph_objects as go
import streamlit as st
from snapshot_tunnel.gamma_search import search_flips
from snapshot_tunnel.options_model import net_exposure

from gui_calculator.options_profile_chart import style_options_chart
from gui_calculator.snapshot_comparison import (
    compare_breakdown as compare_breakdown,
)
from gui_calculator.snapshot_comparison import (
    comparison_summary as comparison_summary,
)
from gui_calculator.snapshot_comparison import (
    exposure_breakdown as exposure_breakdown,
)

if TYPE_CHECKING:
    import pandas as pd
    from snapshot_tunnel.options_model import Snapshot

    from gui_calculator.view_types import IndicatorUI


def breakdown_chart(
    data: pd.DataFrame, *, scope: Literal["Strike", "Expiry"]
) -> go.Figure:
    """Compare net concentrations and expose side totals in hover labels.

    Returns:
        A grouped signed exposure chart.

    """
    chart = go.Figure()
    for label, color in (("Before", "#0369a1"), ("After", "#7e22ce")):
        _ = chart.add_trace(
            go.Bar(
                x=data.index.to_list(),
                y=data[f"{label} Net GEX"],
                name=label,
                marker_color=color,
                customdata=data[
                    [f"{label} Call GEX", f"{label} Put GEX"]
                ].to_numpy(dtype=float),
                hovertemplate=(
                    "%{x}<br>Net: $%{y:,.0f}<br>Call:"
                    " $%{customdata[0]:,.0f}<br>Put:"
                    " $%{customdata[1]:,.0f}<extra>%{fullData.name}</extra>"
                ),
            )
        )
    _ = chart.add_hline(y=0, line_color="#111827")
    _ = chart.update_layout(
        title=f"GEX by {scope.lower()} · before / after",
        barmode="group",
        height=500,
        xaxis_title=f"{scope} (USD)" if scope == "Strike" else "Expiry (UTC)",
        yaxis_title="Net GEX (USD / 1% move)",
    )
    if scope == "Expiry":
        _ = chart.update_xaxes(type="category")
    return style_options_chart(chart)


def regime_chart(snapshot: Snapshot) -> go.Figure:
    """Show actual modeled signs across prices and every detected crossing.

    Returns:
        A signed, shaded repricing curve with observed spot marked.

    """
    result = search_flips(snapshot)
    prices = sorted(
        set(
            result.search.prices(
                snapshot.spot,
                strikes=tuple(option.strike for option in snapshot.options),
            )
        )
        | set(result.roots)
        | {snapshot.spot}
    )
    values = [net_exposure(snapshot, price) for price in prices]
    chart = go.Figure()
    for label, color, positive in (
        ("Positive model GEX", "#15803d", True),
        ("Negative model GEX", "#be123c", False),
    ):
        _ = chart.add_trace(
            go.Scatter(
                x=prices,
                y=[
                    max(value, 0) if positive else min(value, 0)
                    for value in values
                ],
                name=label,
                mode="lines",
                fill="tozeroy",
                line={"color": color},
            )
        )
    for root in result.roots:
        _ = chart.add_vline(
            x=root,
            line_dash="dot",
            line_color="#0369a1",
            annotation_text=f"Flip ${root:,.2f}",
        )
    _ = chart.add_trace(
        go.Scatter(
            x=[snapshot.spot],
            y=[net_exposure(snapshot, snapshot.spot)],
            mode="markers",
            marker={"color": "#111827", "size": 12},
            name=f"Observed spot ${snapshot.spot:,.2f}",
        )
    )
    _ = chart.update_layout(
        title=f"Current snapshot · GEX regimes · {result.status.value}",
        xaxis_title="Hypothetical underlying price (USD)",
        yaxis_title="Net GEX (USD / 1% move)",
        height=500,
    )
    return style_options_chart(chart)


def render_snapshot_comparison(
    snapshots: tuple[Snapshot, ...], chart_ui: IndicatorUI = st
) -> None:
    """Offer explicit before/after views of the levels discussed in a review."""
    if not st.toggle("Compare snapshot regimes, strikes and expiries"):
        return
    ordered = sorted(snapshots, key=lambda snapshot: snapshot.timestamp)
    if len(ordered) <= 1:
        _ = st.info("Select at least two archive snapshots to compare.")
        return

    def label(index: int) -> str:
        return ordered[index].timestamp.isoformat()

    before_index = st.selectbox(
        "Before snapshot (UTC)", range(len(ordered) - 1), format_func=label
    )
    after_index = st.selectbox(
        "After snapshot (UTC)",
        range(before_index + 1, len(ordered)),
        format_func=label,
    )
    render_comparison_pair(
        ordered[before_index], ordered[after_index], chart_ui
    )


def render_comparison_pair(
    before: Snapshot, after: Snapshot, chart_ui: IndicatorUI = st
) -> None:
    """Display the same comparison for archive and single-snapshot requests."""
    _ = st.caption(
        f"Before: {before.timestamp.isoformat()} · "
        f"After: {after.timestamp.isoformat()} · {after.asset}"
    )
    _ = st.dataframe(
        comparison_summary(before, after), use_container_width=True
    )
    _ = st.caption(
        f"Spot change: {(after.spot / before.spot - 1) * 100:+.2f}%. "
        "Positive GEX is green; negative is red in the regime curve. "
        "The sign is calculated, not inferred from being above a flip."
    )
    _ = chart_ui.plotly_chart(regime_chart(after), use_container_width=True)
    for scope in ("Strike", "Expiry"):
        data = compare_breakdown(before, after, scope=scope)
        chart = breakdown_chart(data, scope=scope)
        if scope == "Strike":
            _ = chart.add_vline(
                x=after.spot, line_dash="dash", annotation_text="Current spot"
            )
        _ = chart_ui.plotly_chart(chart, use_container_width=True)
        _ = st.dataframe(data, use_container_width=True)
    _ = st.caption(
        "Calls-positive / puts-negative is a model convention, not observed "
        "dealer positioning. Concentrations are not guaranteed support, "
        "resistance, magnets or targets. GEX changes can reflect spot, time, "
        "IV, OI and chain coverage; they do not prove calls were bought or "
        "puts closed. Missing strikes/expiries remain blank. Repricing fixes "
        "this snapshot's OI and IV; shaded regimes are not a price forecast."
    )
