# Copyright 2026 anchored-vwam-backtest contributors
"""Compare the local clock with Bybit's public server clock."""

import sys
from dataclasses import dataclass
from time import time as _wall_time

import requests
from shared.validation import json_object

TIME_URL = "https://api.bybit.com/v5/market/time"


@dataclass(frozen=True, kw_only=True)
class ClockComparison:
    """Estimated clock offset and request duration in seconds."""

    offset: float
    round_trip: float


def compare_clock() -> ClockComparison:
    """Measure the offset using the midpoint of the request.

    Returns:
        Local time minus Bybit time and the round-trip duration.

    Raises:
        TypeError: If the response has an invalid type.
        ValueError: If the response lacks a valid server timestamp.

    """
    start = _wall_time()
    response = requests.get(TIME_URL, timeout=10)
    end = _wall_time()
    response.raise_for_status()
    try:
        timestamp = json_object(response.text).get("time")
    except (ValueError, TypeError) as exc:
        msg = "Bybit returned an invalid time response"
        raise TypeError(msg) from exc
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        msg = "Bybit returned an invalid server timestamp"
        raise TypeError(msg)
    if timestamp <= 0:
        msg = "Bybit returned an invalid server timestamp"
        raise ValueError(msg)
    return ClockComparison(
        offset=(start + end) / 2 - timestamp / 1000,
        round_trip=end - start,
    )


def main() -> None:
    """Print the estimated offset and its timing uncertainty."""
    result = compare_clock()
    _ = sys.stdout.write(
        f"Local clock minus Bybit: {result.offset:+.3f} seconds\n"
    )
    _ = sys.stdout.write(
        f"Request round trip: {result.round_trip:.3f} seconds\n"
    )


if __name__ == "__main__":
    main()
