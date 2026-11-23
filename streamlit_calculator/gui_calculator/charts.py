# Copyright 2026 anchored-vwam-backtest contributors
"""Provide charts behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import plotly.graph_objects as go
from shared.time_utils import chart_times, chart_timestamp
from shared.validation import json_object, object_mapping

from gui_calculator.observed_chart import (
    add_observed_oscillators,
    style_observed_chart,
)
from gui_calculator.tunnel_confirmation_chart import add_tunnel_confirmations

_CHART_TEXT_COLOR = "#111827"

if TYPE_CHECKING:
    from datetime import tzinfo

    import pandas as pd
    from shared.models import Trade

    from gui_calculator.observed_history import RecordedCharts


def _apply_chart_theme(fig: go.Figure) -> go.Figure:
    """Apply readable colors to charts on both light and dark app themes.

    Returns:
        The themed chart.

    """
    _ = fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": _CHART_TEXT_COLOR, "size": 12},
        title_font={"color": _CHART_TEXT_COLOR, "size": 16},
        legend={"font": {"color": _CHART_TEXT_COLOR}},
        hoverlabel={
            "bgcolor": "#111827",
            "font": {"color": "#ffffff", "size": 12},
        },
    )
    _ = fig.update_xaxes(
        color=_CHART_TEXT_COLOR,
        tickfont={"color": _CHART_TEXT_COLOR},
        title_font={"color": _CHART_TEXT_COLOR},
        linecolor="#6b7280",
        gridcolor="#d1d5db",
        zerolinecolor="#9ca3af",
    )
    _ = fig.update_yaxes(
        color=_CHART_TEXT_COLOR,
        tickfont={"color": _CHART_TEXT_COLOR},
        title_font={"color": _CHART_TEXT_COLOR},
        linecolor="#6b7280",
        gridcolor="#d1d5db",
        zerolinecolor="#9ca3af",
    )
    return fig


def add_hover_crosshair(fig: go.Figure) -> go.Figure:
    """Show a synchronized vertical marker across shared-axis chart panels.

    Returns:
        The chart with the hover crosshair configured.

    """
    # Plotly expands hover across subplots only when traces use the same
    # axis ID; matched ranges alone do not synchronize their cursors.
    layout = json_object(fig.layout.to_json())
    for name, value in layout.items():
        if not name.startswith("xaxis"):
            continue
        matches = object_mapping(value).get("matches")
        if isinstance(matches, str):
            _ = fig.update_traces(
                xaxis=matches, selector={"xaxis": name.replace("axis", "")}
            )
    _ = fig.update_layout(
        hovermode="x unified",
        hoversubplots="axis",
    )
    _ = fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikecolor="#5f6368",
    )
    return fig


def _add_trade_markers(
    fig: go.Figure,
    trades: list[Trade],
    selected_timezone: tzinfo,
) -> None:
    """Add entry and exit markers for visible trades."""
    styles = {
        "Long": ("Long entries", "triangle-up", "#0f9d58"),
        "Short": ("Short entries", "triangle-down", "#d93025"),
    }
    for side, (name, symbol, color) in styles.items():
        matching = [trade for trade in trades if trade.side == side]
        if matching:
            _ = fig.add_trace(
                go.Scatter(
                    x=[
                        chart_timestamp(trade.entry_time, selected_timezone)
                        for trade in matching
                    ],
                    y=[trade.entry_price for trade in matching],
                    name=name,
                    mode="markers",
                    marker={"symbol": symbol, "size": 11, "color": color},
                )
            )
    if trades:
        _ = fig.add_trace(
            go.Scatter(
                x=[
                    chart_timestamp(trade.exit_time, selected_timezone)
                    for trade in trades
                ],
                y=[trade.exit_price for trade in trades],
                name="Exits",
                mode="markers",
                marker={"symbol": "x", "size": 10, "color": "#5f6368"},
            )
        )


def _add_options_gex_panels(
    fig: go.Figure,
    data: pd.DataFrame,
    *,
    selected_timezone: tzinfo,
    observed_history: RecordedCharts | None = None,
) -> None:
    """Add GEX and overlay option levels on the candle price axis."""
    if "options_gex_time" not in data:
        return
    if observed_history is not None:
        if observed_history.gex.empty:
            return
        history = observed_history.gex
    else:
        receipts = data["options_gex_time"]
        previous = receipts.shift()
        unchanged = receipts.eq(previous) | (receipts.isna() & previous.isna())
        history = data.loc[~unchanged]
    history_times = chart_times(history["time"], selected_timezone)
    line_shape = "linear" if observed_history is not None else "hv"
    gex_series = (
        ("options_gex", "Net GEX", "#6d28d9"),
        ("options_call_gex", "Call GEX", "#15803d"),
        ("options_put_gex", "Put GEX", "#be123c"),
        ("options_absolute_gex", "Absolute GEX", "#7e22ce"),
    )
    for column, name, color in gex_series:
        if column not in history:
            continue
        _ = fig.add_trace(
            go.Scatter(
                x=history_times,
                y=history[column],
                name=name,
                visible=(
                    "legendonly"
                    if observed_history is not None and column != "options_gex"
                    else True
                ),
                mode=(
                    "lines" if observed_history is not None else "lines+markers"
                ),
                line={"color": color, "width": 1.5, "shape": line_shape},
                connectgaps=False,
                yaxis="y4",
            )
        )
    level_series = (
        ("options_gamma_flip", "Gamma flip", "#1d4ed8"),
        ("options_call_1", "Call 1", "#15803d"),
        ("options_call_2", "Call 2", "#15803d"),
        ("options_call_wall", "Call wall", "#15803d"),
        ("options_put_1", "Put 1", "#be123c"),
        ("options_put_2", "Put 2", "#be123c"),
        ("options_put_wall", "Put wall", "#be123c"),
        ("options_max_pain", "Max pain", "#a16207"),
    )
    for column, name, color in level_series:
        if column.endswith("_wall") and "options_call_1" in history:
            continue
        if column not in history:
            continue
        _ = fig.add_trace(
            go.Scatter(
                x=history_times,
                y=history[column],
                name=name,
                mode=(
                    "lines" if observed_history is not None else "lines+markers"
                ),
                line={
                    "color": color,
                    "width": 1.5,
                    "shape": line_shape,
                    "dash": "dot" if column.endswith("_2") else "solid",
                },
                connectgaps=False,
                yaxis="y",
            )
        )


@dataclass(frozen=True, kw_only=True)
class ChartDisplay:
    """Select the tunnel chart period, local clock and market labels."""

    strategy_start_at: pd.Timestamp
    strategy_end_at: pd.Timestamp
    selected_timezone: tzinfo
    timezone_label: str
    symbol: str = "BTC_USDT"
    quote_currency: str = "USDT"


def build_chart(
    df: pd.DataFrame,
    equity: pd.DataFrame,
    trades: list[Trade],
    *,
    display: ChartDisplay,
    options_history: RecordedCharts | None = None,
) -> go.Figure:
    """Build the local tunnel price, trade, GEX, volume and equity chart.

    Returns:
        The configured Plotly chart.

    """
    fig = go.Figure()
    show_oscillators = options_history is not None and bool(
        options_history.oscillators
    )
    visible_trades = [
        trade
        for trade in trades
        if display.strategy_start_at
        <= trade.entry_time
        <= display.strategy_end_at
        and display.strategy_start_at
        <= trade.exit_time
        <= display.strategy_end_at
    ]
    price_times = chart_times(df["time"], display.selected_timezone)
    equity_times = chart_times(equity["time"], display.selected_timezone)
    visible_low = float(df["low"].astype(float).min())
    visible_high = float(df["high"].astype(float).max())
    levels = (
        (options_history.gex if options_history is not None else df)
        .filter(
            items=[
                "options_gamma_flip",
                "options_call_1",
                "options_call_2",
                "options_put_1",
                "options_put_2",
                "options_call_wall",
                "options_put_wall",
                "options_max_pain",
            ]
        )
        .melt()["value"]
        .dropna()
        .astype(float)
    )
    if not levels.empty:
        visible_low = min(visible_low, float(levels.min()))
        visible_high = max(visible_high, float(levels.max()))
    price_padding = max(
        (visible_high - visible_low) * 0.05, visible_high * 0.01
    )
    equity_low = float(equity["equity"].astype(float).min())
    equity_high = float(equity["equity"].astype(float).max())
    equity_padding = max((equity_high - equity_low) * 0.05, equity_high * 0.01)
    _ = fig.add_trace(
        go.Candlestick(
            x=price_times,
            open=df["open"],
            high=df["high"].astype(float),
            low=df["low"].astype(float),
            close=df["close"],
            name=display.symbol,
            increasing_line_color="#0f9d58",
            decreasing_line_color="#d93025",
        )
    )
    _add_trade_markers(fig, visible_trades, display.selected_timezone)
    _ = fig.add_trace(
        go.Scatter(
            x=equity_times,
            y=equity["equity"].astype(float),
            name="Equity",
            yaxis="y2",
            line={"color": "#5f6368", "width": 1.5},
        )
    )
    _ = fig.add_trace(
        go.Bar(
            x=price_times,
            y=df["volume"],
            name="Volume",
            yaxis="y3",
            marker={
                "color": [
                    "#00c853" if rising else "#ff1744"
                    for rising in (df["close"] >= df["open"]).to_list()
                ],
                "line": {"width": 0},
            },
            hovertemplate="%{x}<br>Volume: %{y:,.2f}<extra></extra>",
        )
    )
    _add_options_gex_panels(
        fig,
        df,
        selected_timezone=display.selected_timezone,
        observed_history=options_history,
    )
    if options_history is not None and show_oscillators:
        add_observed_oscillators(
            fig, options_history, timezone=display.selected_timezone
        )
    strategy_start_chart = chart_timestamp(
        display.strategy_start_at, display.selected_timezone
    )
    strategy_end_chart = chart_timestamp(
        display.strategy_end_at, display.selected_timezone
    )
    _ = fig.add_vline(
        x=strategy_start_chart.timestamp() * 1000,
        line={"color": "#188038", "width": 1, "dash": "dash"},
        annotation_text="Strategy start",
        annotation_position="top left",
    )
    _ = fig.add_vline(
        x=strategy_end_chart.timestamp() * 1000,
        line={"color": "#d93025", "width": 1, "dash": "dash"},
        annotation_text="Strategy stop",
        annotation_position="top right",
    )
    _ = fig.update_layout(
        title={"text": f"{display.symbol} · {'GEX'}"},
        height=1750 if show_oscillators else 980,
        bargap=0.15,
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        xaxis={
            "title": display.timezone_label,
            "rangeslider": {"visible": False},
        },
        yaxis={
            "title": f"{display.symbol} price",
            "tickformat": ",.2f",
            "domain": [0.56, 1.0] if show_oscillators else [0.3, 1.0],
            "range": [
                visible_low - price_padding,
                visible_high + price_padding,
            ],
            "ticksuffix": f" {display.quote_currency}",
            "separatethousands": True,
        },
        yaxis2={
            "title": f"Equity ({display.quote_currency})",
            "range": [
                equity_low - equity_padding,
                equity_high + equity_padding,
            ],
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
            "ticksuffix": f" {display.quote_currency}",
            "separatethousands": True,
        },
        yaxis3={
            "title": "Volume",
            "domain": [0.0, 0.04] if show_oscillators else [0.0, 0.1],
            "rangemode": "tozero",
            "side": "right",
            "showgrid": False,
            "tickformat": "~s",
        },
        yaxis4={
            "title": "GEX (USD / 1%)",
            "domain": [0.39, 0.52] if show_oscillators else [0.12, 0.27],
            "showgrid": True,
            "zeroline": True,
            "zerolinecolor": "#9ca3af",
        },
        yaxis6={
            "title": "Book · 5m (%)",
            "domain": [0.29, 0.37],
            "range": [0, 100],
        },
        yaxis7={
            "title": "Margin · hourly (%)",
            "domain": [0.2, 0.27],
            "range": [0, 100],
        },
        yaxis8={"title": "OI momentum %", "domain": [0.12, 0.18]},
        yaxis9={
            "title": "OI divergence / convergence",
            "domain": [0.06, 0.1],
            "range": [-0.1, 1.1],
            "tickvals": [0, 1],
        },
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
    )
    add_tunnel_confirmations(fig, df, timezone=display.selected_timezone)
    fig = _apply_chart_theme(fig)
    if options_history is not None:
        fig = style_observed_chart(fig)
    return add_hover_crosshair(fig)
