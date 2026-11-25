# Copyright 2026 anchored-vwam-backtest contributors
"""Configure snapshot tunnel replay and inspect its saved-date limits."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import streamlit as st
from shared.option_levels import OptionLevelRange
from shared.tunnel import OiConfirmationMode, TunnelSettings, TunnelState

from gui_calculator.snapshot_retest import retest_settings

if TYPE_CHECKING:
    from gui_calculator.settings import CalculatorSettings


def render_tunnel_controls(settings: CalculatorSettings) -> TunnelSettings:
    """Expose scenario thresholds, independent switches and quorum.

    Returns:
        Validated configuration with optional recorded CSV contents.

    """
    use_gex = st.toggle("Confirm with GEX state", value=True)
    state = st.selectbox(
        "Tunnel state",
        ("Automatic", "State 1: long", "State 2: short", "State 3: both"),
        help="Option-level structure applies only to positive GEX entries.",
    )
    level_range = _level_range_controls()
    tight = st.number_input(
        "Tight tunnel maximum width, %",
        min_value=0.01,
        max_value=99.0,
        value=0.5,
    )
    proximity = st.number_input(
        "Tunnel border proximity, %", min_value=0.01, max_value=99.0, value=0.1
    )
    cap_target = st.toggle(
        "Cap negative-GEX long TP below gamma flip", value=True
    )
    target_offset = st.number_input(
        "Negative-GEX long TP below gamma flip, %",
        disabled=not cap_target,
        min_value=0.01,
        max_value=99.0,
        value=0.1,
    )
    _ = st.caption(
        "Positive GEX: state 1 allows longs near the lower option level in a"
        " tight tunnel; state 2 allows shorts near the upper level when lower"
        " <= flip; state 3 allows both. Price must be above flip and near the"
        " eligible level, with oscillator confirmation. The state override"
        " applies only to positive GEX."
    )
    _ = st.caption(
        "Negative GEX: direction comes only from the oscillator quorum. No"
        " option-level structure, wall breakout, proximity or state 1-3 filter"
        " applies. Enabled OI must confirm convergence. Positive GEX uses OI"
        " divergence. Zero or unavailable GEX blocks GEX-confirmed entries."
    )
    _ = st.caption(
        "Entries use available oscillator evidence at the opening quote."
        " Negative-GEX long TP is the"
        " lower of the percentage TP and flip minus the configured offset when"
        " the ceiling toggle is on; otherwise it uses the percentage TP."
        " If gamma flip is unavailable, negative-GEX longs remain eligible"
        " and use the ordinary percentage TP."
        " Entries without profitable room after costs are skipped. Insurance"
        " orders are disabled; the available capital funds one position."
    )
    return _oscillator_controls(
        settings,
        base=TunnelSettings(
            level_range=level_range,
            tight_width=tight / 100,
            proximity=proximity / 100,
            negative_long_tp_offset=target_offset / 100,
            cap_negative_long_tp=cap_target,
            state_override=(
                None if state == "Automatic" else TunnelState(int(state[6]))
            ),
            use_gex=use_gex,
        ),
    )


def _oscillator_controls(
    settings: CalculatorSettings,
    *,
    base: TunnelSettings,
) -> TunnelSettings:
    """Collect independent oscillator evidence and explicitly document formulas.

    Returns:
        Strategy settings and the selected historical input files.

    """
    book = st.toggle("Confirm with limit-order oscillator", value=True)
    margin = st.toggle("Confirm with margin-loan oscillator", value=False)
    oi = st.toggle("Confirm with OI oscillator", value=False)
    retest = st.toggle(
        "Confirm with Retest oscillator",
        help="Replay votes use the selected Retest confirmation mode.",
    )
    show_retest = st.toggle(
        "Show Retest oscillator",
        key="strategy_retest",
        help="Chart only. Uses completed BTCUSDT spot 1-hour candles.",
    )
    settings.retest = retest_settings() if retest or show_retest else None
    oi_mode = st.selectbox(
        "OI confirmation regime",
        tuple(OiConfirmationMode),
        format_func=str.capitalize,
        disabled=not oi or base.use_gex,
    )
    _ = st.caption(
        "With GEX enabled, OI mode is automatic: positive GEX requires"
        " divergence; negative GEX requires convergence. Enabled OI must agree"
        " with the entry even when other oscillators meet the quorum. With GEX"
        " off, use"
        " the regime selector. OI divergence reverses a price swing when"
        " OI momentum disagrees."
        " Convergence follows a new price high/low when raw OI makes a"
        " higher high/lower low. Divergence and convergence require confirmed"
        " pivots. Momentum uses smoothed 12-hour OI growth above the minimum"
        " for either breakout direction, without waiting for pivots."
    )
    _ = st.caption(
        "Each enabled confirmation marks its fresh long/short signals on"
        " the price timeline, including when tunnel rules block trading."
        " Markers show evidence at candle openings, not executed trades."
    )
    momentum_minimum = st.number_input(
        "Minimum OI momentum (12-hour growth %)",
        min_value=0.01,
        value=1.0,
        disabled=not oi
        or base.use_gex
        or oi_mode != OiConfirmationMode.MOMENTUM,
        help="Smoothed over three samples. Confirms either breakout direction.",
    )
    enabled = sum((book, margin, oi, retest))
    votes = st.selectbox(
        "Required agreeing oscillators",
        list(range(1, enabled + 1)) or [0],
    )
    long = st.number_input(
        "Oscillator long minimum (0-100)",
        min_value=51.0,
        max_value=100.0,
        value=60.0,
    )
    short = st.number_input(
        "Oscillator short maximum (0-100)",
        min_value=0.0,
        max_value=49.0,
        value=40.0,
    )
    age = st.number_input(
        "Maximum oscillator age, minutes", min_value=1, value=10
    )
    _ = st.caption(
        f"Book, margin and OI use stored receipts. Active sources: {enabled}."
        " Retest checks sampled quotes against completed 1-hour candles. OI"
        " uses five-minute samples; gaps reset its 12-hour warmup."
    )
    if enabled == 0:
        _ = st.warning("Enable at least one oscillator to authorize trades.")
    return replace(
        base,
        use_book=book,
        use_margin=margin,
        use_oi=oi,
        use_retest=retest,
        oi_mode=oi_mode,
        oi_momentum_minimum=momentum_minimum,
        votes=votes,
        long_threshold=long,
        short_threshold=short,
        maximum_age=timedelta(minutes=age),
    )


def _level_range_controls() -> OptionLevelRange:
    """Collect the optional symmetric option-level distance from spot.

    Returns:
        A validated range retaining its percentage while disabled.

    """
    enabled = st.toggle("Limit option levels to price range", value=True)
    percent = st.number_input(
        "Option level range from current price, %",
        min_value=0.01,
        max_value=99.99,
        value=20.0,
        disabled=not enabled,
        help="Only strikes within this percentage above or below spot qualify.",
    )
    return OptionLevelRange(enabled=enabled, distance=percent / 100)
