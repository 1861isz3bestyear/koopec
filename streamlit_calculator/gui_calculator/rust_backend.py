# Copyright 2026 anchored-vwam-backtest contributors
"""Use Koopec's Rust API for the displayed options strike profile."""

from __future__ import annotations

import math
from itertools import pairwise, starmap
from typing import TYPE_CHECKING, cast

import koopec_calculus
from snapshot_tunnel.options_model import Exposure

if TYPE_CHECKING:
    from datetime import datetime

    from snapshot_tunnel.options_model import Option, Snapshot


def _seconds(value: datetime, *, round_up: bool) -> int:
    """Convert an aware timestamp without backdating receipt availability.

    Returns:
        Unix seconds rounded according to the boundary.

    Raises:
        ValueError: If the timestamp has no timezone.

    """
    if value.utcoffset() is None:
        msg = "Snapshot timestamps must include a timezone."
        raise ValueError(msg)
    timestamp = value.timestamp()
    return math.ceil(timestamp) if round_up else math.floor(timestamp)


def _contract(index: int, option: Option) -> dict[str, object]:
    """Map one option to the Rust API's contract format.

    Returns:
        A JSON-compatible contract.

    """
    return {
        "id": f"{option.exchange}:{index}",
        "kind": option.side,
        "strike": option.strike,
        "expiry": _seconds(option.expiry, round_up=False),
        "iv": option.iv,
        "open_interest": option.open_interest,
        "multiplier": option.multiplier,
    }


def build_exposure_request(snapshot: Snapshot) -> dict[str, object]:
    """Retain the snapshot's availability and valuation cutoffs.

    Returns:
        A JSON-compatible Rust API request.

    Raises:
        ValueError: If the valuation precedes availability.

    """
    available = _seconds(snapshot.timestamp, round_up=True)
    valuation = _seconds(
        snapshot.valuation_time or snapshot.timestamp, round_up=True
    )
    if valuation < available:
        msg = "Valuation cannot precede snapshot availability."
        raise ValueError(msg)
    return {
        "observed_at": available,
        "available_at": available,
        "valued_at": valuation,
        "spot": snapshot.spot,
        "contracts": list(starmap(_contract, enumerate(snapshot.options))),
    }


def _finite(value: object) -> float:
    """Reject non-numeric and non-finite values received from the API.

    Returns:
        A finite floating-point value.

    Raises:
        TypeError: If the value is not numeric.
        ValueError: If the value is not finite.

    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = "Rust API returned a non-numeric exposure."
        raise TypeError(msg)
    try:
        number = float(value)
    except OverflowError as exc:
        msg = "Rust API returned an out-of-range exposure."
        raise ValueError(msg) from exc
    if not math.isfinite(number):
        msg = "Rust API returned a non-finite exposure."
        raise ValueError(msg)
    return number


def _level(value: object) -> Exposure:
    """Validate and convert a single API strike exposure.

    Returns:
        A validated strike exposure.

    Raises:
        TypeError: If the response has an invalid type.
        ValueError: If a numeric value or sign is invalid.

    """
    if not isinstance(value, dict):
        msg = "Rust API returned an invalid strike."
        raise TypeError(msg)
    item = cast("dict[object, object]", value)
    strike = _finite(item.get("strike"))
    call = _finite(item.get("call"))
    put = _finite(item.get("put"))
    if strike <= 0 or call < 0 or put > 0:
        msg = "Rust API returned invalid strike exposure signs."
        raise ValueError(msg)
    return Exposure(strike=strike, call=call, put=put)


def parse_exposure_response(value: object) -> tuple[Exposure, ...]:
    """Validate the response envelope and enforce unique ordered strikes.

    Returns:
        Validated strike exposures in ascending order.

    Raises:
        TypeError: If the response has an invalid type.
        ValueError: If strikes are not uniquely ordered.

    """
    if not isinstance(value, dict):
        msg = "Rust API returned an invalid response."
        raise TypeError(msg)
    payload = cast("dict[object, object]", value)
    strikes = payload.get("strikes")
    if not isinstance(strikes, list):
        msg = "Rust API returned invalid strike exposures."
        raise TypeError(msg)
    levels = tuple(_level(item) for item in cast("list[object]", strikes))
    if any(left.strike >= right.strike for left, right in pairwise(levels)):
        msg = "Rust API returned unordered or duplicate strikes."
        raise ValueError(msg)
    return levels


def strike_exposures(snapshot: Snapshot) -> tuple[Exposure, ...]:
    """Calculate the selected profile through Koopec's local Rust service.

    Returns:
        Validated strike exposures from the Rust API.

    """
    available = _seconds(snapshot.timestamp, round_up=True)
    valuation = _seconds(
        snapshot.valuation_time or snapshot.timestamp, round_up=True
    )
    contracts = [
        (
            f"{option.exchange}:{index}",
            option.side,
            option.strike,
            _seconds(option.expiry, round_up=False),
            option.iv,
            option.open_interest,
            option.multiplier,
        )
        for index, option in enumerate(snapshot.options)
    ]
    strikes = koopec_calculus.strike_exposures(
        available, available, valuation, snapshot.spot, contracts
    )
    return parse_exposure_response({
        "strikes": [
            {"strike": strike, "call": call, "put": put}
            for strike, call, put in strikes
        ],
    })
