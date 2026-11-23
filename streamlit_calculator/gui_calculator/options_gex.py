# Copyright 2026 anchored-vwam-backtest contributors
"""Options terminal with explicit snapshot provenance and assumptions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
from shared.option_levels import DEFAULT_LEVEL_RANGE, OptionLevelRange
from snapshot_tunnel.gamma_search import search_flips
from snapshot_tunnel.options_model import (
    CandleClose,
    Snapshot,
    max_pain,
    parse_snapshots,
    ranked_walls,
    update_gex_once_per_candle,
)

from gui_calculator.expiry_view import render_expiry_impact
from gui_calculator.observed_chart import (
    add_observed_oscillators,
    style_observed_chart,
)
from gui_calculator.options_candles import render_candle_source
from gui_calculator.options_profile_chart import (
    exposure_chart as exposure_chart,
)
from gui_calculator.options_profile_chart import (
    style_options_chart,
    wall_levels_chart,
)
from gui_calculator.previous_day_view import (
    render_previous_day_comparison,
)
from gui_calculator.rust_backend import strike_exposures
from gui_calculator.snapshot_balance_view import (
    snapshot_balance,
    snapshot_balance_chart,
)
from gui_calculator.snapshot_dashboard import render_snapshot_dashboard
from gui_calculator.snapshot_request_view import render_snapshot_request

if TYPE_CHECKING:
    from gui_calculator.observed_history import RecordedCharts
    from gui_calculator.view_types import IndicatorUI

DEFAULT_OPTIONS_CSV = Path(__file__).with_name("options_snapshot.csv")
EXAMPLE = DEFAULT_OPTIONS_CSV.read_text(encoding="utf-8")


@dataclass(frozen=True, kw_only=True)
class OptionsDisplay:
    """Keep profile range and history visibility together for analytics."""

    level_range: OptionLevelRange = field(default_factory=OptionLevelRange)
    show_history_chart: bool = True


DEFAULT_OPTIONS_DISPLAY = OptionsDisplay()


def _render_levels(
    snapshot: Snapshot,
    flips: tuple[float, ...],
    *,
    level_range: OptionLevelRange = DEFAULT_LEVEL_RANGE,
) -> None:
    """Render scope-consistent metrics and ranked strike levels."""
    levels = strike_exposures(snapshot)
    ranked = ranked_walls(levels, spot=snapshot.spot, level_range=level_range)
    pain = max_pain(snapshot)
    nearest_flip = (
        min(flips, key=lambda value: abs(value - snapshot.spot))
        if flips
        else None
    )
    metrics = st.columns(3)
    _ = metrics[0].metric(
        "Gamma flip (nearest spot)",
        (
            f"${nearest_flip:,.2f}"
            if nearest_flip is not None
            else "No crossing in search range"
        ),
    )
    if nearest_flip is not None and snapshot.spot < nearest_flip:
        _ = metrics[0].warning(
            f"Snapshot price ${snapshot.spot:,.2f} is below gamma flip "
            f"${nearest_flip:,.2f}."
        )
    _ = metrics[1].metric(
        "Model GEX (call+/put-) · USD / 1%",
        f"{sum(level.net for level in levels):+,.0f}",
    )
    _ = metrics[2].metric(
        "Absolute GEX · USD / 1%",
        f"{sum(level.absolute for level in levels):,.0f}",
    )
    walls = st.columns(3)
    _ = walls[0].metric(
        "Max pain", f"${pain:,.2f}" if pain is not None else "Unavailable"
    )
    for column, side, levels_for_side in (
        (walls[1], "Call", ranked.calls),
        (walls[2], "Put", ranked.puts),
    ):
        for index in range(2):
            _ = column.metric(
                f"{side} {index + 1} · ranked GEX strike",
                (
                    f"${levels_for_side[index].strike:,.2f}"
                    if index < len(levels_for_side)
                    else "Unavailable"
                ),
            )
    range_description = (
        f" Only strikes within ±{level_range.distance:.2%} of the current price"
        " qualify."
        if level_range.enabled
        else " The option level price-range limit is disabled."
    )
    _ = st.caption(
        "Max pain requires one expiry with positive OI. Call 1/2 and Put 1/2"
        " are ranked independently by side GEX magnitude, for either net GEX"
        " sign."
        + range_description
        + " GEX ties choose the lower strike. Missing ranks remain"
        " unavailable. These levels are not guaranteed support/resistance."
    )
    with st.expander("Strike exposure details"):
        _ = st.dataframe(
            [
                {
                    "Strike (USD)": level.strike,
                    "Call GEX": level.call,
                    "Put GEX": level.put,
                    "Net GEX": level.net,
                    "Absolute GEX": level.absolute,
                }
                for level in levels
            ],
            hide_index=True,
        )


def _render_extremum_distances(
    snapshot: Snapshot, *, level_range: OptionLevelRange = DEFAULT_LEVEL_RANGE
) -> None:
    """Show each shared ranked strike's signed distance from snapshot spot."""
    distances = snapshot_balance(
        snapshot, level_range=level_range
    ).extremum_distances
    if not distances:
        return
    _ = st.caption("Extremum distance from snapshot spot")
    for column, level in zip(
        st.columns(len(distances)), distances, strict=True
    ):
        distance = level.strike - snapshot.spot
        _ = column.metric(
            f"Extremum ${level.strike:,.2f} · distance from spot",
            f"{level.percent:+.2f}%",
            delta=f"${distance:+,.2f}",
            delta_color="off",
        )


