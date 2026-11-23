# Copyright 2026 anchored-vwam-backtest contributors
"""Validate the boundary between the copied Streamlit UI and Rust."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from snapshot_tunnel.options_model import Option, Snapshot
from snapshot_tunnel.options_model import strike_exposures as python_exposures

from gui_calculator.rust_backend import (
    build_exposure_request,
    parse_exposure_response,
    strike_exposures,
)

EXPECTED_RECEIPT = 1767225601
EXPECTED_PRICE = 100
EXPECTED_CALL = 2
EXPECTED_PUT = -3


def example_snapshot() -> Snapshot:
    """Build a deterministic one-contract example.

    Returns:
        A snapshot with fractional receipt time and an aware expiry.

    """
    receipt = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(microseconds=500000)
    return Snapshot(
        timestamp=receipt,
        asset="BTC",
        spot=100,
        options=(
            Option(
                exchange="DERIBIT",
                expiry=datetime(2026, 2, 1, tzinfo=UTC),
                strike=100,
                side="call",
                open_interest=10,
                multiplier=2,
                iv=0.5,
            ),
        ),
    )


def test_payload_preserves_values_and_never_backdates_receipt() -> None:
    """Round availability forward and retain the contract's financial units."""
    result = build_exposure_request(example_snapshot())
    assert result["available_at"] == EXPECTED_RECEIPT
    assert result["valued_at"] == EXPECTED_RECEIPT
    assert result["spot"] == EXPECTED_PRICE
    assert result["contracts"] == [
        {
            "id": "DERIBIT:0",
            "kind": "call",
            "strike": 100,
            "expiry": 1769904000,
            "iv": 0.5,
            "open_interest": 10,
            "multiplier": 2,
        },
    ]


def test_rejects_naive_or_earlier_valuation() -> None:
    """Reject ambiguous or noncausal request timestamps."""
    original = example_snapshot()
    with pytest.raises(ValueError, match="timezone"):
        _ = build_exposure_request(
            replace(original, timestamp=original.timestamp.replace(tzinfo=None))
        )
    with pytest.raises(ValueError, match="precede"):
        _ = build_exposure_request(
            replace(
                original,
                valuation_time=original.timestamp - timedelta(seconds=2),
            )
        )


def test_converts_valid_rust_response_in_strike_order() -> None:
    """Accept finite sorted side contributions and preserve their values."""
    result = parse_exposure_response(
        {"strikes": [{"strike": 100, "call": 2, "put": -3}]},
    )
    assert len(result) == 1
    assert result[0].strike == EXPECTED_PRICE
    assert result[0].call == EXPECTED_CALL
    assert result[0].put == EXPECTED_PUT
    assert parse_exposure_response({"strikes": []}) == ()


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"strikes": [None]},
        {"strikes": [{"strike": True, "call": 1, "put": -1}]},
        {"strikes": [{"strike": 100, "call": float("nan"), "put": -1}]},
        {"strikes": [{"strike": 100, "call": -1, "put": -1}]},
        {"strikes": [{"strike": 100, "call": 1, "put": 1}]},
        {"strikes": [{"strike": 0, "call": 1, "put": -1}]},
        {"strikes": [{"strike": 100, "call": 1, "put": -1}] * 2},
    ],
)
def test_rejects_untrusted_rust_response(value: object) -> None:
    """Reject malformed, non-finite, invalid-side and duplicate data."""
    with pytest.raises((TypeError, ValueError)):
        _ = parse_exposure_response(value)


def test_native_exposure_calculates_known_at_money_contract() -> None:
    """The native path produces a positive call exposure and no put exposure."""
    result = strike_exposures(example_snapshot())
    assert len(result) == 1
    assert result[0].strike == EXPECTED_PRICE
    assert result[0].call == pytest.approx(54.6113684, rel=1e-8)
    assert result[0].put == 0


def test_native_exposure_rejects_earlier_valuation() -> None:
    """Unavailable snapshots must not enter the calculation."""
    snapshot = example_snapshot()
    with pytest.raises(ValueError, match="Invalid options input"):
        _ = strike_exposures(
            replace(
                snapshot,
                valuation_time=snapshot.timestamp - timedelta(seconds=2),
            )
        )


def test_native_matches_python_for_whole_second_snapshot() -> None:
    """Compare the native result with the existing Python calculation."""
    from gui_calculator.rust_backend import strike_exposures

    snapshot = example_snapshot()
    snapshot = replace(
        snapshot, timestamp=snapshot.timestamp.replace(microsecond=0)
    )
    native = strike_exposures(snapshot)
    reference = python_exposures(snapshot)
    assert len(native) == len(reference) == 1
    assert native[0].strike == reference[0].strike
    assert native[0].call == pytest.approx(reference[0].call, rel=1e-12)
    assert native[0].put == reference[0].put
