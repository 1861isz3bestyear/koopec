# Copyright 2026 anchored-vwam-backtest contributors
"""Exercise the compiled Python extension at its public boundary."""

import math

import koopec_calculus
import pytest


def test_at_money_call_and_put_match_independent_gamma() -> None:
    """Call and put have equal, opposite exposure at the same strike."""
    contracts = [
        ("call", "call", 100.0, 31_536_000, 0.5, 10.0, 2.0),
        ("put", "put", 100.0, 31_536_000, 0.5, 10.0, 2.0),
    ]
    result = koopec_calculus.strike_exposures(0, 0, 0, 100.0, contracts)
    gamma = math.exp(-(0.25**2) / 2) / (100 * 0.5 * math.sqrt(2 * math.pi))
    expected = gamma * 10 * 2 * 100**2 * 0.01
    assert len(result) == 1
    assert result[0][0] == pytest.approx(100.0)
    assert result[0][1] == pytest.approx(expected, rel=1e-12)
    assert result[0][2] == pytest.approx(-expected, rel=1e-12)


def test_expiry_boundary_and_empty_chain() -> None:
    """An option is unavailable at expiry, but live a second before it."""
    contract = ("a", "call", 100.0, 10, 0.5, 1.0, 1.0)
    assert koopec_calculus.strike_exposures(0, 0, 0, 100.0, []) == []
    assert (
        len(koopec_calculus.strike_exposures(0, 0, 9, 100.0, [contract])) == 1
    )
    assert koopec_calculus.strike_exposures(0, 0, 10, 100.0, [contract]) == []


def test_invalid_inputs_are_rejected() -> None:
    """Reject invalid side, value, duplicate identity and noncausal time."""
    valid = ("a", "call", 100.0, 10, 0.5, 1.0, 1.0)
    for contracts in [
        [("a", "other", 100.0, 10, 0.5, 1.0, 1.0)],
        [("a", "call", 100.0, 10, math.nan, 1.0, 1.0)],
        [valid, valid],
        [valid] * 10_001,
    ]:
        with pytest.raises(ValueError, match=r"Invalid|Too many"):
            _ = koopec_calculus.strike_exposures(0, 0, 0, 100.0, contracts)
    with pytest.raises(ValueError, match="Invalid"):
        _ = koopec_calculus.strike_exposures(0, 1, 0, 100.0, [valid])


def test_ranked_walls_respects_inclusive_range_and_lower_strike_ties() -> None:
    """Call ranks break ties by price and distant puts stay out of range."""
    levels = [(80.0, 10.0, 0.0), (120.0, 10.0, -2.0), (121.0, 0.0, -9.0)]
    calls, puts = koopec_calculus.ranked_walls(levels, 100.0, 0.2)
    assert calls == levels[:2]
    assert puts == levels[1:2]
    assert koopec_calculus.ranked_walls(levels, 100.0, None)[1][0] == levels[2]


def test_max_pain_handles_mixed_expiry_and_payout_ties() -> None:
    """Equal OI across a wider call/put interval gives the lower strike."""
    call = ("call", "call", 90.0, 10, 0.5, 10.0, 2.0)
    put = ("put", "put", 110.0, 10, 0.5, 10.0, 2.0)
    assert koopec_calculus.options_max_pain([call, put]) == pytest.approx(
        call[2]
    )
    assert (
        koopec_calculus.options_max_pain(
            [call, ("put", "put", 110.0, 11, 0.5, 10.0, 2.0)]
        )
        is None
    )
    assert koopec_calculus.options_max_pain([]) is None


@pytest.mark.parametrize(
    ("period", "step_ms"), [("24h", 3_600_000), ("30d", 86_400_000)]
)
def test_margin_warmup_ready_and_gap(period: str, step_ms: int) -> None:
    """Thirteen positives and one equal loss give a 13/14 positive share."""
    offset_ms = 125
    points = [(offset_ms + index * step_ms, 1.0) for index in range(13)]
    points.extend([
        (offset_ms + 13 * step_ms, -1.0),
        (offset_ms + 14 * step_ms + 1, 1.0),
    ])
    values = koopec_calculus.margin_momentum(period, points)
    assert values[:13] == [None] * 13
    assert values[13] == pytest.approx(100 * 13 / 14)
    assert values[14] is None


def test_market_growth_enforces_receipt_cutoff_and_sorts() -> None:
    """Equal duplicates collapse and evidence after receipt is rejected."""
    payload = (
        '{"code":"00000","data":[{"ts":"2000","growthRate":"-1"},'
        '{"ts":1000,"growthRate":"2"},{"ts":"1000","growthRate":2}]}'
    )
    assert koopec_calculus.bitget_growth(payload, 2000) == [
        (1000, 2.0),
        (2000, -1.0),
    ]
    with pytest.raises(ValueError, match="Invalid public market data"):
        _ = koopec_calculus.bitget_growth(payload, 1999)
