# Copyright 2026 anchored-vwam-backtest contributors
"""Provide ui controls behavior."""

from __future__ import annotations

from datetime import time, timedelta
from decimal import ROUND_HALF_UP, Decimal

import streamlit as st
from shared.gex import OPTIONS_GEX_MODE
from shared.gex_rules import GexHypothesis
from shared.time_utils import chart_timezone

from gui_calculator.child_assets import render_child_controls
from gui_calculator.data_sources import BYBIT_TICKERS, INTERVALS, MEXC_TICKERS
from gui_calculator.local_archive_view import render_local_archive
from gui_calculator.settings import CalculatorSettings
from gui_calculator.tunnel_controls import (
    render_tunnel_controls,
)
from gui_calculator.vwam import MICROPRICE, SAME_SIDE

WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
MIN_ORDER_SIZE = Decimal("0.01")


def ticker_options(data_source: str) -> list[str]:
    """Handle ticker options.

    Returns:
        The resulting value.

    """
    if data_source == "MEXC REST":
        return list(MEXC_TICKERS)
    if data_source == "Bybit REST":
        return list(BYBIT_TICKERS)
    return ["BTC_USDT"]


def normalize_order_size(value: float) -> float:
    """Validate a quote-currency order size and normalize its input to cents.

    Returns:
        The computed result.

    Raises:
        ValueError: If the operation cannot be completed.

    """
    amount = Decimal(str(value)).quantize(
        MIN_ORDER_SIZE, rounding=ROUND_HALF_UP
    )
    if amount < MIN_ORDER_SIZE:
        msg = "Order size must be at least 0.01."
        raise ValueError(msg)
    return float(amount)


def render_sidebar() -> CalculatorSettings:
    """Render only the archived Snapshot tunnel backtester.

    Returns:
        Current market, tunnel, risk and replay settings.

    """
    settings = CalculatorSettings(
        strategy_mode=OPTIONS_GEX_MODE, gex_hypothesis=GexHypothesis.TUNNEL
    )
    with st.sidebar:
        settings.local_archive = render_local_archive()
        if settings.local_archive is None:
            _ = st.info(
                "Enable local GEX archive loading to run Snapshot tunnel."
            )
            st.stop()
        _ = st.selectbox("Strategy", ["Snapshot tunnel"], disabled=True)
        render_market_controls(settings)
        render_strategy_controls(settings)
        render_risk_controls(settings)
        render_schedule_controls(settings)
    return settings


