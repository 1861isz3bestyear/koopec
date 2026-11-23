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
