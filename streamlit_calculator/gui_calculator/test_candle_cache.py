# Copyright 2026 anchored-vwam-backtest contributors
"""Test candle cache."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pandas as pd

from gui_calculator.candle_cache import (
    CandleMarket,
    HistoricalCandleCache,
    load_cached_klines,
)


def _candles(times: list[int]) -> pd.DataFrame:
    return pd.DataFrame({
        "time": pd.to_datetime(times, unit="ms", utc=True),
        "open": [1.0] * len(times),
        "high": [2.0] * len(times),
        "low": [0.5] * len(times),
        "close": [1.5] * len(times),
        "volume": [10.0] * len(times),
        "quote_asset_volume": [15.0] * len(times),
        "number_of_trades": [2] * len(times),
    })


def test_cache_persists_deduplicates_and_filters() -> None:
    """Verify expected behavior."""
    with TemporaryDirectory() as directory:
        cache = HistoricalCandleCache(Path(directory) / "candles.sqlite")
        cache.upsert(
            exchange="mexc",
            symbol="SHIBUSDT",
            interval="1m",
            candles=_candles([0, 60_000]),
        )
        cache.upsert(
            exchange="mexc",
            symbol="SHIBUSDT",
            interval="1m",
            candles=_candles([60_000]),
        )

        result = cache.load(
            exchange="mexc",
            symbol="SHIBUSDT",
            interval="1m",
            start_ms=0,
            end_ms=60_000,
        )

        assert result["time"].tolist() == list(
            pd.to_datetime([0, 60_000], unit="ms", utc=True)
        )


def test_loader_chunks_and_resumes_without_refetching() -> None:
    """Verify expected behavior."""
    with TemporaryDirectory() as directory:
        cache = HistoricalCandleCache(Path(directory) / "candles.sqlite")
        calls: list[tuple[int, int]] = []

        def fetcher(
            _symbol: str,
            _interval: str,
            *,
            start_ms: int,
            end_ms: int,
        ) -> pd.DataFrame:
            calls.append((start_ms, end_ms))
            return _candles([start_ms])

        end_ms = 60_000 * 1001
        first = load_cached_klines(
            CandleMarket(exchange="mexc", symbol="SHIBUSDT", interval="1m"),
            start_ms=0,
            end_ms=end_ms,
            fetcher=fetcher,
            cache=cache,
        )
        second = load_cached_klines(
            CandleMarket(exchange="mexc", symbol="SHIBUSDT", interval="1m"),
            start_ms=0,
            end_ms=end_ms,
            fetcher=fetcher,
            cache=cache,
        )

        assert calls == [(0, 59_999_999), (60_000_000, end_ms)]
        expected_count = 2
        assert len(first) == expected_count
        assert first.equals(second)


def test_empty_download_is_retried_not_permanently_cached(
    tmp_path: Path,
) -> None:
    """Verify expected behavior."""
    cache = HistoricalCandleCache(tmp_path / "empty.sqlite")
    calls: list[tuple[str, str, int, int]] = []

    def fetcher(
        symbol: str,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> pd.DataFrame:
        calls.append((symbol, interval, start_ms, end_ms))
        return _candles([])

    for _ in range(2):
        assert load_cached_klines(
            CandleMarket(
                exchange="bybit_linear", symbol="XRPUSDT", interval="1m"
            ),
            start_ms=0,
            end_ms=59999,
            fetcher=fetcher,
            cache=cache,
        ).empty
    expected_count = 2
    assert len(calls) == expected_count
    assert cache.missing_ranges(
        exchange="bybit_linear",
        symbol="XRPUSDT",
        interval="1m",
        start_ms=0,
        end_ms=59999,
    ) == [(0, 59999)]


def test_future_candles_are_not_requested_or_stored(tmp_path: Path) -> None:
    """Verify expected behavior."""
    cache = HistoricalCandleCache(tmp_path / "future.sqlite")
    fetcher = Mock()
    future = int(
        (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)).timestamp() * 1000
    )
    assert load_cached_klines(
        CandleMarket(exchange="bybit_linear", symbol="XRPUSDT", interval="1m"),
        start_ms=future,
        end_ms=future + 60000,
        fetcher=fetcher,
        cache=cache,
    ).empty
    fetcher.assert_not_called()


def test_market_categories_do_not_share_cache(tmp_path: Path) -> None:
    """Verify expected behavior."""
    cache = HistoricalCandleCache(tmp_path / "markets.sqlite")
    cache.upsert(
        exchange="bybit",
        symbol="XRPUSDT",
        interval="1m",
        candles=_candles([0]),
    )
    assert cache.load(
        exchange="bybit_linear",
        symbol="XRPUSDT",
        interval="1m",
        start_ms=0,
        end_ms=59999,
    ).empty