def render_market_controls(settings: CalculatorSettings) -> None:
    """Select candles and the archived history window.

    Raises:
        ValueError: If no local archive is selected.

    """
    local_archive = settings.local_archive
    archive_key = (
        f"archive_{local_archive.path}_{local_archive.modified_ns}_{local_archive.size}"
        if local_archive is not None
        else "manual"
    )
    if local_archive is None:
        msg = "Select a local GEX archive."
        raise ValueError(msg)
    tunnel_dates = (local_archive.start.date(), local_archive.end.date())
    default_start = tunnel_dates[0]
    today = tunnel_dates[1]
    with st.sidebar:
        _ = st.header("Data and time controls")
        settings.data_source = st.selectbox(
            "Source", ["Bybit REST"], disabled=True
        )
        settings.ticker = st.selectbox("Ticker", ["BTC_USDT"], disabled=True)
        settings.reverse_ticker = st.toggle(
            "Reverse ticker",
            value=False,
            disabled=settings.local_archive is not None,
            key=f"{archive_key}_reverse",
            help="Snapshot tunnel uses non-reversed BTC_USDT prices.",
        )
        settings.base_currency, settings.quote_currency = settings.ticker.split(
            "_", maxsplit=1
        )
        if settings.reverse_ticker:
            settings.base_currency, settings.quote_currency = (
                settings.quote_currency,
                settings.base_currency,
            )
        interval_options = list(INTERVALS.keys())
        settings.interval = st.selectbox(
            "Interval", interval_options, index=interval_options.index("5m")
        )
        chart_timezone_selection = st.selectbox(
            "Graph time zone",
            ["Local time", "Eastern Time (New York)", "UTC"],
            index=2,
            key=f"{archive_key}_timezone",
            disabled=settings.local_archive is not None,
        )
        settings.selected_timezone, settings.timezone_label = chart_timezone(
            chart_timezone_selection
        )
        _ = st.caption(
            f"All date and hour inputs use {settings.timezone_label}."
        )
        settings.vwam_file = None
        settings.vwam_method = MICROPRICE
        settings.show_vwam_chart = st.toggle("Show bid/ask VWAM", value=False)
        if settings.show_vwam_chart:
            settings.vwam_method = st.selectbox(
                "VWAM formula", [MICROPRICE, SAME_SIDE]
            )
            _ = st.caption(
                "Microprice weights ask by bid size and bid by ask size."
                " Same-side weights each price by its own size."
            )
            settings.vwam_file = st.file_uploader(
                "Best quotes CSV for the selected ticker",
                type=["csv"],
                key="vwam_quotes",
            )
            _ = st.caption(
                "Columns: time, bid, ask, bid_size, ask_size. Use recorded best"
                " quotes; candle data cannot supply these values."
            )
        start_date_column, start_hour_column = st.columns([2, 1])
        with start_date_column:
            settings.start_day = st.date_input(
                "History start",
                default_start,
                min_value=tunnel_dates[0] if tunnel_dates else None,
                max_value=tunnel_dates[1] if tunnel_dates else None,
                key=f"{archive_key}_history_start",
            )
        with start_hour_column:
            settings.start_hour = st.number_input(
                "Start hour",
                min_value=0,
                max_value=23,
                value=(
                    settings.local_archive.start.hour
                    if settings.local_archive is not None
                    else 0
                ),
                step=1,
                key=f"{archive_key}_start_hour",
            )
        end_date_column, end_hour_column = st.columns([2, 1])
        with end_date_column:
            settings.end_day = st.date_input(
                "History end",
                today,
                min_value=tunnel_dates[0] if tunnel_dates else None,
                max_value=tunnel_dates[1] if tunnel_dates else None,
                key=f"{archive_key}_history_end",
            )
        with end_hour_column:
            settings.end_hour = st.number_input(
                "End hour",
                min_value=0,
                max_value=23,
                value=(
                    settings.local_archive.end.hour
                    if settings.local_archive is not None
                    else 23
                ),
                step=1,
                key=f"{archive_key}_end_hour",
            )


def render_strategy_controls(settings: CalculatorSettings) -> None:
    """Configure Snapshot tunnel confirmations and child assets."""
    _ = st.header("Strategy and trading controls")
    settings.simulate_trades = st.toggle("Simulate trades", value=True)
    settings.child_assets = render_child_controls(
        enabled=settings.simulate_trades
    )
    _ = st.selectbox(
        "GEX entry hypothesis", [GexHypothesis.TUNNEL.value], disabled=True
    )
    settings.tunnel = render_tunnel_controls()
    _ = st.info(
        "Candle prices come from the selected source. GEX and independent"
        " oscillator receipts come from the selected archive. Missing or stale"
        " confirmations block entries; protective stops remain active."
    )


