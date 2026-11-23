# Copyright 2026 anchored-vwam-backtest contributors
"""Exercise held binary state, nearby extrema, warmup and causality."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from snapshot_tunnel.oi_divergence import (
    DivergenceSettings,
    InterestSample,
    MarketSample,
    divergence_series,
)

PRICES = (90, 95, 100, 95, 90, 95, 110, 95, 90, 95, 120, 95, 90)
RATES = (0, 1, 3, 1, 0, 1, 5, 1, 0, 1, 4, 1, 0)


def market_samples(
    rates: tuple[float, ...] = RATES, prices: tuple[float, ...] = PRICES
) -> tuple[MarketSample, ...]:
    """Construct OI history with specified post-warmup smoothed rates.

    Returns:
        Contiguous hourly observations with exactly fourteen warmup samples.

    """
    quantities = [100.0] * 14
    changes = [0.0, 0.0]
    for rate in rates:
        change = 3 * rate - sum(changes[-2:])
        quantities.append(quantities[-12] * (1 + change / 100))
        changes.append(change)
    all_prices = (90.0,) * 14 + prices
    return tuple(
        MarketSample(
            interest=InterestSample(
                timestamp=datetime(2026, 1, 1, tzinfo=UTC)
                + timedelta(hours=index),
                value=quantity,
            ),
            price=all_prices[index],
        )
        for index, quantity in enumerate(quantities)
    )


def test_momentum_and_held_binary_states() -> None:
    """State starts unknown, changes on detection, then persists."""
    samples = market_samples()
    result = divergence_series(samples)
    assert [point.rate for point in result.points[14:]] == pytest.approx(RATES)
    assert result.states == (None,) * 22 + (0,) * 4 + (1,)
    assert [signal.state for signal in result.signals] == [0, 1]
    for signal in result.signals:
        assert signal.detected == (
            signal.current.point.sample.interest.timestamp
            + timedelta(hours=2, minutes=1)
        )
    assert result.signals[0].label == "No divergence (confirmation)"
    assert result.signals[1].label == "Divergence"
    assert all(
        point.rate is None for point in divergence_series(samples[:14]).points
    )
    assert not divergence_series(()).states


def test_signed_lows_and_nearby_extrema() -> None:
    """Lows compare signed values; oscillator extrema may lead or lag price."""
    lows = divergence_series(
        market_samples(
            tuple(-rate for rate in RATES),
            tuple(200 - price for price in PRICES),
        )
    )
    assert [signal.state for signal in lows.signals] == [0, 1]
    assert all(signal.current.kind == "low" for signal in lows.signals)
    result = divergence_series(
        market_samples((0, 4, 1, 0, 0, 1, 2, 6, 0), PRICES[:9])
    )
    signal = result.signals[0]
    previous_index = 15
    assert signal.previous.oi_index == previous_index
    expected_index = 21
    assert signal.current.oi_index == expected_index
    assert signal.current.rate == pytest.approx(6)


def test_filters_and_equal_peaks() -> None:
    """Noise thresholds, flat price and flat OI do not create false states."""
    for config in (
        DivergenceSettings(min_swing_percent=20),
        DivergenceSettings(min_oi_change=20),
    ):
        assert not divergence_series(market_samples(), settings=config).signals
    flat_price = divergence_series(
        market_samples(prices=(100.0,) * len(PRICES))
    )
    assert not flat_price.signals
    flat_oi = divergence_series(market_samples(rates=(0.0,) * len(RATES)))
    assert not flat_oi.signals
    equal_price = divergence_series(
        market_samples(
            prices=(90, 95, 100, 95, 90, 95, 100, 95, 90, 95, 99, 95, 90)
        )
    )
    assert not equal_price.signals
    shallow = tuple(100 + (price - 90) * 0.00001 for price in PRICES)
    assert not divergence_series(market_samples(prices=shallow)).signals


def test_prefix_causality_and_missing_hours() -> None:
    """Future observations cannot change known states; gaps restart warmup."""
    samples = market_samples()
    full = divergence_series(samples)
    for length in range(len(samples) + 1):
        result = divergence_series(samples[:length])
        assert result.points == full.points[: len(result.points)]
        assert result.states == full.states[: len(result.states)]
        assert result.signals == tuple(
            signal
            for signal in full.signals
            if length
            and signal.detected
            <= samples[length - 1].interest.timestamp + timedelta(minutes=1)
        )
    second = tuple(
        replace(
            sample,
            interest=replace(
                sample.interest,
                timestamp=sample.interest.timestamp + timedelta(hours=30),
            ),
        )
        for sample in samples
    )
    result = divergence_series((*samples, *second))
    assert result.states == (*full.states, *full.states)
    assert len(result.signals) == 2 * len(full.signals)
    trailing = divergence_series((*samples, second[0]))
    assert trailing.states[-1] is None
    with pytest.raises(ValueError, match="chronological"):
        _ = divergence_series((samples[0], samples[0]))


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_invalid_domain_values(value: float) -> None:
    """Reject nonfinite and negative configuration, prices and OI."""
    with pytest.raises(ValueError, match="thresholds"):
        _ = DivergenceSettings(min_swing_percent=value)
    with pytest.raises(ValueError, match="thresholds"):
        _ = DivergenceSettings(min_oi_change=value)
    with pytest.raises(ValueError, match="positive"):
        _ = InterestSample(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC), value=value
        )
    with pytest.raises(ValueError, match="price"):
        _ = replace(market_samples()[0], price=value)


def test_naive_timestamps_zero_values_and_overflow() -> None:
    """Reject invalid timestamps, zero base OI and overflowing rates."""
    with pytest.raises(ValueError, match="offset-aware"):
        _ = InterestSample(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
            value=1,
        )
    with pytest.raises(ValueError, match="positive"):
        _ = InterestSample(timestamp=datetime(2026, 1, 1, tzinfo=UTC), value=0)
    samples = list(market_samples())
    samples[0] = replace(
        samples[0], interest=replace(samples[0].interest, value=1e-308)
    )
    samples[12] = replace(
        samples[12], interest=replace(samples[12].interest, value=1e308)
    )
    with pytest.raises(ValueError, match="overflow"):
        _ = divergence_series(tuple(samples))
