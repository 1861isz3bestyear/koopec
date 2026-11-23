# Copyright 2026 anchored-vwam-backtest contributors
"""Real HTTP -> SQLite -> indicator -> execution -> metrics/CSV integration."""

from io import StringIO
from typing import TYPE_CHECKING, cast

import pandas as pd
import pytest
import requests
from shared.indicators import add_launch_weekly_anchored_vwap
from shared.strategy import backtest
from shared.validation import numeric_string

from gui_calculator import data_sources
from gui_calculator.candle_cache import (
    CandleMarket,
    HistoricalCandleCache,
    load_cached_klines,
)
from gui_calculator.metrics import summarize
from tests.support import uncached

if TYPE_CHECKING:
    from pathlib import Path

    from shared.models import Trade

    from tests.conftest import MarketHTTP

pytestmark = pytest.mark.integration


def calculate(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[Trade]]:
    """Return calculate.

    Returns:
        The computed result.

    """
    data = add_launch_weekly_anchored_vwap(
        raw, pd.to_datetime(raw["time"], utc=True).iloc[0], 2
    )
    equity, trades = backtest(
        data,
        pd.to_datetime(raw["time"], utc=True).iloc[0],
        strategy_end_at=pd.to_datetime(raw["time"], utc=True).iloc[-1],
        initial_capital=1000,
        fee_pct=0.1,
        stop_loss_pct=0,
        take_profit_pct=0,
        allow_reentry=True,
        strategy_mode="VWAP band mean reversion",
        band_sigma=1,
        exit_band_sigma=2,
        trend_mode=True,
        open_position_side="Long",
    )
    return equity, trades


def test_http_cache_restart_and_csv_produce_identical_realistic_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, market_http: MarketHTTP
) -> None:
    """Verify http cache restart and csv produce identical realistic results."""
    monkeypatch.setattr(data_sources, "BYBIT_KLINES_URL", market_http.url)
    path = tmp_path / "history.sqlite"
    args = (
        "bybit_linear",
        "XRPUSDT",
        "1m",
        market_http.start,
        market_http.start + 239999,
        uncached(data_sources.fetch_bybit_klines),
    )
    market = CandleMarket(exchange=args[0], symbol=args[1], interval=args[2])
    raw = load_cached_klines(
        market,
        start_ms=args[3],
        end_ms=args[4],
        fetcher=args[5],
        cache=HistoricalCandleCache(path),
    )
    expected_count = 4
    assert len(raw) == expected_count
    expected_count = 2
    assert (
        len(market_http.requests) == expected_count
    )  # Descending pages normalized to chronological rows.
    assert all(q["category"] == "linear" for q in market_http.requests)
    cached = load_cached_klines(
        market,
        start_ms=args[3],
        end_ms=args[4],
        fetcher=args[5],
        cache=HistoricalCandleCache(path),
    )
    assert (
        len(market_http.requests) == expected_count
    )  # A fresh cache object reuses on-disk history.
    pd.testing.assert_frame_equal(raw, cached)
    equity, trades = calculate(raw)
    assert len(trades) == 1
    trade = trades[0]
    assert (trade.entry_price, trade.exit_price) == (100, 102)
    assert trade.quantity == pytest.approx(9.99)
    assert trade.pnl == pytest.approx(17.96102)
    assert summarize(equity, trades, 1000)["Final equity"] == pytest.approx(
        1017.96102
    )
    for name in ["entry", "exit"]:
        trade_time = trade.entry_time if name == "entry" else trade.exit_time
        trade_price = trade.entry_price if name == "entry" else trade.exit_price
        candle = raw.loc[
            pd.to_datetime(raw["time"], utc=True) == trade_time
        ].iloc[0]
        assert (
            numeric_string(cast("object", candle["low"]))
            <= trade_price
            <= numeric_string(cast("object", candle["high"]))
        )
    uploaded = data_sources.parse_uploaded_csv(
        StringIO(raw.to_csv(index=False))
    )
    uploaded_equity, uploaded_trades = calculate(uploaded)
    # CSV timestamps may use a different pandas storage resolution; compare
    # identical instants explicitly, without relaxing numeric-column equality.
    equity["time"] = pd.to_datetime(equity["time"], utc=True).dt.as_unit("ns")
    uploaded_equity["time"] = pd.to_datetime(
        uploaded_equity["time"], utc=True
    ).dt.as_unit("ns")
    pd.testing.assert_frame_equal(equity, uploaded_equity)
    assert uploaded_trades == trades


def test_failed_http_page_does_not_commit_download_then_retry_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, market_http: MarketHTTP
) -> None:
    """Verify failed http page does not commit download then retry recovers."""
    monkeypatch.setattr(data_sources, "BYBIT_KLINES_URL", market_http.url)
    path = tmp_path / "retry.sqlite"
    args = (
        "bybit_linear",
        "XRPUSDT",
        "1m",
        market_http.start,
        market_http.start + 239999,
        uncached(data_sources.fetch_bybit_klines),
    )
    market_http.fail_request = 2
    market = CandleMarket(exchange=args[0], symbol=args[1], interval=args[2])
    with pytest.raises(requests.HTTPError):
        _ = load_cached_klines(
            market,
            start_ms=args[3],
            end_ms=args[4],
            fetcher=args[5],
            cache=HistoricalCandleCache(path),
        )
    cache = HistoricalCandleCache(path)
    assert cache.load(
        exchange=market.exchange,
        symbol=market.symbol,
        interval=market.interval,
        start_ms=market_http.start,
        end_ms=market_http.start + 239999,
    ).empty
    assert cache.missing_ranges(
        exchange=market.exchange,
        symbol=market.symbol,
        interval=market.interval,
        start_ms=market_http.start,
        end_ms=market_http.start + 239999,
    ) == [(market_http.start, market_http.start + 239999)]
    market_http.fail_request = None
    recovered = load_cached_klines(
        market,
        start_ms=args[3],
        end_ms=args[4],
        fetcher=args[5],
        cache=HistoricalCandleCache(path),
    )
    expected_count = 4
    assert len(recovered) == expected_count
    assert calculate(recovered)[1][0].pnl == pytest.approx(17.96102)
