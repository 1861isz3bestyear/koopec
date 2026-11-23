# Copyright 2026 anchored-vwam-backtest contributors
"""Provide candle cache behavior."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import koopec_calculus
import pandas as pd

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
        koopec_calculus.initialize_candles(path)

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
        koopec_calculus.upsert_candles(
            self.path, (exchange, symbol, interval), rows
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
        koopec_calculus.mark_candle_download(
            self.path, (exchange, symbol, interval), (start_ms, end_ms)
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
        return koopec_calculus.missing_candle_ranges(
            self.path, (exchange, symbol, interval), (start_ms, end_ms)
        )

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
        rows = koopec_calculus.load_candles(
            self.path, (exchange, symbol, interval), (start_ms, end_ms)
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
