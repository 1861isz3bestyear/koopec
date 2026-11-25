# Copyright 2026 anchored-vwam-backtest contributors
"""Detect and plot hourly Bybit spot level retests at snapshot time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import accumulate, pairwise
from typing import TYPE_CHECKING, Literal, cast

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from shared.validation import number, object_list, object_mapping
from snapshot_tunnel.tunnel_flow import BOTH_DIRECTIONS, OscillatorObservation

from gui_calculator.data_sources import fetch_bybit_klines
from gui_calculator.settings import (
    DEFAULT_RETEST_LOOKBACK,
    RetestMode,
    RetestSettings,
)

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot

HOUR = timedelta(hours=1)
RETEST_ROW = 5


@dataclass(frozen=True, kw_only=True)
class SpotQuote:
    """Observable spot price at a sampling candle's opening time."""

    available: datetime
    price: float


@dataclass(frozen=True, kw_only=True)
class HourlyCandle:
    """Spot candle timestamped when its full price range became available."""

    closed_at: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, kw_only=True)
class Retest:
    """A confirmed return to a prior extreme."""

    side: Literal["High", "Low"]
    origin: datetime
    confirmed_at: datetime
    level: float


@dataclass(frozen=True, kw_only=True)
class RetestHistory:
    """Hourly bars and the visible range they warm up."""

    candles: tuple[HourlyCandle, ...]
    start: datetime
    settings: RetestSettings
    quotes: tuple[SpotQuote, ...]


@dataclass(frozen=True, kw_only=True)
class HourlyLevels:
    """Highest wick and lowest wick of one contiguous completed window."""

    peak: HourlyCandle
    trough: HourlyCandle


@dataclass(frozen=True, kw_only=True)
class RetestAssessment:
    """The result of evaluating one fully warmed-up candle."""

    available: datetime
    signals: tuple[Retest, ...]
    calculatable: bool


def _spot_candle(record: object, /) -> HourlyCandle:
    row = object_mapping(record)
    timestamp = row["time"]
    if (
        not isinstance(timestamp, pd.Timestamp)
        or timestamp.tzinfo is None
        or timestamp != timestamp.floor("h")
    ):
        msg = "Bybit returned an invalid candle timestamp."
        raise ValueError(msg)
    opening, high, low, close = (
        number(row[key]) for key in ("open", "high", "low", "close")
    )
    if (
        not all(value > 0 for value in (opening, high, low, close))
        or high < max(opening, close)
        or low > min(opening, close)
    ):
        msg = "Bybit returned an invalid candle price range."
        raise ValueError(msg)
    return HourlyCandle(
        closed_at=timestamp.to_pydatetime() + HOUR,
        open=opening,
        high=high,
        low=low,
        close=close,
    )


def load_retest_candles(
    symbol: str, cutoff: datetime, *, days: int, lookback: int
) -> tuple[HourlyCandle, ...]:
    """Load completed spot candles and sufficient warmup for the visible window.

    Returns:
        Chronological candles bounded by the dashboard cutoff.

    """
    return load_retest_window(
        symbol, cutoff - timedelta(days=days), cutoff, lookback=lookback
    )


@st.cache_data(ttl=60, show_spinner=False)
def load_retest_window(
    symbol: str, start: datetime, cutoff: datetime, *, lookback: int
) -> tuple[HourlyCandle, ...]:
    """Fetch spot bars back far enough to warm up the selected window.

    Returns:
        Consecutive or gapped hourly bars as supplied by Bybit, before cutoff.

    """
    end = cutoff.replace(minute=0, second=0, microsecond=0)
    first_open = (start - datetime.resolution).replace(
        minute=0, second=0, microsecond=0
    )
    start = first_open - lookback * HOUR
    frame = fetch_bybit_klines(
        symbol,
        "1h",
        start_ms=int(start.timestamp() * 1000),
        end_ms=int(end.timestamp() * 1000) - 1,
        category="spot",
    )
    candles = map(
        _spot_candle, object_list(cast("object", frame.to_dict("records")))
    )
    return tuple(
        candle for candle in candles if start < candle.closed_at <= end
    )


