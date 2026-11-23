# Copyright 2026 anchored-vwam-backtest contributors
"""Load child prices and display separate copies of executed BTC trades."""

from __future__ import annotations

import csv
import sqlite3
from io import StringIO
from typing import TYPE_CHECKING

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from shared.child_assets import (
    CHILD_SYMBOLS,
    ChildFunding,
    ChildOrder,
    ChildPrice,
    ChildResult,
    ChildSymbol,
    replay_child,
)
from shared.gex import OPTIONS_GEX_MODE
from shared.validation import numeric_string

from gui_calculator.candle_cache import CandleMarket, load_cached_klines
from gui_calculator.data_sources import fetch_bybit_klines

if TYPE_CHECKING:
    from shared.models import Trade
    from shared.spot_execution import Side

    from gui_calculator.settings import CalculatorSettings
    from gui_calculator.view_types import IndicatorUI


def render_child_controls(*, enabled: bool) -> tuple[ChildSymbol, ...]:
    """Select supported children only when GEX trade simulation is enabled.

    Returns:
        The enabled child symbols in display order.

    """
    selected = st.multiselect(
        "Child Assets",
        CHILD_SYMBOLS,
        disabled=not enabled,
        help=(
            "Copy executed BTCUSDT entries and exits. Each child has a separate"
            " account with the configured starting capital. Only BTC evaluates"
            " confirmations, stop loss and take profit."
        ),
    )
    return tuple(selected) if enabled else ()


def father_orders(trades: list[Trade]) -> tuple[ChildOrder, ...]:
    """Convert executed trades into ordered entry and exit actions.

    Returns:
        Mirrored actions preserving same-candle entry/exit order.

    Raises:
        ValueError: If a father trade has an unsupported direction or timeline.

    """
    orders: list[ChildOrder] = []
    for trade in trades:
        side: Side
        if trade.side == "Long":
            side = "Long"
        elif trade.side == "Short":
            side = "Short"
        else:
            msg = f"Unsupported father trade side: {trade.side}"
            raise ValueError(msg)
        if trade.exit_time < trade.entry_time:
            msg = "Father trade closes before its entry."
            raise ValueError(msg)
        orders.extend((
            ChildOrder(time=trade.entry_time, action="open", side=side),
            ChildOrder(
                time=trade.exit_time,
                action="close",
                side=side,
                reason=trade.exit_reason,
            ),
        ))
    return tuple(orders)


def child_prices(frame: pd.DataFrame) -> tuple[ChildPrice, ...]:
    """Validate external time/open/close columns before domain execution.

    Returns:
        Price observations without child indicators, volume, or protection.

    Raises:
        ValueError: If required price columns or UTC timestamps are missing.

    """
    if not {"time", "open", "close"}.issubset(frame.columns):
        msg = "Child price history requires time, open and close columns."
        raise ValueError(msg)
    result: list[ChildPrice] = []
    for row in csv.DictReader(StringIO(frame.to_csv(index=False))):
        timestamp = pd.Timestamp(row["time"])
        if pd.isna(timestamp) or timestamp.tzinfo is None:
            msg = "Child price timestamps must be valid and timezone-aware."
            raise ValueError(msg)
        result.append(
            ChildPrice(
                time=timestamp.tz_convert("UTC"),
                opening=numeric_string(row["open"]),
                close=numeric_string(row["close"]),
            )
        )
    return tuple(result)


def load_child_result(
    symbol: ChildSymbol,
    equity: pd.DataFrame,
    *,
    orders: tuple[ChildOrder, ...],
    settings: CalculatorSettings,
) -> ChildResult:
    """Fetch only price candles and replay executed father actions.

    Returns:
        The child's independent trade and equity history.

    Raises:
        ValueError: If price history has gaps within the father's timeline.

    """
    times = pd.DatetimeIndex(equity["time"])
    candles = load_cached_klines(
        CandleMarket(
            exchange="bybit_linear", symbol=symbol, interval=settings.interval
        ),
        start_ms=int(times.min().timestamp() * 1000),
        end_ms=int(times.max().timestamp() * 1000),
        fetcher=fetch_bybit_klines,
    )
    prices = child_prices(candles)
    available = {price.time for price in prices}
    if not set(times).issubset(available):
        msg = (
            f"{symbol}: missing price candles in the father's simulation range."
        )
        raise ValueError(msg)
    return replay_child(
        tuple(price for price in prices if price.time in times),
        orders,
        funding=ChildFunding(
            capital=settings.initial_capital,
            fee_pct=settings.fee_pct,
            slippage_bps=settings.slippage_bps,
            leverage=settings.leverage,
        ),
    )


