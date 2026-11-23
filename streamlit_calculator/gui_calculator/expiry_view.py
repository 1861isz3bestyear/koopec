# Copyright 2026 anchored-vwam-backtest contributors
"""Isolate the exposure removed by an upcoming options expiry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go
import streamlit as st
from snapshot_tunnel.options_model import (
    Snapshot,
    net_exposure,
    strike_exposures,
)

from gui_calculator.expiry_impact import (
    ExpiryImpact,
    wall_label,
)
from gui_calculator.expiry_impact import (
    analyze_expiry as analyze_expiry,
)
from gui_calculator.expiry_impact import (
    expiry_outlook as expiry_outlook,
)
from gui_calculator.options_profile_chart import style_options_chart

if TYPE_CHECKING:

    from gui_calculator.view_types import IndicatorUI


def expiry_price_chart(impact: ExpiryImpact) -> go.Figure:
    """Compare signed GEX across hypothetical underlying prices.

    Returns:
        A fixed-IV, fixed-time removal scenario, not a price forecast.

    """
    prices = [impact.before.spot * (0.8 + index * 0.005) for index in range(81)]
    chart = go.Figure()
    for label, snapshot in (
        ("Current chain", impact.before),
        ("Without selected expiry", impact.remaining),
    ):
        _ = chart.add_trace(
            go.Scatter(
                x=prices,
                y=[net_exposure(snapshot, price) for price in prices],
                name=label,
                mode="lines",
            )
        )
    _ = chart.add_vline(x=impact.before.spot, annotation_text="Snapshot spot")
    _ = chart.add_hline(y=0)
    _ = chart.update_layout(
        title="Expiry removal: GEX sensitivity to price",
        xaxis_title="Hypothetical underlying price (USD)",
        yaxis_title="Model GEX (USD / 1% move)",
    )
    return style_options_chart(chart)


def _expiry_strike_chart(impact: ExpiryImpact) -> go.Figure:
    """Show which call and put exposures disappear at each strike.

    Returns:
        Gross side exposures for the expiring contracts.

    """
    levels = strike_exposures(impact.expiring)
    chart = go.Figure()
    for label, values in (
        ("Expiring call GEX", [level.call for level in levels]),
        ("Expiring put GEX", [level.put for level in levels]),
    ):
        _ = chart.add_trace(
            go.Bar(x=[level.strike for level in levels], y=values, name=label)
        )
    _ = chart.add_vline(x=impact.before.spot, annotation_text="Snapshot spot")
    _ = chart.update_layout(
        title="Exposure disappearing at the selected expiry",
        xaxis_title="Strike (USD)",
        yaxis_title="Model GEX (USD / 1% move)",
        barmode="relative",
    )
    annotation = go.layout.Annotation(
        x=0,
        y=-0.25,
        xref="paper",
        yref="paper",
        xanchor="left",
        yanchor="top",
        align="left",
        showarrow=False,
        text=expiry_outlook(impact),
        font={"size": 11},
    )
    _ = chart.update_layout(
        annotations=(*chart.layout.annotations, annotation), margin={"b": 180}
    )
    return style_options_chart(chart)


def render_expiry_impact(snapshot: Snapshot, chart_ui: IndicatorUI) -> None:
    """Display expiry concentration, wall shifts and price scenarios."""
    upcoming = sorted({
        option.expiry
        for option in snapshot.options
        if option.expiry > (snapshot.valuation_time or snapshot.timestamp)
    })
    if not upcoming:
        _ = st.info("No upcoming expiries in this snapshot.")
        return
    _ = st.subheader("Upcoming expiry impact")
    expiry = st.selectbox("Analyze expiry (UTC) · nearest first", upcoming)
    impact = analyze_expiry(snapshot, expiry=expiry)
    hours = (
        expiry - (snapshot.valuation_time or snapshot.timestamp)
    ).total_seconds() / 3600
    _ = st.caption(
        f"{expiry:%Y-%m-%d %H:%M} UTC · {hours:,.1f} hours from snapshot · "
        f"{impact.absolute_share:.1%} of absolute chain GEX expires. "
        "Use the expiry table above to identify larger later expirations."
    )
    _ = st.dataframe(
        [
            {
                "Scenario": label,
                "Net GEX (USD / 1%)": net_exposure(chain, chain.spot),
                "Call wall": wall_label(chain, side="call"),
                "Put wall": wall_label(chain, side="put"),
            }
            for label, chain in (
                ("Current chain", snapshot),
                ("Without selected expiry", impact.remaining),
            )
        ],
        hide_index=True,
    )
    _ = chart_ui.plotly_chart(
        _expiry_strike_chart(impact), use_container_width=True
    )
    _ = chart_ui.plotly_chart(
        expiry_price_chart(impact), use_container_width=True
    )
    _ = st.caption(
        "Removal-only scenario: valuation time, spot, IV and surviving OI are "
        "held fixed. This is not a forecast of post-expiry gamma; time decay, "
        "new trades and rolls can change the outcome. No surviving contracts "
        "means zero modeled GEX and unavailable walls."
    )
    _ = st.info(
        "Price interpretation: under the call-positive / put-negative dealer "
        "gamma assumption, positive GEX can dampen moves and negative GEX can "
        "amplify them. Removing a large expiry may weaken or shift those "
        "effects and the displayed walls. Expiring strikes may be pinning "
        "areas before settlement, but walls are not guaranteed support or "
        "resistance. Neither GEX nor expiry determines price direction; actual "
        "dealer positioning and settlement flows are not observed here."
    )
