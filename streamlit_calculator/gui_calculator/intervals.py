# Copyright 2026 anchored-vwam-backtest contributors
"""Candle interval metadata independent of exchange adapters."""

from datetime import timedelta
from typing import TypedDict


class Interval(TypedDict):
    """Describe the duration and pandas frequency for a candle interval."""

    delta: timedelta
    freq: str


INTERVALS: dict[str, Interval] = {
    "1m": {"delta": timedelta(minutes=1), "freq": "1min"},
    "5m": {"delta": timedelta(minutes=5), "freq": "5min"},
    "15m": {"delta": timedelta(minutes=15), "freq": "15min"},
    "1h": {"delta": timedelta(hours=1), "freq": "1h"},
    "4h": {"delta": timedelta(hours=4), "freq": "4h"},
    "1d": {"delta": timedelta(days=1), "freq": "1D"},
}