def _quote_from_row(record: object, /) -> SpotQuote:
    row = object_mapping(record)
    timestamp = row["time"]
    price = number(row["open"])
    if (
        not isinstance(timestamp, pd.Timestamp)
        or timestamp.tzinfo is None
        or price <= 0
    ):
        msg = "Bybit returned an invalid spot quote."
        raise ValueError(msg)
    return SpotQuote(available=timestamp.to_pydatetime(), price=price)


@st.cache_data(ttl=60, show_spinner=False)
def load_retest_quotes(
    symbol: str,
    start: datetime,
    cutoff: datetime,
    *,
    interval: Literal["1m", "5m"],
) -> tuple[SpotQuote, ...]:
    """Load observable open prices at the requested cadence.

    Returns:
        Spot opening quotes within the requested time bounds.

    """
    frame = fetch_bybit_klines(
        symbol,
        interval,
        start_ms=int(start.timestamp() * 1000),
        end_ms=int(cutoff.timestamp() * 1000),
        category="spot",
    )
    quotes = map(
        _quote_from_row, object_list(cast("object", frame.to_dict("records")))
    )
    return tuple(
        quote for quote in quotes if start <= quote.available <= cutoff
    )


def _hourly_levels(history: RetestHistory) -> dict[datetime, HourlyLevels]:
    candles = history.candles
    if not candles:
        return {}
    length = history.settings.lookback
    runs = accumulate(
        (
            current.closed_at - previous.closed_at == HOUR
            for previous, current in pairwise(candles)
        ),
        lambda size, adjacent: size + 1 if adjacent else 1,
        initial=1,
    )
    levels: dict[datetime, HourlyLevels] = {}
    for index, size in enumerate(runs):
        if size < length:
            continue
        window = candles[index - length + 1 : index + 1]
        levels[candles[index].closed_at] = HourlyLevels(
            peak=max(reversed(window), key=lambda bar: bar.high),
            trough=min(reversed(window), key=lambda bar: bar.low),
        )
    return levels


def _assess_quote(
    quote: SpotQuote, levels: HourlyLevels | None
) -> RetestAssessment:
    signals: list[Retest] = []
    if levels is not None:
        if quote.price >= levels.peak.high:
            signals.append(
                Retest(
                    side="High",
                    origin=levels.peak.closed_at,
                    confirmed_at=quote.available,
                    level=levels.peak.high,
                )
            )
        if quote.price <= levels.trough.low:
            signals.append(
                Retest(
                    side="Low",
                    origin=levels.trough.closed_at,
                    confirmed_at=quote.available,
                    level=levels.trough.low,
                )
            )
    return RetestAssessment(
        available=quote.available,
        signals=tuple(signals),
        calculatable=levels is not None,
    )


def _assess_retests(history: RetestHistory) -> tuple[RetestAssessment, ...]:
    levels = _hourly_levels(history)
    return tuple(
        _assess_quote(
            quote,
            levels.get(
                quote.available.replace(minute=0, second=0, microsecond=0)
            ),
        )
        for quote in history.quotes
    )


def _retest_direction(signals: tuple[Retest, ...], mode: RetestMode) -> int:
    if not signals:
        return 0
    if mode is RetestMode.EITHER:
        return BOTH_DIRECTIONS
    reversal = sum(1 if signal.side == "Low" else -1 for signal in signals)
    return reversal if mode is RetestMode.REVERSAL else -reversal


def retest_votes(
    history: RetestHistory | None,
) -> tuple[OscillatorObservation, ...]:
    """Sample level touches and map them to strategy confirmations.

    Returns:
        One observation per spot quote, usable until the next expected sample.

    """
    if history is None:
        return ()
    interval = timedelta(minutes=1 if history.settings.interval == "1m" else 5)
    return tuple(
        OscillatorObservation(
            available=assessment.available,
            direction=_retest_direction(
                assessment.signals, history.settings.mode
            ),
            calculatable=assessment.calculatable,
            valid_for=interval,
        )
        for assessment in _assess_retests(history)
    )