def render_child_assets(
    trades: list[Trade], equity: pd.DataFrame, settings: CalculatorSettings
) -> None:
    """Display independently funded children after the BTC simulation."""
    if (
        not settings.child_assets
        or not settings.simulate_trades
        or settings.strategy_mode != OPTIONS_GEX_MODE
    ):
        return
    _ = st.subheader("Child Assets")
    if settings.ticker != "BTC_USDT" or settings.reverse_ticker:
        _ = st.error("Child Assets requires BTCUSDT as the father asset.")
        return
    _ = st.caption(
        "Separate accounts start with the configured initial capital. BTC alone"
        " controls entries and every exit, including TP/SL, reversals and"
        " session end. Child fills use the matching candle OPEN plus configured"
        " slippage; exact intrabar BTC execution times are unavailable."
        " Same-candle round trips use the same opening price. Equity is valued"
        " at candle CLOSE. Fees and selected leverage apply; this price-only"
        " model excludes child funding, liquidation, exchange lot sizes and"
        " minimum notionals."
    )
    if not trades:
        _ = st.info("No executed BTC trades to copy to child assets.")
        return
    try:
        orders = father_orders(trades)
        with st.spinner(
            "Loading DOGE/XRP child prices and copying BTC orders..."
        ):
            results: dict[ChildSymbol, ChildResult] = {
                symbol: load_child_result(
                    symbol, equity, orders=orders, settings=settings
                )
                for symbol in settings.child_assets
            }
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        sqlite3.Error,
        requests.RequestException,
    ) as exc:
        _ = st.error(f"Cannot simulate Child Assets: {exc}")
        return
    _render_child_results(st, results, settings)


def _render_child_results(
    ui: IndicatorUI,
    results: dict[ChildSymbol, ChildResult],
    settings: CalculatorSettings,
) -> None:
    """Show separate account totals, equity and downloadable child trades."""
    summary = pd.DataFrame([
        {
            "Asset": symbol,
            "Starting capital (USDT)": settings.initial_capital,
            "Final equity (USDT)": result.marks[-1].equity,
            "Net P&L (USDT)": (
                result.marks[-1].equity - settings.initial_capital
            ),
            "Trades": len(result.trades),
        }
        for symbol, result in results.items()
    ])
    _ = ui.dataframe(summary, hide_index=True, use_container_width=True)
    chart = go.Figure(
        data=[
            go.Scatter(
                x=[
                    mark.time.tz_convert(settings.selected_timezone)
                    for mark in result.marks
                ],
                y=[mark.equity for mark in result.marks],
                name=symbol,
                mode="lines",
            )
            for symbol, result in results.items()
        ]
    )
    _ = chart.update_layout(
        title="Child account equity",
        yaxis_title="Equity (USDT)",
        xaxis_title=f"Time ({settings.timezone_label})",
    )
    _ = ui.plotly_chart(chart, use_container_width=True)
    records = pd.DataFrame([
        {"asset": symbol, "father_asset": "BTCUSDT", **trade.__dict__}
        for symbol, result in results.items()
        for trade in result.trades
    ])
    for column in ("entry_time", "exit_time"):
        records[column] = pd.to_datetime(
            records[column], utc=True
        ).dt.tz_convert(settings.selected_timezone)
    _ = ui.dataframe(records, hide_index=True, use_container_width=True)
    _ = ui.download_button(
        "Download child trades CSV",
        records.to_csv(index=False),
        file_name="child_asset_trades.csv",
        mime="text/csv",
    )
