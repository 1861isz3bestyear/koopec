# Copyright 2026 anchored-vwam-backtest contributors
"""Provide candle cache behavior."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import pandas as pd
from shared.validation import database_rows, integer

from gui_calculator.data_sources import CANDLE_COLUMNS, INTERVALS

DEFAULT_CANDLE_DB = (
    Path(__file__).resolve().parents[1] / "historical_candles.sqlite"
)


class KlineFetcher(Protocol):
    """Fetch exchange candles for an inclusive millisecond range."""

    def __call__(
        self,
        symbol: str,
        interval: str,
        /,
        *,
        start_ms: int,
        end_ms: int,
    ) -> pd.DataFrame:
        """Return candles in the requested range."""
        ...


@dataclass(frozen=True, kw_only=True)
class CandleMarket:
    """Identify an exchange candle series and its sampling interval."""

    exchange: str
    symbol: str
    interval: str


class HistoricalCandleCache:
    """Persistent exchange candle cache with resumable downloaded ranges."""

    def __init__(self, path: Path = DEFAULT_CANDLE_DB) -> None:
        """Create a candle cache backed by the SQLite database at ``path``."""
        self.path: Path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        _ = connection.execute("PRAGMA journal_mode=WAL")
        _ = connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            _ = connection.executescript("""
                CREATE TABLE IF NOT EXISTS candles (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    quote_asset_volume REAL NOT NULL,
                    number_of_trades INTEGER NOT NULL,
                    PRIMARY KEY (exchange, symbol, interval, open_time_ms)
                );
                CREATE TABLE IF NOT EXISTS downloaded_ranges (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    PRIMARY KEY (exchange, symbol, interval, start_ms, end_ms)
                );
                """)

    def upsert(
        self,
        *,
        exchange: str,
        symbol: str,
        interval: str,
        candles: pd.DataFrame,
    ) -> None:
        """Insert or update candles for one exchange and market interval."""
        if candles.empty:
            return
        rows = [
            (
                exchange,
                symbol,
                interval,
                int(timestamp.timestamp() * 1000),
                opening,
                high,
                low,
                close,
                volume,
                quote_volume,
                trades,
            )
            for timestamp, (opening, high, low, close), (
                volume,
                quote_volume,
                trades,
            ) in zip(
                pd.to_datetime(candles["time"], utc=True),
                zip(
                    candles["open"].astype(float),
                    candles["high"].astype(float),
                    candles["low"].astype(float),
                    candles["close"].astype(float),
                    strict=False,
                ),
                zip(
                    candles["volume"].astype(float),
                    candles["quote_asset_volume"].astype(float),
                    candles["number_of_trades"].astype(int),
                    strict=False,
                ),
                strict=False,
            )
        ]
        with closing(self._connect()) as connection, connection:
            _ = connection.executemany(
                """
                INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol, interval, open_time_ms)
                DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume,
                    quote_asset_volume=excluded.quote_asset_volume,
                    number_of_trades=excluded.number_of_trades
                """,
                rows,
            )

    def mark_downloaded(
        self,
        *,
        exchange: str,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> None:
        """Record a successfully downloaded candle range."""
        with closing(self._connect()) as connection, connection:
            _ = connection.execute(
                "INSERT OR IGNORE INTO downloaded_ranges VALUES (?, ?, ?,"
                " ?, ?)",
                (exchange, symbol, interval, start_ms, end_ms),
            )

    def missing_ranges(
        self,
        *,
        exchange: str,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[tuple[int, int]]:
        """Return portions of a requested range not present in the cache.

        Returns:
            Inclusive timestamp ranges that still need downloading.

        """
        with closing(self._connect()) as connection, connection:
            stored = database_rows(
                cast(
                    "object",
                    connection.execute(
                        """
                SELECT start_ms, end_ms FROM downloaded_ranges
                WHERE exchange=? AND symbol=? AND interval=?
                  AND end_ms >= ? AND start_ms <= ?
                ORDER BY start_ms
                """,
                        (exchange, symbol, interval, start_ms, end_ms),
                    ).fetchall(),
                )
            )
        cursor = start_ms
        missing: list[tuple[int, int]] = []
        for row in stored:
            covered_start, covered_end = (integer(value) for value in row)
            if covered_start > cursor:
                missing.append((cursor, min(end_ms, covered_start - 1)))
            cursor = max(cursor, covered_end + 1)
            if cursor > end_ms:
                break
        if cursor <= end_ms:
            missing.append((cursor, end_ms))
        return missing

    def load(
        self,
        *,
        exchange: str,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> pd.DataFrame:
        """Load cached candles within an inclusive timestamp range.

        Returns:
            A dataframe containing candles in the requested range.

        """
        with closing(self._connect()) as connection, connection:
            rows = database_rows(
                cast(
                    "object",
                    connection.execute(
                        """
                SELECT open_time_ms, open, high, low, close, volume,
                       quote_asset_volume, number_of_trades
                FROM candles
                WHERE exchange=? AND symbol=? AND interval=?
                  AND open_time_ms >= ? AND open_time_ms <= ?
                ORDER BY open_time_ms
                """,
                        (exchange, symbol, interval, start_ms, end_ms),
                    ).fetchall(),
                )
            )
        if not rows:
            return pd.DataFrame(columns=CANDLE_COLUMNS)
        frame = pd.DataFrame(
            rows,
            columns=[
                "open_time_ms",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "quote_asset_volume",
                "number_of_trades",
            ],
        )
        frame.insert(
            0,
            "time",
            pd.to_datetime(frame.pop("open_time_ms"), unit="ms", utc=True),
        )
        return frame[CANDLE_COLUMNS]


def _download_range(
    market: CandleMarket,
    *,
    start_ms: int,
    end_ms: int,
    fetcher: KlineFetcher,
    cache: HistoricalCandleCache,
) -> None:
    """Download and persist each chunk in one missing candle range."""
    interval_ms = int(
        INTERVALS[market.interval]["delta"].total_seconds() * 1000
    )
    chunk_span_ms = interval_ms * 1000
    chunk_start = start_ms
    while chunk_start <= end_ms:
        chunk_end = min(end_ms, chunk_start + chunk_span_ms - 1)
        candles = fetcher(
            market.symbol,
            market.interval,
            start_ms=chunk_start,
            end_ms=chunk_end,
        )
        if candles.empty:
            chunk_start = chunk_end + 1
            continue
        candles = candles[
            (
                candles["time"]
                >= pd.to_datetime(chunk_start, unit="ms", utc=True)
            )
            & (
                candles["time"]
                <= pd.to_datetime(chunk_end, unit="ms", utc=True)
            )
        ]
        cache.upsert(
            exchange=market.exchange,
            symbol=market.symbol,
            interval=market.interval,
            candles=candles,
        )
        cache.mark_downloaded(
            exchange=market.exchange,
            symbol=market.symbol,
            interval=market.interval,
            start_ms=chunk_start,
            end_ms=chunk_end,
        )
        chunk_start = chunk_end + 1


def load_cached_klines(
    market: CandleMarket,
    *,
    start_ms: int,
    end_ms: int,
    fetcher: KlineFetcher,
    cache: HistoricalCandleCache | None = None,
) -> pd.DataFrame:
    """Download missing chunks and return the complete cached range.

    Returns:
        The cached candles in the requested inclusive timestamp range.

    """
    exchange, symbol, interval = market.exchange, market.symbol, market.interval
    cache = cache or HistoricalCandleCache()
    interval_ms = int(INTERVALS[interval]["delta"].total_seconds() * 1000)
    # Never persist a forming candle or mark future history as downloaded.
    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    end_ms = min(end_ms, (now_ms // interval_ms) * interval_ms - 1)
    for missing_start, missing_end in cache.missing_ranges(
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
    ):
        _download_range(
            market,
            start_ms=missing_start,
            end_ms=missing_end,
            fetcher=fetcher,
            cache=cache,
        )
    return cache.load(
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
    )