def strategy_retest_history(
    data: pd.DataFrame, *, settings: RetestSettings | None
) -> RetestHistory | None:
    """Load shared signal and chart inputs for the Snapshot tunnel replay.

    Returns:
        Hourly levels and price samples bounded by the replay window.

    """
    if settings is None:
        return None
    times = pd.to_datetime(data["time"], utc=True)
    start, cutoff = times.min().to_pydatetime(), times.max().to_pydatetime()
    try:
        candles = load_retest_window(
            "BTCUSDT", start, cutoff, lookback=settings.lookback
        )
        quotes = load_retest_quotes(
            "BTCUSDT", start, cutoff, interval=settings.interval
        )
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        _ = st.warning(f"Retest oscillator unavailable: {exc}")
        return None
    if not candles or not quotes:
        _ = st.info(
            "No completed hourly candles or spot quotes for Retest in this"
            " window."
        )
    return RetestHistory(
        candles=candles, start=start, settings=settings, quotes=quotes
    )


def _add_confirmations(
    chart: go.Figure, signals: tuple[Retest, ...], *, start: datetime, row: int
) -> None:
    line_times: list[datetime | None] = []
    levels: list[float] = []
    for signal in signals:
        line_times.extend(
            (max(start, signal.origin), signal.confirmed_at, None)
        )
        levels.extend((signal.level, signal.level, float("nan")))
    _ = chart.add_trace(
        go.Scatter(
            x=line_times,
            y=levels,
            mode="lines",
            name="Retest levels",
            hoverinfo="skip",
            line={"color": "#16a34a", "width": 2},
        ),
        row=row,
        col=1,
    )
    _ = chart.add_trace(
        go.Scatter(
            x=[signal.confirmed_at for signal in signals],
            y=[signal.level for signal in signals],
            text=[f"{signal.side} retest confirmed" for signal in signals],
            mode="markers",
            name="Retest confirmations",
            marker={"color": "#16a34a", "size": 8},
            hovertemplate="%{text} · %{y:,.2f}<extra></extra>",
        ),
        row=row,
        col=1,
    )


def add_retest_panel(
    chart: go.Figure, snapshot: Snapshot, *, days: int
) -> None:
    """Draw spot candles and confirmed retest levels on the shared timeline."""
    lookback = retest_lookback()
    symbol = f"{snapshot.asset}USDT"
    start = snapshot.timestamp - timedelta(days=days)
    history = load_retest_candles(
        symbol, snapshot.timestamp, days=days, lookback=lookback
    )
    if not any(candle.closed_at >= start for candle in history):
        _ = st.info(f"No completed {symbol} spot candles in this window.")
    else:
        add_retest_history(
            chart,
            RetestHistory(
                candles=history,
                start=start,
                settings=RetestSettings(lookback=lookback),
                quotes=load_retest_quotes(
                    symbol, start, snapshot.timestamp, interval="5m"
                ),
            ),
            row=RETEST_ROW,
        )


def retest_lookback() -> int:
    """Read the number of prior hourly candles for each decision.

    Returns:
        The selected lookback in candles.

    """
    return st.number_input(
        "Retest lookback candles",
        min_value=1,
        max_value=500,
        value=DEFAULT_RETEST_LOOKBACK,
        step=1,
        help="The preceding hourly candles used to find each high and low.",
    )


def retest_settings() -> RetestSettings:
    """Read replay controls for the two sampling intervals and three modes.

    Returns:
        The selected Retest configuration.

    """
    return RetestSettings(
        lookback=retest_lookback(),
        interval=st.selectbox(
            "Retest price interval",
            ("1m", "5m"),
            index=1,
            help=(
                "Spot opening quote cadence. Reference candles are always 1"
                " hour."
            ),
        ),
        mode=st.selectbox(
            "Retest confirmation mode",
            tuple(RetestMode),
            index=1,
        ),
    )


def add_retest_history(
    chart: go.Figure, history: RetestHistory, *, row: int
) -> None:
    """Plot completed spot candles and mark each confirmed high or low."""
    visible = tuple(
        candle
        for candle in history.candles
        if candle.closed_at >= history.start
    )
    _ = chart.add_trace(
        go.Candlestick(
            x=[candle.closed_at for candle in visible],
            open=[candle.open for candle in visible],
            high=[candle.high for candle in visible],
            low=[candle.low for candle in visible],
            close=[candle.close for candle in visible],
            name="Retest · Bybit spot · 1h",
        ),
        row=row,
        col=1,
    )
    signals = tuple(
        signal
        for assessment in _assess_retests(history)
        for signal in assessment.signals
    )
    _add_confirmations(chart, signals, start=history.start, row=row)