def _render_expiries(snapshot: Snapshot, chart_ui: IndicatorUI) -> None:
    """Show opposing expiry exposures that a single net number can conceal."""
    totals: list[dict[str, str | int | float]] = []
    for expiry in sorted({option.expiry for option in snapshot.options}):
        selected = replace(
            snapshot,
            options=tuple(
                option for option in snapshot.options if option.expiry == expiry
            ),
        )
        levels = strike_exposures(selected)
        totals.append({
            "Expiry": expiry.isoformat(),
            "Contracts": len(selected.options),
            "Model GEX (call+/put-)": sum(level.net for level in levels),
            "Absolute GEX": sum(level.absolute for level in levels),
        })
    _ = chart_ui.dataframe(
        pd.DataFrame(totals), hide_index=True, use_container_width=True
    )


def _render_profile(
    snapshot: Snapshot,
    chart_ui: IndicatorUI,
    *,
    level_range: OptionLevelRange = DEFAULT_LEVEL_RANGE,
) -> None:
    """Reprice gamma across hypothetical spots and display detected flips."""
    result = search_flips(snapshot)
    flips = result.roots
    _ = st.caption(
        f"Full strike range: USD {result.lower:,.2f} to USD"
        f" {result.upper:,.2f}. {result.status.value}."
    )
    _ = st.html(Path(__file__).with_name("options_terminal.css"))
    with st.container(border=True, key="gex-terminal-chart"):
        _ = st.subheader(f"{snapshot.asset} · GEX terminal")
        _ = st.caption(
            f"{snapshot.timestamp:%d %b %Y · %H:%M UTC} · "
            f"Spot ${snapshot.spot:,.2f} · "
            f"{len(strike_exposures(snapshot))} strikes"
        )
        _ = chart_ui.plotly_chart(
            exposure_chart(snapshot, level_range=level_range),
            use_container_width=True,
        )
    with st.container(key="gex-terminal-levels"):
        _render_levels(snapshot, flips, level_range=level_range)
    _ = chart_ui.plotly_chart(
        wall_levels_chart(
            snapshot, gamma_flip=result.nearest, level_range=level_range
        ),
        use_container_width=True,
    )
    _render_extremum_distances(snapshot, level_range=level_range)
    _ = chart_ui.plotly_chart(
        snapshot_balance_chart(snapshot, level_range=level_range),
        use_container_width=True,
    )
    _ = chart_ui.caption(
        "Calls positive / puts negative is a model convention. "
        "Wall distances are signed price changes from snapshot spot; "
        "missing sides have no distance bar. Balance is net / absolute GEX; "
        "zero exposure has no balance bar. These measurements are not "
        "bid/ask imbalance or probabilities of rising, falling or staying. "
        "A closer wall requires a smaller move, not a directional signal."
    )
    with st.expander("Gamma flip search and expiry breakdown"):
        _ = chart_ui.plotly_chart(
            exposure_chart(
                snapshot, flip_search=result, level_range=level_range
            ),
            use_container_width=True,
        )
        _render_expiries(snapshot, chart_ui)
    _ = st.caption(
        "All detected flips: "
        + (
            ", ".join(f"${value:,.2f}" for value in flips)
            or "none in the selected search range"
        )
    )


def _render_candle_updates(
    snapshot: Snapshot, candles: tuple[CandleClose, ...], chart_ui: IndicatorUI
) -> None:
    """Render GEX updated once for each supplied completed candle."""
    updates = update_gex_once_per_candle(snapshot, candles)
    chart = go.Figure()
    _ = chart.add_trace(
        go.Scatter(
            x=[item.timestamp for item in updates],
            y=[item.signed for item in updates],
            name="Signed GEX",
            line={"color": "#0369a1", "width": 2},
        )
    )
    _ = chart.add_trace(
        go.Scatter(
            x=[item.timestamp for item in updates],
            y=[item.absolute for item in updates],
            name="Absolute GEX",
            line={"color": "#7e22ce", "width": 2},
        )
    )
    _ = chart.update_layout(
        title="GEX updated once per completed candle",
        xaxis_title="Candle close time",
        yaxis_title="USD / 1% move",
    )
    _ = chart_ui.plotly_chart(
        style_options_chart(chart), use_container_width=True
    )
    _ = st.dataframe(
        [
            {
                "Candle time": item.timestamp,
                "Spot": item.spot,
                "Signed GEX": item.signed,
                "Absolute GEX": item.absolute,
            }
            for item in updates
        ],
        hide_index=True,
    )


