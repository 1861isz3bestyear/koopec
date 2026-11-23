# Copyright 2026 anchored-vwam-backtest contributors
"""Tests for the public Bybit clock diagnostic."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from check_bybit_time import compare_clock


class TimeResponse:
    """A successful response with a controlled JSON payload."""

    payload: object

    def __init__(self, payload: object) -> None:
        """Store the controlled payload."""
        self.payload = payload

    def json(self) -> object:
        """Return the test payload.

        Returns:
            The controlled response payload.

        """
        return self.payload

    def raise_for_status(self) -> None:
        """Represent a successful HTTP status."""


def test_clock_offset_uses_request_midpoint() -> None:
    """Estimate offset from the midpoint rather than either endpoint."""
    response = TimeResponse({"time": 100_000})
    values = iter([101.0, 103.0])
    with (
        patch("check_bybit_time.requests.get", return_value=response),
        patch(
            "check_bybit_time.time", SimpleNamespace(time=lambda: next(values))
        ),
    ):
        result = compare_clock()
    assert result.offset == pytest.approx(2.0)
    assert result.round_trip == pytest.approx(2.0)


@pytest.mark.parametrize("payload", [None, {}, {"time": True}, {"time": -1}])
def test_rejects_invalid_server_time(payload: object) -> None:
    """Do not interpret malformed external data as a clock measurement."""
    response = TimeResponse(payload)
    with (
        patch("check_bybit_time.requests.get", return_value=response),
        pytest.raises((TypeError, ValueError), match="invalid"),
    ):
        _ = compare_clock()
