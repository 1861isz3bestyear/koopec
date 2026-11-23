# Copyright 2026 anchored-vwam-backtest contributors
"""Verify OI momentum boundaries and neutral negative-GEX option borders."""

import math
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest
from shared.tunnel import OiConfirmationMode, TunnelSettings
from shared.tunnel_config import parse_tunnel, tunnel_values
from shared.validation import json_object, object_list, object_mapping, string
from snapshot_tunnel.oi_divergence import divergence_series
from snapshot_tunnel.options_model import Exposure, parse_snapshots
from snapshot_tunnel.tunnel_flow import momentum_votes, oi_votes

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.options_profile_chart import wall_levels_chart
from gui_calculator.test_oi_divergence import RATES, market_samples


def test_momentum_votes_need_rates_not_confirmed_pivots() -> None:
    """Warmup and gaps stay unavailable; every ready rate can confirm."""
    samples = market_samples()
    series = divergence_series(samples)
    votes = momentum_votes(series)
    assert all(not vote.calculatable for vote in votes[:14])
    assert [vote.momentum for vote in votes[14:]] == pytest.approx(RATES)
    assert votes[15].calculatable
    assert series.states[15] is None
    for length in range(1, len(samples)):
        assert (
            momentum_votes(divergence_series(samples[:length]))
            == votes[:length]
        )
    gap = replace(
        samples[-1],
        interest=replace(
            samples[-1].interest,
            timestamp=samples[-1].interest.timestamp + timedelta(hours=2),
        ),
    )
    assert not momentum_votes(divergence_series((*samples, gap)))[
        -1
    ].calculatable
    rows = ["time,available_at,open_interest,price"]
    rows.extend(
        f"{point.sample.interest.timestamp.isoformat()},{point.available.isoformat()},"
        f"{point.sample.interest.value},{point.sample.price}"
        for point in series.points
    )
    assert oi_votes("\n".join(rows), mode=OiConfirmationMode.MOMENTUM) == votes


@pytest.mark.parametrize("minimum", [0.0, -1.0, math.inf, math.nan])
def test_momentum_threshold_validation(minimum: float) -> None:
    """Reject invalid thresholds at the configuration boundary."""
    with pytest.raises(ValueError, match="momentum minimum"):
        _ = TunnelSettings(oi_momentum_minimum=minimum)


def test_momentum_threshold_round_trip() -> None:
    """Preserve a chosen strength threshold in exported configurations."""
    settings = TunnelSettings(oi_momentum_minimum=2.5)
    assert parse_tunnel(tunnel_values(settings)) == settings


def test_negative_levels_are_neutral_deduplicated_borders() -> None:
    """A shared put/call strike becomes one orange breakout border."""
    levels = (
        Exposure(strike=100, call=20, put=-40),
        Exposure(strike=110, call=10, put=-30),
    )
    with patch(
        "gui_calculator.options_profile_chart.strike_exposures",
        return_value=levels,
    ):
        chart = wall_levels_chart(
            replace(parse_snapshots(EXAMPLE)[0], spot=100)
        )
    traces = [
        object_mapping(trace)
        for trace in object_list(json_object(chart.to_json())["data"])
    ]
    borders = [
        trace
        for trace in traces
        if string(trace["name"]).startswith("Option border")
    ]
    assert len(borders) == len(levels)
    assert [object_list(trace["y"])[0] for trace in borders] == [100, 110]
    assert all(
        object_mapping(trace["line"])["color"] == "#92400e" for trace in borders
    )
    assert all(
        not string(trace["name"]).startswith(("Call", "Put"))
        for trace in traces
    )


def test_delayed_oi_receipts_delay_dependent_momentum() -> None:
    """A later observation cannot reveal evidence using an unreceived sample."""
    samples = list(market_samples())
    delayed = samples[14].interest.timestamp + timedelta(hours=4)
    samples[14] = replace(samples[14], received=delayed)
    votes = momentum_votes(divergence_series(tuple(samples)))
    assert all(vote.available >= delayed for vote in votes[14:])