def render_options_gex() -> None:
    """Calculate analytics after an explicit snapshot request."""
    _ = st.header("Options GEX")
    _ = st.caption("Snapshot analytics · BTC / ETH · no trade execution")
    try:
        snapshot = render_snapshot_request(EXAMPLE)
        if snapshot is None:
            return
        _ = st.caption(
            f"Observation: {snapshot.timestamp.isoformat()} ·"
            f" {len(snapshot.options)} contracts. Calls positive / puts"
            " negative is a model assumption, not observed dealer inventory."
        )
        _render_profile(snapshot, st)
        render_expiry_impact(snapshot, st)
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        sqlite3.Error,
        requests.RequestException,
        OverflowError,
    ) as exc:
        _ = st.error(f"Snapshot analytics unavailable: {exc}")
    else:
        if st.session_state.get("options_data_source") in {
            "Deribit API (latest snapshot)",
            "Saved history / Deribit API",
        }:
            render_snapshot_dashboard(snapshot)
        if st.session_state.get("options_data_source") in {
            "Deribit API (latest snapshot)",
            "Saved history / Deribit API",
        }:
            render_previous_day_comparison(snapshot)


@st.fragment(run_every="1m")
def _render_live_candles(snapshot: Snapshot) -> None:
    """Refresh completed candles independently of options collection."""
    candles = render_candle_source(snapshot)
    if candles:
        try:
            _render_candle_updates(snapshot, candles, st)
        except (ValueError, OverflowError) as exc:
            _ = st.error(f"Invalid candle data: {exc}")


