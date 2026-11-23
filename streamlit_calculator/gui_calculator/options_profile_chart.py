# Copyright 2026 anchored-vwam-backtest contributors
"""Shared strike profile charts for single observations and archive browsing."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from shared.option_levels import DEFAULT_LEVEL_RANGE, OptionLevelRange
from snapshot_tunnel.options_model import (
    Snapshot,
    net_exposure,
)

from gui_calculator.charts import add_hover_crosshair
from gui_calculator.rust_backend import max_pain, ranked_walls, strike_exposures

if TYPE_CHECKING:
    from snapshot_tunnel.gamma_search import FlipResult

_PRICE_TICK_FORMAT = "$,.2f"


def wall_levels_chart(
    snapshot: Snapshot,
    *,
    gamma_flip: float | None = None,
    level_range: OptionLevelRange = DEFAULT_LEVEL_RANGE,
) -> go.Figure:
    """Display independent ranked call/put strikes, spot and gamma flip.

    Returns:
        Four side-ranked price levels using the exposure chart definitions.

    """
    levels = strike_exposures(snapshot)
    walls = ranked_walls(levels, spot=snapshot.spot, level_range=level_range)
    chart = go.Figure()
    negative = math.fsum(level.net for level in levels) < 0
    ranked = (
        tuple(
            (f"Option border {index}", strike, "#92400e")
            for index, strike in enumerate(
                sorted({level.strike for level in (*walls.calls, *walls.puts)}),
                start=1,
            )
        )
        if negative
        else tuple(
            (f"{side} {rank}", level.strike, color)
            for side, ranks, color in (
                ("Call", walls.calls, "#15803d"),
                ("Put", walls.puts, "#be123c"),
            )
            for rank, level in enumerate(ranks, start=1)
        )
    )
    for name, strike, color in ranked:
        _ = chart.add_trace(
            go.Scatter(
                x=[0, 1],
                y=[strike] * 2,
                mode="lines",
                name=name,
                line={"color": color, "width": 3},
                hovertemplate=name + ": $%{y:,.2f}<extra></extra>",
            )
        )
    _ = chart.add_trace(
        go.Scatter(
            x=[0, 1],
            y=[snapshot.spot] * 2,
            mode="lines",
            name="Snapshot spot",
            line={"color": "#0369a1", "width": 4, "dash": "dot"},
            hovertemplate="Spot: $%{y:,.2f}<extra></extra>",
        )
    )
    if gamma_flip is not None:
        _ = chart.add_trace(
            go.Scatter(
                x=[0, 1],
                y=[gamma_flip] * 2,
                mode="lines",
                name=f"Gamma flip ${gamma_flip:,.2f}",
                line={"color": "#7c3aed", "width": 4, "dash": "dash"},
                hovertemplate="Gamma flip: $%{y:,.2f}<extra></extra>",
            )
        )
    title = "Option breakout borders" if negative else "Ranked call/put levels"
    _label_tunnel_prices(chart)
    _ = chart.update_layout(
        title=f"{snapshot.asset} · {title} · {snapshot.timestamp:%H:%M UTC}",
        height=520,
        margin={"l": 85, "r": 20, "t": 65, "b": 85},
        xaxis={"visible": False, "range": [0, 1], "domain": [0, 0.58]},
        yaxis={"title": "Price (USD)", "tickformat": _PRICE_TICK_FORMAT},
        legend={"orientation": "h", "y": -0.15, "yanchor": "top"},
    )
    return style_options_chart(chart)


def _label_tunnel_prices(chart: go.Figure) -> None:
    """Place price badges in a separate rail so nearby levels stay legible."""
    labels: dict[float, list[str]] = {}
    colors: dict[float, str] = {}
    for trace in chart.data:
        if isinstance(trace, go.Scatter):
            price = float(trace.y[0])
            name = str(trace.name)
            if name.startswith("Gamma flip"):
                name = "Gamma flip"
            labels.setdefault(price, []).append(name)
            colors[price] = {
                "Snapshot spot": "#0369a1",
                "Gamma flip": "#7c3aed",
                "Put 1": "#be123c",
                "Put 2": "#be123c",
                "Call 1": "#15803d",
                "Call 2": "#15803d",
            }.get(name, "#92400e")
    for index, price in enumerate(sorted(labels, reverse=True)):
        names = labels[price]
        annotation = go.layout.Annotation(
            x=0.63,
            xref="paper",
            y=1 - (index + 0.5) / len(labels),
            yref="paper",
            text=f"{' / '.join(names)}<br><b>${price:,.2f}</b>",
            showarrow=False,
            xanchor="left",
            yanchor="middle",
            align="left",
            font={"color": colors[price], "size": 14},
            bordercolor=colors[price],
            borderwidth=2,
            borderpad=6,
            bgcolor="#ffffff",
        )
        _ = chart.update_layout(
            annotations=(*chart.layout.annotations, annotation)
        )


def style_options_chart(chart: go.Figure) -> go.Figure:
    """Keep options charts readable regardless of Streamlit's theme.

    Returns:
        The themed options chart.

    """
    _ = chart.update_layout(
        template="plotly_white",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": "#111827", "size": 12},
        title_font={"color": "#111827", "size": 16},
        legend={"font": {"color": "#111827"}},
        hoverlabel={
            "bgcolor": "#111827",
            "font": {"color": "#ffffff", "size": 12},
        },
    )
    _ = chart.update_xaxes(
        color="#111827",
        tickfont={"color": "#111827"},
        title_font={"color": "#111827"},
        linecolor="#6b7280",
        gridcolor="#d1d5db",
        zerolinecolor="#9ca3af",
    )
    _ = chart.update_yaxes(
        color="#111827",
        tickfont={"color": "#111827"},
        title_font={"color": "#111827"},
        linecolor="#6b7280",
        gridcolor="#d1d5db",
        zerolinecolor="#9ca3af",
    )
    return add_hover_crosshair(chart)


def _annotate_gamma_context(
    chart: go.Figure, snapshot: Snapshot, result: FlipResult
) -> None:
    """Explain the snapshot exposure and nearest crossing inside the chart."""
    nearest = result.nearest
    flip_text = "Gamma flip: no crossing found in search range"
    if nearest is not None:
        distance = (snapshot.spot / nearest - 1) * 100
        flip_text = (
            f"Nearest gamma flip: ${nearest:,.2f}"
            f" · spot vs flip: {distance:+.2f}%"
        )
    if nearest is not None and nearest > snapshot.spot:
        flip_text += "<br><b>Warning: gamma flip is above snapshot price.</b>"
    net = net_exposure(snapshot, snapshot.spot)
    annotation = go.layout.Annotation(
        x=0,
        y=1.13,
        xref="paper",
        yref="paper",
        xanchor="left",
        yanchor="top",
        showarrow=False,
        align="left",
        text=(
            f"{flip_text}<br>Net GEX at spot: ${net:+,.0f} / 1% move"
            f"<br>Flip search: ${result.lower:,.2f} to ${result.upper:,.2f}"
            " · fixed snapshot IV and open interest"
        ),
        font={"color": "#111827", "size": 12},
        bgcolor="#ffffff",
    )
    _ = chart.update_layout(
        annotations=(*chart.layout.annotations, annotation), margin={"t": 170}
    )


def _annotate_nearest_flip(
    chart: go.Figure, snapshot: Snapshot, result: FlipResult
) -> None:
    """Label the nearest crossing away from clustered price markers."""
    nearest = result.nearest
    if nearest is None:
        return
    _ = chart.add_vline(
        x=nearest,
        line_color="#000000",
        line_width=2,
        row=1,
        col=1,
    )
    color = "#dc2626" if nearest > snapshot.spot else "#0369a1"
    annotation = go.layout.Annotation(
        x=1,
        y=0.98,
        xref="paper",
        yref="y3 domain",
        xanchor="right",
        yanchor="top",
        text=f"Gamma flip ${nearest:,.2f}",
        showarrow=False,
        font={"color": color, "size": 14},
        bgcolor="#ffffff",
        bordercolor=color,
        borderpad=6,
    )
    _ = chart.update_layout(annotations=(*chart.layout.annotations, annotation))


def _annotate_walls(
    chart: go.Figure, snapshot: Snapshot, *, level_range: OptionLevelRange
) -> None:
    """Mark the two strongest call and put strikes on the exposure panel."""
    levels = strike_exposures(snapshot)
    walls = ranked_walls(levels, spot=snapshot.spot, level_range=level_range)
    lower = min((level.put for level in levels), default=0.0)
    upper = max((level.call for level in levels), default=0.0)
    for prefix, ranked, color, offset in (
        ("P", walls.calls, "#15803d", 45),
        ("N", walls.puts, "#be123c", -45),
    ):
        for rank, level in enumerate(ranked[:2], start=1):
            side = "CALL" if prefix == "P" else "PUT"
            _ = chart.add_vline(
                x=level.strike,
                line_color=color,
                line_dash="dash",
                line_width=1,
                row=1,
                col=1,
            )
            annotation = go.layout.Annotation(
                x=level.strike,
                y=lower if prefix == "P" else upper,
                yanchor="top" if prefix == "P" else "bottom",
                text=f"<b>{prefix}{rank} · {side}</b><br>${level.strike:,.0f}",
                showarrow=True,
                arrowhead=2,
                arrowcolor=color,
                ax=0,
                ay=offset * rank,
                bgcolor=color,
                bordercolor="#ffffff",
                borderpad=5,
                font={"color": "#ffffff", "size": 12},
                xref="x",
                yref="y",
            )
            _ = chart.update_layout(
                annotations=(*chart.layout.annotations, annotation)
            )


def exposure_chart(
    snapshot: Snapshot,
    *,
    flip_search: FlipResult | None = None,
    level_range: OptionLevelRange = DEFAULT_LEVEL_RANGE,
) -> go.Figure:
    """Build exposure and, optionally, repriced exposure on one price scale.

    Returns:
        The interactive chart.

    """
    levels = strike_exposures(snapshot)
    strikes = [level.strike for level in levels]
    row_count = 3 if flip_search is not None else 2
    row_heights = [0.46, 0.22, 0.32] if flip_search else [0.72, 0.28]
    chart = make_subplots(
        rows=row_count,
        cols=1,
        shared_xaxes=True,
        row_heights=row_heights,
        vertical_spacing=0.06,
    )
    for label, values, color in [
        ("Call (+)", [level.call for level in levels], "#15803d"),
        ("Put (-)", [level.put for level in levels], "#be123c"),
    ]:
        _ = chart.add_trace(
            go.Bar(x=strikes, y=values, name=label, marker_color=color),
            row=1,
            col=1,
        )
    _ = chart.add_trace(
        go.Scatter(
            x=strikes,
            y=[level.absolute for level in levels],
            name="Absolute GEX",
            line={"color": "#7e22ce", "width": 2.5},
            fill="tozeroy",
            fillcolor="rgba(126, 34, 206, 0.10)",
        ),
        row=2,
        col=1,
    )
    if flip_search is not None:
        prices = flip_search.search.prices(
            snapshot.spot,
            strikes=tuple(option.strike for option in snapshot.options),
        )
        _ = chart.add_trace(
            go.Scatter(
                x=prices,
                y=[net_exposure(snapshot, price) for price in prices],
                name="Repriced net GEX",
                line={"color": "#0369a1", "width": 2},
            ),
            row=3,
            col=1,
        )
    _ = chart.add_vline(
        x=snapshot.spot,
        line_dash="dash",
        line_color="#111827",
        line_width=2,
        annotation_text=f"BTCUSDT ${snapshot.spot:,.2f}",
        annotation_position="top",
    )
    _annotate_walls(chart, snapshot, level_range=level_range)
    pain = max_pain(snapshot)
    if pain is not None:
        _ = chart.add_vline(
            x=pain,
            line_dash="dot",
            line_color="#7e22ce",
            annotation_text=f"Max pain ${pain:,.2f}",
            annotation_position="bottom",
            row=2,
            col=1,
        )
    if flip_search is not None:
        _ = chart.add_hline(y=0, line_color="#4b5563", line_width=2, row=3)
        for flip in flip_search.roots:
            _ = chart.add_vline(
                x=flip,
                line_color="#dc2626" if flip > snapshot.spot else "#0369a1",
                line_width=3 if flip == flip_search.nearest else 1,
                line_dash="dot",
                row=3,
            )
        _annotate_nearest_flip(chart, snapshot, flip_search)
        _annotate_gamma_context(chart, snapshot, flip_search)
    _ = chart.update_layout(
        height=800 if flip_search is not None else 650,
        barmode="relative",
        bargap=0.22,
        margin={"l": 65, "r": 25, "b": 45},
        legend={
            "orientation": "h",
            "x": 1,
            "xanchor": "right",
            "y": 1.04,
        },
        title_y=0.99,
        title=(
            f"{snapshot.asset} exposure by strike"
            + (" and gamma flip search" if flip_search else "")
            + f" · spot ${snapshot.spot:,.2f}"
        ),
    )
    _ = chart.update_yaxes(title_text="USD / 1% move", row=1, col=1)
    _ = chart.update_yaxes(
        title_text="USD / 1% move", matches="y", row=2, col=1
    )
    if flip_search is not None:
        _ = chart.update_yaxes(
            title_text="Repriced net GEX (USD / 1% move)",
            row=3,
            col=1,
        )
        _ = chart.update_xaxes(
            range=[flip_search.lower, flip_search.upper],
            title_text="Price / strike (USD)",
            row=3,
            col=1,
        )
    else:
        _ = chart.update_xaxes(title_text="Strike (USD)", row=2, col=1)
    _ = chart.update_xaxes(
        tickformat=_PRICE_TICK_FORMAT,
        hoverformat=_PRICE_TICK_FORMAT,
    )
    chart = style_options_chart(chart)
    _ = chart.update_xaxes(griddash="dash")
    _ = chart.update_yaxes(griddash="dash")
    return chart