def render_risk_controls(settings: CalculatorSettings) -> None:
    """Configure capital, costs and protective exits."""
    settings.initial_capital = normalize_order_size(
        st.number_input(
            f"Initial capital, {settings.quote_currency}",
            min_value=0.01,
            value=10000.0,
            step=0.01,
            format="%.2f",
            help=(
                "Starting deposit for the calculator. Fees, equity, profit, and"
                " P&L retain sub-cent precision."
            ),
        )
    )
    settings.minimum_order_size = normalize_order_size(
        st.number_input(
            f"Minimum order size, {settings.quote_currency}",
            min_value=0.01,
            value=5.0,
            step=0.01,
            format="%.2f",
            help=(
                "Enter the exchange minimum for this market, for example 5.00"
                " for Bybit BTC/USDT or 0.10 for MEXC SHIB/USDT."
            ),
        )
    )
    settings.fee_pct = st.number_input(
        "Backtest fee per side, %",
        min_value=0.0,
        value=0.3,
        step=0.01,
        format="%.3f",
        help=(
            "Used only by the historical calculator. The separate CLI bot reads"
            " its live account fee from Bybit."
        ),
    )
    settings.funding_rate_pct = st.number_input(
        "Perpetual funding rate per 8 hours, %",
        value=0.0,
        step=0.001,
        format="%.5f",
        help=(
            "Optional fixed funding rate at 00:00, 08:00 and 16:00 UTC. "
            "Positive rates charge longs and credit shorts; negative rates "
            "do the reverse. Zero disables funding. Uses candle open as an "
            "approximation of the settlement mark price."
        ),
    )
    settings.use_leverage = st.toggle(
        "Use leverage",
        value=False,
        disabled=settings.strategy_mode == OPTIONS_GEX_MODE,
    )
    settings.leverage = 1
    settings.slippage_bps = st.number_input(
        "GEX execution slippage, basis points",
        min_value=0.0,
        max_value=1000.0,
        value=2.0,
        step=0.5,
    )
    settings.stop_loss_pct = st.number_input(
        "Stop loss, %", min_value=0.0, value=2.0, step=0.001, format="%.3f"
    )
    settings.take_profit_pct = st.number_input(
        "Take profit, %",
        min_value=0.0,
        value=5.0,
        step=0.5,
        help=(
            "Close a position when this gain from its actual fill is reached."
            " Zero disables it; the first reached TP rule wins."
        ),
    )
    settings.allow_reentry = st.toggle("Allow immediate re-entry", value=True)


def render_schedule_controls(settings: CalculatorSettings) -> None:
    """Restrict trading to selected dates and sessions."""
    settings.use_weekday_schedule = st.toggle(
        "Trade only on selected weekdays", value=False
    )
    settings.selected_weekday_names = WEEKDAYS
    if settings.use_weekday_schedule:
        settings.selected_weekday_names = st.multiselect(
            "Active weekdays",
            WEEKDAYS,
            default=["Tuesday", "Wednesday", "Thursday"],
        )
        start, end = st.columns(2)
        with start:
            settings.active_session_start = st.time_input(
                "Daily trade start",
                value=time(hour=14),
                step=timedelta(minutes=15),
            )
        with end:
            settings.active_session_end = st.time_input(
                "Daily trade end",
                value=time(hour=22),
                step=timedelta(minutes=15),
                help=(
                    "An end earlier than the start continues into the next day."
                ),
            )
    settings.use_full_history_range = st.toggle(
        "Trade full history range", value=True
    )
    render_strategy_dates(settings)


def render_strategy_dates(settings: CalculatorSettings) -> None:
    """Select a trading period within the loaded candle window."""
    start_day, start_hour = st.columns([2, 1])
    with start_day:
        settings.strategy_start_day = st.date_input(
            "Strategy start",
            settings.start_day,
            disabled=settings.use_full_history_range,
        )
    with start_hour:
        settings.strategy_start_hour = st.number_input(
            "Strategy start hour",
            min_value=0,
            max_value=23,
            value=int(settings.start_hour),
            step=1,
            disabled=settings.use_full_history_range,
        )
    end_day, end_hour = st.columns([2, 1])
    with end_day:
        settings.strategy_end_day = st.date_input(
            "Strategy end",
            settings.end_day,
            disabled=settings.use_full_history_range,
        )
    with end_hour:
        settings.strategy_end_hour = st.number_input(
            "Strategy end hour",
            min_value=0,
            max_value=23,
            value=int(settings.end_hour),
            step=1,
            disabled=settings.use_full_history_range,
        )
