# Copyright 2026 anchored-vwam-backtest contributors
"""Provide data sources behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Never, cast

import numpy as np
import pandas as pd
import requests
import streamlit as st
from shared.validation import (
    numeric_rows,
    numeric_string,
    object_list,
    object_mapping,
)

from gui_calculator.intervals import INTERVALS as INTERVALS

if TYPE_CHECKING:
    from gui_calculator.settings import CSVSource

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BYBIT_KLINES_URL = "https://api.bybit.com/v5/market/kline"
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"
MEXC_KLINES_URL = "https://api.mexc.com/api/v3/klines"
SYMBOL = "BTCUSDT"
MINIMUM_HEADERLESS_COLUMNS = 6
MILLISECOND_TIMESTAMP_THRESHOLD = 10_000_000_000
BYBIT_TICKERS = {
    "BTC_USDT": "BTCUSDT",
    "XRP_USDT": "XRPUSDT",
    "DOGE_USDT": "DOGEUSDT",
    "ADA_USDT": "ADAUSDT",
    "TRX_USDT": "TRXUSDT",
    "LINK_USDT": "LINKUSDT",
    "AVAX_USDT": "AVAXUSDT",
    "DOT_USDT": "DOTUSDT",
    "TON_USDT": "TONUSDT",
    "NEAR_USDT": "NEARUSDT",
}
MEXC_TICKERS = {
    "SHIB_USDT": "SHIBUSDT",
    "VET_USDT": "VETUSDT",
    "VED_USDT": "VEDUSDT",
}
CANDLE_COLUMNS = [
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_asset_volume",
    "number_of_trades",
]


def raise_mexc_api_error(payload: dict[str, object]) -> Never:
    """Raise the domain error reported by MEXC.

    Raises:
        ValueError: Always, with the exchange-provided message.

    """
    msg = f"MEXC API error: {payload.get('msg', 'unknown error')}"
    raise ValueError(msg)


def reverse_candles(candles: pd.DataFrame) -> pd.DataFrame:
    """Convert BASE/QUOTE candles into synthetic QUOTE/BASE candles.

    Returns:
        A copy containing reciprocal prices and exchanged volume measures.

    Raises:
        ValueError: If any source price is zero or negative.

    """
    result = candles.copy()
    price_columns = ["open", "high", "low", "close"]
    if (result[price_columns] <= 0).any().any():
        msg = "Cannot reverse candles containing zero or negative prices."
        raise ValueError(msg)
    original_high = result["high"].copy()
    original_low = result["low"].copy()
    original_volume = result["volume"].copy()
    result["open"] = 1 / result["open"]
    result["high"] = 1 / original_low
    result["low"] = 1 / original_high
    result["close"] = 1 / result["close"]
    result["volume"] = result["quote_asset_volume"]
    result["quote_asset_volume"] = original_volume
    return result


@st.cache_data(show_spinner=False)
def generate_sample_klines(interval: str) -> pd.DataFrame:
    """Generate deterministic sample candles for the selected interval.

    Returns:
        Sample candles spanning the application's demonstration period.

    """
    rng = pd.date_range(
        "2022-01-01",
        "2026-07-17 23:00:00",
        freq=INTERVALS[interval]["freq"],
        tz="UTC",
    )
    random = np.random.default_rng(42)
    anchor_dates = pd.to_datetime(
        [
            "2022-01-01",
            "2022-11-21",
            "2023-10-23",
            "2024-03-14",
            "2024-08-05",
            "2024-12-16",
            "2025-04-07",
            "2025-10-06",
            "2026-04-06",
            "2026-07-17",
        ],
        utc=True,
    )
    anchor_prices = np.array([
        46_300,
        15_700,
        31_000,
        73_800,
        49_000,
        106_000,
        74_500,
        123_000,
        91_000,
        118_000,
    ])
    x = rng.view("int64")
    anchor_x = anchor_dates.view("int64")
    baseline = np.interp(x, anchor_x, anchor_prices)

    volatility = 0.008 if interval == "1d" else 0.0022
    noise = random.normal(0, volatility, len(rng))
    noise = np.array(
        pd.Series(noise).rolling(5, min_periods=1).mean().tolist(), dtype=float
    )
    close = np.clip(baseline * (1 + noise), 14_000, 130_000)
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(random.normal(0.0018, 0.001, len(rng)))
    high = np.maximum(open_, close) * (1 + spread)
    low = np.minimum(open_, close) * (1 - spread)
    volume = np.maximum(40, random.lognormal(5.5, 0.55, len(rng)))

    return pd.DataFrame({
        "time": rng,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "quote_asset_volume": volume * close,
        "number_of_trades": np.maximum(100, volume * 18).astype(int),
    })


@st.cache_data(ttl=900, show_spinner=False)
def fetch_klines(
    symbol: str,
    interval: str,
    *,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Fetch Binance spot candles in the application's candle schema.

    Returns:
        Candles returned by Binance, or an empty standard-schema frame.

    """
    frames: list[pd.DataFrame] = []
    cursor = start_ms

    while cursor < end_ms:
        response = requests.get(
            BINANCE_KLINES_URL,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            },
            timeout=20,
        )
        response.raise_for_status()
        rows = numeric_rows(cast("object", response.json()), 12)
        if not rows:
            break

        frames.append(
            pd.DataFrame(
                rows,
                columns=[
                    "open_time",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "quote_asset_volume",
                    "number_of_trades",
                    "taker_buy_base_volume",
                    "taker_buy_quote_volume",
                    "ignore",
                ],
            )
        )
        next_cursor = int(rows[-1][0]) + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor

    if not frames:
        return pd.DataFrame(columns=CANDLE_COLUMNS)

    df = pd.concat(frames, ignore_index=True)
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "number_of_trades",
    ]
    df[numeric_columns] = df[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df[CANDLE_COLUMNS]


@st.cache_data(ttl=900, show_spinner=False)
def fetch_mexc_klines(
    symbol: str,
    interval: str,
    *,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Fetch MEXC spot candles in the application's candle schema.

    Returns:
        Chronologically ordered, deduplicated candles.

    Raises:
        ValueError: If the interval is invalid or MEXC reports an error.

    """
    mexc_intervals = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "60m",
        "4h": "4h",
        "1d": "1d",
    }
    if interval not in mexc_intervals:
        msg = f"MEXC does not support interval {interval!r}."
        raise ValueError(msg)
    interval_ms = int(INTERVALS[interval]["delta"].total_seconds() * 1000)

    frames: list[pd.DataFrame] = []
    cursor = start_ms

    while cursor < end_ms:
        # MEXC returns at most 1,000 candles and may return an empty response
        # when the requested time window contains substantially more than that.
        page_end = min(end_ms, cursor + interval_ms * 1000 - 1)
        response = requests.get(
            MEXC_KLINES_URL,
            params={
                "symbol": symbol,
                "interval": mexc_intervals[interval],
                "startTime": cursor,
                "endTime": page_end,
                "limit": 1000,
            },
            timeout=20,
        )
        response.raise_for_status()
        raw = cast("object", response.json())
        if isinstance(raw, dict):
            payload = object_mapping(cast("object", raw))
            raise_mexc_api_error(payload)
        rows = numeric_rows(raw, 8)
        if not rows:
            break

        frames.append(
            pd.DataFrame(
                rows,
                columns=[
                    "open_time",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "quote_asset_volume",
                ],
            )
        )
        next_cursor = int(rows[-1][0]) + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor

    if not frames:
        return pd.DataFrame(columns=CANDLE_COLUMNS)

    df = pd.concat(frames, ignore_index=True)
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
    ]
    df[numeric_columns] = df[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    df["time"] = pd.to_datetime(
        pd.to_numeric(df["open_time"]), unit="ms", utc=True
    )
    df["number_of_trades"] = 0
    df = (
        df.drop_duplicates(subset="time")
        .sort_values("time")
        .reset_index(drop=True)
    )
    return df[CANDLE_COLUMNS]


@st.cache_data(ttl=900, show_spinner=False)
def fetch_bybit_klines(
    symbol: str,
    interval: str,
    *,
    start_ms: int,
    end_ms: int,
    category: Literal["linear", "spot"] = "linear",
) -> pd.DataFrame:
    """Fetch Bybit candles in the standard schema.

    Returns:
        Chronologically ordered, deduplicated candles.

    Raises:
        ValueError: If the interval or response payload is invalid.

    """
    bybit_intervals = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "240",
        "1d": "D",
    }
    if interval not in bybit_intervals:
        msg = f"Bybit does not support interval {interval!r}."
        raise ValueError(msg)

    rows: list[list[float]] = []
    cursor_end = end_ms
    while cursor_end >= start_ms:
        response = requests.get(
            BYBIT_KLINES_URL,
            params={
                "category": category,
                "symbol": symbol,
                "interval": bybit_intervals[interval],
                "start": start_ms,
                "end": cursor_end,
                "limit": 1000,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = object_mapping(cast("object", response.json()))
        if payload.get("retCode") != 0:
            msg = f"Bybit API error: {payload.get('retMsg', 'unknown error')}"
            raise ValueError(msg)

        page = numeric_rows(
            object_mapping(payload.get("result", {})).get("list", []), 7
        )
        if not page:
            break
        rows.extend(page)

        next_cursor_end = min(int(row[0]) for row in page) - 1
        if next_cursor_end >= cursor_end:
            break
        cursor_end = next_cursor_end

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_asset_volume",
        ],
    )
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
    ]
    df[numeric_columns] = df[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    df["time"] = pd.to_datetime(
        pd.to_numeric(df["open_time"]), unit="ms", utc=True
    )
    df["number_of_trades"] = 0
    df = (
        df.drop_duplicates(subset="time")
        .sort_values("time")
        .reset_index(drop=True)
    )
    return df[[
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "number_of_trades",
    ]]


@st.cache_data(ttl=5, show_spinner=False)
def fetch_bybit_live_price(symbol: str) -> float:
    """Return the latest live linear-contract price from Bybit's public API.

    Returns:
        The strictly positive latest contract price.

    Raises:
        ValueError: If Bybit reports an error, no ticker, or an invalid price.

    """
    response = requests.get(
        BYBIT_TICKERS_URL,
        params={"category": "linear", "symbol": symbol},
        timeout=20,
    )
    response.raise_for_status()
    payload = object_mapping(cast("object", response.json()))
    if payload.get("retCode") != 0:
        msg = f"Bybit API error: {payload.get('retMsg', 'unknown error')}"
        raise ValueError(msg)
    tickers = object_list(
        object_mapping(payload.get("result", {})).get("list", [])
    )
    if not tickers:
        msg = f"Bybit returned no live price for {symbol}."
        raise ValueError(msg)
    price = numeric_string(object_mapping(tickers[0])["lastPrice"])
    if price <= 0:
        msg = f"Bybit returned an invalid live price for {symbol}."
        raise ValueError(msg)
    return price


def fetch_bybit_linear_klines(
    symbol: str,
    interval: str,
    *,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Fetch completed linear candles for the live local-paper strategy.

    Returns:
        Chronologically ordered completed candles.

    Raises:
        ValueError: If the interval or response payload is invalid.

    """
    bybit_intervals = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "240",
        "1d": "D",
    }
    interval_ms = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }
    if interval not in bybit_intervals:
        msg = f"Bybit does not support interval {interval!r}."
        raise ValueError(msg)
    rows: list[list[float]] = []
    cursor_end = end_ms
    while cursor_end > start_ms:
        response = requests.get(
            BYBIT_KLINES_URL,
            params={
                "category": "linear",
                "symbol": symbol,
                "interval": bybit_intervals[interval],
                "start": start_ms,
                "end": cursor_end,
                "limit": 1000,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = object_mapping(cast("object", response.json()))
        if payload.get("retCode") != 0:
            msg = f"Bybit API error: {payload.get('retMsg', 'unknown error')}"
            raise ValueError(msg)
        page = numeric_rows(
            object_mapping(payload.get("result", {})).get("list", []), 7
        )
        if not page:
            break
        rows.extend(page)
        next_cursor_end = min(int(row[0]) for row in page) - 1
        if next_cursor_end >= cursor_end:
            break
        cursor_end = next_cursor_end
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_asset_volume",
        ],
    )
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
    ]
    frame[numeric_columns] = frame[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    frame["open_time"] = pd.to_numeric(frame["open_time"])
    frame = frame[
        frame["open_time"].astype(float) + interval_ms[interval] <= end_ms
    ]
    frame["time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["number_of_trades"] = 0
    frame = (
        frame.drop_duplicates(subset="time")
        .sort_values("time")
        .reset_index(drop=True)
    )
    return frame[[
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "number_of_trades",
    ]]


def parse_uploaded_csv(uploaded_file: CSVSource) -> pd.DataFrame:
    """Parse an uploaded candle CSV into the application's standard schema.

    Returns:
        Valid, chronological candle rows in the standard schema.

    Raises:
        ValueError: If required timestamp or price columns are missing.

    """
    raw = pd.read_csv(uploaded_file)
    columns = {str(column).strip().lower(): column for column in raw.columns}

    if (
        not {"open_time", "time", "timestamp"}.intersection(columns)
        and len(raw.columns) >= MINIMUM_HEADERLESS_COLUMNS
    ):
        if not isinstance(uploaded_file, str):
            _ = uploaded_file.seek(0)
        raw = pd.read_csv(
            uploaded_file,
            header=None,
            names=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "number_of_trades",
                "taker_buy_base_volume",
                "taker_buy_quote_volume",
                "ignore",
            ],
        )
        columns = {
            str(column).strip().lower(): column for column in raw.columns
        }

    time_column = (
        columns.get("time")
        or columns.get("open_time")
        or columns.get("timestamp")
    )
    required = ["open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in columns]
    if time_column is None or missing:
        msg = (
            "CSV must include time/open_time and open, high, low, close, volume"
            " columns."
        )
        raise ValueError(msg)

    parsed = pd.DataFrame()
    raw_time = raw[time_column]
    if pd.api.types.is_numeric_dtype(raw_time):
        unit = (
            "ms"
            if raw_time.astype("int64").median()
            > MILLISECOND_TIMESTAMP_THRESHOLD
            else "s"
        )
        parsed["time"] = pd.to_datetime(raw_time, unit=unit, utc=True)
    else:
        parsed["time"] = pd.to_datetime(raw_time, utc=True)

    for column in required:
        parsed[column] = pd.to_numeric(raw[columns[column]], errors="coerce")

    parsed["quote_asset_volume"] = parsed["close"] * parsed["volume"]
    parsed["number_of_trades"] = 0
    return parsed.dropna().sort_values("time").reset_index(drop=True)
