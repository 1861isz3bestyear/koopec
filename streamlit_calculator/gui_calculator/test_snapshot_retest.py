# Copyright 2026 anchored-vwam-backtest contributors
"""Verify retest decisions and availability at the hourly exchange boundary."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from shared.tunnel import TunnelSettings
from snapshot_tunnel.tunnel_flow import (
    BOTH_DIRECTIONS,
    OscillatorObservation,
    TunnelFlow,
)

from gui_calculator.settings import RetestMode, RetestSettings
from gui_calculator.snapshot_retest import (
    HOUR,
    HourlyCandle,
    RetestHistory,
    SpotQuote,
    load_retest_candles,
    load_retest_quotes,
    retest_votes,
)
from gui_calculator.tunnel_replay import replay_tunnel

START = datetime(2026, 11, 24, tzinfo=UTC)


def candle(hour: int, high: float, low: float) -> HourlyCandle:
    """Produce a closed hourly candle around a fixed opening and close.

    Returns:
        A deterministic hourly candle.

    """
    return HourlyCandle(
        closed_at=START + hour * HOUR, open=90, high=high, low=low, close=90
    )


def test_load_spot_candles_at_historical_cutoff() -> None:
    """Request warmup and exclude candles that close after the cutoff."""
    times = (START, START + HOUR)
    frame = pd.DataFrame(
        {"time": times, "open": 90, "high": 100, "low": 80, "close": 91}
    )
    cutoff = START + HOUR + timedelta(minutes=30)
    with patch(
        "gui_calculator.snapshot_retest.fetch_bybit_klines", return_value=frame
    ) as fetch:
        candles = load_retest_candles("BTCUSDT", cutoff, days=1, lookback=2)
    fetch.assert_called_once_with(
        "BTCUSDT",
        "1h",
        start_ms=int((START - 25 * HOUR).timestamp() * 1000),
        end_ms=int((START + HOUR).timestamp() * 1000) - 1,
        category="spot",
    )
    assert [bar.closed_at for bar in candles] == [START + HOUR]


def test_reject_invalid_spot_range() -> None:
    """Reject external candles whose prices disagree with the wick range."""
    frame = pd.DataFrame(
        {"time": [START], "open": 90, "high": 89, "low": 80, "close": 85}
    )
    with (
        patch(
            "gui_calculator.snapshot_retest.fetch_bybit_klines",
            return_value=frame,
        ),
        pytest.raises(ValueError, match="invalid candle price range"),
    ):
        _ = load_retest_candles("ETHUSDT", START + HOUR, days=1, lookback=2)


@pytest.mark.parametrize(
    ("mode", "directions"),
    [
        (RetestMode.EITHER, (BOTH_DIRECTIONS, BOTH_DIRECTIONS, 0)),
        (RetestMode.REVERSAL, (-1, 1, 0)),
        (RetestMode.BREAKOUT, (1, -1, 0)),
    ],
)
def test_quote_touches_use_all_three_modes(
    mode: RetestMode, directions: tuple[int, ...]
) -> None:
    """Match both levels and leave an inside quote neutral."""
    times = tuple(START + 2 * HOUR + timedelta(minutes=i) for i in (5, 10, 15))
    history = RetestHistory(
        candles=(candle(1, 100, 80), candle(2, 95, 85), candle(3, 120, 70)),
        start=START,
        settings=RetestSettings(lookback=2, mode=mode),
        quotes=tuple(
            SpotQuote(available=now, price=price)
            for now, price in zip(times, (100, 80, 99.99), strict=True)
        ),
    )
    votes = retest_votes(history)
    assert tuple(point.available for point in votes) == times
    assert tuple(point.direction for point in votes) == directions
    assert all(point.calculatable for point in votes)


def test_hourly_levels_roll_and_require_contiguous_history() -> None:
    """Drop expired extremes and block votes until gaps fully warm up."""
    times = tuple(START + i * HOUR for i in range(1, 7))
    history = RetestHistory(
        candles=(
            candle(1, 110, 75),
            candle(2, 100, 80),
            candle(3, 99, 81),
            candle(5, 99, 81),
            candle(6, 100, 80),
        ),
        start=START,
        settings=RetestSettings(lookback=2),
        quotes=tuple(SpotQuote(available=now, price=100) for now in times),
    )
    votes = retest_votes(history)
    assert [point.calculatable for point in votes] == [
        False,
        True,
        True,
        False,
        False,
        True,
    ]
    assert [point.direction for point in votes] == [0, 0, -1, 0, 0, -1]


def test_load_minute_quotes_uses_only_open_price() -> None:
    """Read spot opens at the selected cadence and reject future rows."""
    time = START + timedelta(minutes=1)
    frame = pd.DataFrame({
        "time": [START, time],
        "open": [100, 101],
        "close": [999, 999],
    })
    with patch(
        "gui_calculator.snapshot_retest.fetch_bybit_klines", return_value=frame
    ) as fetch:
        quotes = load_retest_quotes("BTCUSDT", START, START, interval="1m")
    fetch.assert_called_once_with(
        "BTCUSDT",
        "1m",
        category="spot",
        start_ms=int(START.timestamp() * 1000),
        end_ms=int(START.timestamp() * 1000),
    )
    assert quotes == (SpotQuote(available=START, price=100),)


def test_replay_retest_joins_quorum_at_candle_close() -> None:
    """Allow both fresh votes and bar-open markers with causal cutoff."""
    settings = TunnelSettings(
        use_gex=False, use_book=True, use_retest=True, votes=2
    )
    close = START + 3 * HOUR
    times = pd.date_range(close - timedelta(minutes=5), periods=5, freq="5min")
    frame = pd.DataFrame({
        "time": times,
        "open": 90.0,
        "high": 95.0,
        "low": 85.0,
        "close": 90.0,
        "volume": 1.0,
    })
    flow = TunnelFlow(
        book=(OscillatorObservation(available=close, direction=1),),
        retest=(OscillatorObservation(available=close, direction=1),),
    )
    replay = replay_tunnel(
        frame, (), settings=settings, flow=flow, interval=timedelta(minutes=5)
    )
    assert replay["tunnel_confirmation_retest"].to_list() == [0, 1, 1, 1, 0]
    assert replay["options_direction"].to_list() == [0, 1, 1, 1, 0]


def test_retest_vote_expires_at_next_quote_even_with_a_gap() -> None:
    """A missing quote cannot prolong an older confirmation."""
    settings = TunnelSettings(
        use_gex=False, use_book=False, use_retest=True, maximum_age=2 * HOUR
    )
    flow = TunnelFlow(
        retest=(
            OscillatorObservation(
                available=START, direction=-1, valid_for=timedelta(minutes=1)
            ),
        )
    )
    minute = timedelta(minutes=1)
    assert (
        flow.direction(START + minute - timedelta.resolution, settings=settings)
        == -1
    )
    assert flow.direction(START + minute, settings=settings) == 0


def test_either_supports_each_side_without_choosing_a_side() -> None:
    """One symmetric vote supports a direction without selecting one itself."""
    either = OscillatorObservation(available=START, direction=BOTH_DIRECTIONS)
    settings = TunnelSettings(use_gex=False, use_book=False, use_retest=True)
    flow = TunnelFlow(retest=(either,))
    assert flow.direction(START, settings=settings) == 0
    assert flow.count(1, START, settings=settings) == 1
    assert flow.count(-1, START, settings=settings) == 1
    combined = TunnelSettings(use_gex=False, use_book=True, use_retest=True)
    short = OscillatorObservation(available=START, direction=-1)
    assert (
        TunnelFlow(book=(short,), retest=(either,)).direction(
            START, settings=combined
        )
        == -1
    )
