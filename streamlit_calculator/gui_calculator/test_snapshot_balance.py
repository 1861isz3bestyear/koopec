# Copyright 2026 anchored-vwam-backtest contributors
"""Verify snapshot balance measurements and their chart representation."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from shared.validation import json_object, object_list, object_mapping
from snapshot_tunnel.options_model import Exposure, parse_snapshots

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.snapshot_balance_view import (
    snapshot_balance,
    snapshot_balance_chart,
)


def test_balance_preserves_strike_regions_and_signed_distances() -> None:
    """Measure uneven walls without translating proximity into probability."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], spot=100)
    levels = (
        Exposure(strike=80, call=0, put=-60),
        Exposure(strike=100, call=10, put=-10),
        Exposure(strike=110, call=40, put=-20),
    )
    with patch(
        "gui_calculator.snapshot_balance.strike_exposures",
        return_value=levels,
    ):
        result = snapshot_balance(snapshot)
        chart = snapshot_balance_chart(snapshot)
    assert result.put_distance == pytest.approx(-20)
    assert result.call_distance == pytest.approx(10)
    assert [
        (level.strike, level.percent) for level in result.extremum_distances
    ] == [(110, pytest.approx(10))]
    assert result.net_percent == pytest.approx(-40 / 140 * 100)
    assert [(r.call, r.put) for r in result.regions] == [
        (0, -60),
        (10, -10),
        (40, -20),
    ]
    traces = object_list(json_object(chart.to_json())["data"])
    assert len(traces) == len(("calls", "puts", "distances", "balance"))
    assert object_mapping(traces[0])["y"] == [0, 10, 40]
    assert object_mapping(traces[1])["y"] == [-60, -10, -20]
    assert object_mapping(traces[2])["x"] == [
        "Put wall",
        "Call wall",
        "Extremum $110.00",
    ]
    assert object_mapping(traces[2])["y"] == pytest.approx([-20, 10, 10])


@pytest.mark.parametrize("side", ["call", "put", "zero"])
def test_balance_missing_sides_and_zero_exposure(side: str) -> None:
    """Unavailable walls and undefined ratios do not become invented zeros."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    snapshot = replace(
        snapshot,
        options=tuple(
            replace(option, open_interest=0) if side == "zero" else option
            for option in snapshot.options
            if side in {"zero", option.side}
        ),
    )
    result = snapshot_balance(snapshot)
    assert not result.extremum_distances
    if side == "zero":
        assert result.call_distance is None
        assert result.put_distance is None
        assert result.net_percent is None
    elif side == "call":
        assert result.call_distance is not None
        assert result.put_distance is not None
        assert result.call_distance >= result.put_distance
        assert result.net_percent == pytest.approx(100)
    else:
        assert result.call_distance is not None
        assert result.put_distance is not None
        assert result.call_distance >= result.put_distance
        assert result.net_percent == pytest.approx(-100)
    _ = snapshot_balance_chart(snapshot).to_json()


@pytest.mark.parametrize("spot", [79_000, 80_000, 83_000])
def test_extremum_distances_reach_wall_distance_chart(spot: float) -> None:
    """Plot each shared strike, including those coinciding with a wall."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    snapshot = replace(
        snapshot,
        spot=spot,
        options=tuple(
            replace(snapshot.options[0], strike=strike, side=side)
            for strike in (80_000, 82_000)
            for side in ("call", "put")
        ),
    )
    balance = snapshot_balance(snapshot)
    expected = [(strike / spot - 1) * 100 for strike in (80_000, 82_000)]
    assert [level.strike for level in balance.extremum_distances] == [
        80_000,
        82_000,
    ]
    assert [
        level.percent for level in balance.extremum_distances
    ] == pytest.approx(expected)
    traces = object_list(
        json_object(snapshot_balance_chart(snapshot).to_json())["data"]
    )
    distances = object_mapping(traces[2])
    assert distances["x"] == [
        "Put wall",
        "Call wall",
        "Extremum $80,000.00",
        "Extremum $82,000.00",
    ]
    assert distances["y"] == pytest.approx([*expected, *expected])