def render_strategy_history(
    chart_ui: IndicatorUI,
    data: pd.DataFrame,
    *,
    observed_history: RecordedCharts | None = None,
) -> None:
    """Plot every calculated interval and expose its numeric values."""
    if "options_gex_time" not in data:
        return
    daily = observed_history is None and "options_decision_at" in data
    history = (
        observed_history.gex.copy()
        if observed_history is not None
        else data.copy()
    )
    if observed_history is None and not daily:
        history = history.dropna(subset=["options_gex_time"]).drop_duplicates(
            "options_gex_time"
        )
    timeline = history[(
        "time"
        if observed_history is not None
        else ("options_decision_at" if daily else "options_gex_time")
    )]
    if daily:
        valid = timeline < pd.to_datetime(
            history["options_valid_until"], utc=True
        )
        columns = [
            "options_gex",
            "options_call_gex",
            "options_put_gex",
            "options_absolute_gex",
            "options_gamma_flip",
            "options_call_wall",
            "options_put_wall",
            "options_call_1",
            "options_call_2",
            "options_put_1",
            "options_put_2",
            "options_monitored_gex",
        ]
        history.loc[~valid, [name for name in columns if name in history]] = (
            float("nan")
        )
        history["options_price"] = history["open"]
    show_oscillators = observed_history is not None and bool(
        observed_history.oscillators
    )
    level_row = 2
    chart = make_subplots(
        rows=6 if show_oscillators else level_row,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
    )
    for column, label, row, color in (
        ("options_gex", "Plan GEX" if daily else "Net GEX", 1, "#6d28d9"),
        ("options_monitored_gex", "Repriced GEX (fixed OI / IV)", 1, "#a16207"),
        ("options_call_gex", "Call GEX", 1, "#15803d"),
        ("options_put_gex", "Put GEX", 1, "#be123c"),
        ("options_absolute_gex", "Absolute GEX", 1, "#7e22ce"),
        (
            "options_price",
            (
                "BTC snapshot spot"
                if observed_history is not None
                else "BTCUSDT price"
            ),
            2,
            "#111827",
        ),
        ("options_gamma_flip", "Gamma flip", level_row, "#1d4ed8"),
        ("options_call_1", "Call 1", level_row, "#15803d"),
        ("options_call_2", "Call 2", level_row, "#15803d"),
        ("options_call_wall", "Call wall", level_row, "#15803d"),
        ("options_put_1", "Put 1", level_row, "#be123c"),
        ("options_put_2", "Put 2", level_row, "#be123c"),
        ("options_put_wall", "Put wall", level_row, "#be123c"),
        ("options_max_pain", "Max pain", level_row, "#a16207"),
    ):
        if column not in history:
            continue
        if column.endswith("_wall") and "options_call_1" in history:
            continue
        _ = chart.add_trace(
            go.Scatter(
                x=timeline,
                y=history[column],
                name=label,
                mode=(
                    "lines" if observed_history is not None else "lines+markers"
                ),
                visible=(
                    "legendonly"
                    if observed_history is not None
                    and column
                    in {
                        "options_call_gex",
                        "options_put_gex",
                        "options_absolute_gex",
                    }
                    else True
                ),
                line={
                    "shape": "linear" if observed_history is not None else "hv",
                    "color": color,
                    "width": 2.5 if column == "options_price" else 1.5,
                    "dash": "dot" if column.endswith("_2") else "solid",
                },
                marker={"size": 3},
                connectgaps=False,
            ),
            row=row,
            col=1,
        )
    if observed_history is not None and show_oscillators:
        add_observed_oscillators(chart, observed_history, subplots=True)
        _ = chart.update_yaxes(
            title_text="Book · 5m (%)", range=[0, 100], row=3, col=1
        )
        _ = chart.update_yaxes(
            title_text="Margin · hourly (%)", range=[0, 100], row=4, col=1
        )
        _ = chart.update_yaxes(title_text="OI momentum %", row=5, col=1)
        _ = chart.update_yaxes(
            title_text="OI divergence",
            range=[-0.1, 1.1],
            tickvals=[0, 1],
            row=6,
            col=1,
        )
    _ = chart.update_layout(
        title=(
            "GEX history · recorded observations"
            if observed_history is not None
            else "GEX history · selected timeframe"
        ),
        height=1450 if show_oscillators else 900,
        hovermode="x unified",
    )
    _ = chart.update_yaxes(title_text="USD / 1% move", row=1, col=1)
    _ = chart.update_yaxes(title_text="Price (USD)", row=2, col=1)
    chart = style_options_chart(chart)
    if observed_history is not None:
        chart = style_observed_chart(chart)
    _ = chart_ui.plotly_chart(chart, use_container_width=True)
    observations = history.dropna(subset=["options_gex_time"])
    if observed_history is not None:
        _ = chart_ui.caption(
            f"{len(observations):,} recorded observations at actual receipt"
            " times. No forward fill or smoothing. Lines connect adjacent"
            " observations; missing five-minute collections break the line."
            " Daily execution plans are listed separately in the strategy"
            " audit."
        )
    _ = chart_ui.dataframe(
        observations[[
            column
            for column in observations
            if isinstance(column, str) and column.startswith("options_")
        ]],
        hide_index=True,
        use_container_width=True,
    )


def render_options_gex_strategy(
    chart_ui: IndicatorUI,
    data: pd.DataFrame,
    *,
    content: str | tuple[Snapshot, ...] = EXAMPLE,
    display: OptionsDisplay = DEFAULT_OPTIONS_DISPLAY,
    observed_history: RecordedCharts | None = None,
) -> None:
    """Render the Options GEX analytics used by the GEX backtest strategy.

    The strategy reprices the latest snapshot available at each candle.  The
    summary panels therefore use the latest BTC snapshot available in the
    supplied backtest data, so the displayed exposure and flip search describe
    the same options chain without importing a future snapshot.

    Raises:
        ValueError: If the options snapshot is malformed or has no BTC data.

    """
    snapshots = (
        parse_snapshots(content) if isinstance(content, str) else content
    )
    btc = tuple(item for item in snapshots if item.asset == "BTC")
    if not btc:
        msg = "Options GEX snapshots must include BTC data."
        raise ValueError(msg)
    candle_times = pd.to_datetime(data["time"], utc=True)
    latest_time = candle_times.max()
    available = tuple(
        snapshot for snapshot in btc if snapshot.timestamp <= latest_time
    )
    if not available:
        _ = chart_ui.info(
            "No BTC options snapshot is available inside the strategy window."
        )
        return
    snapshot = max(available, key=lambda item: item.timestamp)
    _ = chart_ui.caption(
        "Snapshot profile at its observation time (see history for repriced "
        "strategy values): "
        f"{snapshot.timestamp.isoformat()}."
    )
    with st.container(border=True):
        _ = chart_ui.subheader("Options GEX strategy analytics")
        _render_profile(snapshot, chart_ui, level_range=display.level_range)
        if display.show_history_chart:
            if observed_history is not None and observed_history.gex.empty:
                _ = chart_ui.info(
                    "No recorded options observations in this window."
                )
            else:
                render_strategy_history(
                    chart_ui, data, observed_history=observed_history
                )
