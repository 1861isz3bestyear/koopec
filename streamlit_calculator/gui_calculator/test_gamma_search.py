# Copyright 2026 anchored-vwam-backtest contributors
"""Verify full-chain searches beyond the former spot window."""

from dataclasses import replace

import pytest
from snapshot_tunnel.gamma_search import (
    FlipResult,
    FlipSearch,
    FlipStatus,
    compare_flip_searches,
    search_flips,
)
from snapshot_tunnel.options_model import net_exposure, parse_snapshots

from gui_calculator.options_gex import EXAMPLE


def test_full_range_finds_distant_crossing() -> None:
    """Find a real repriced crossing outside the old twenty-percent range."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], spot=40000)
    bounded = search_flips(snapshot, search=FlipSearch(width=0.2))
    result = search_flips(snapshot)
    assert bounded.status is FlipStatus.NOT_FOUND
    assert result.status is FlipStatus.FOUND
    assert result.nearest is not None
    assert result.nearest > bounded.upper
    assert net_exposure(snapshot, result.nearest) == pytest.approx(0, abs=1e-4)
    assert result.lower == snapshot.spot
    assert result.upper == max(option.strike for option in snapshot.options)
    sensitivity = compare_flip_searches(snapshot, result)
    assert sensitivity.density_agrees
    assert sensitivity.range_agrees


def test_grid_preserves_strikes_and_includes_spot() -> None:
    """Preserve irregular strikes and avoid duplicate prices."""
    search = FlipSearch(intervals=2)
    assert search.prices(100, strikes=(10, 37, 90)) == (10, 37, 55, 90, 100)
    assert search.prices(100, strikes=(100,)) == (100,)
    assert search.prices(100) == (100,)


@pytest.mark.parametrize("width", [0, -0.2, 1, float("nan")])
def test_invalid_width(width: float) -> None:
    """Reject invalid optional spot windows."""
    with pytest.raises(ValueError, match="width"):
        _ = FlipSearch(width=width)


@pytest.mark.parametrize("intervals", [True, 0, 10001])
def test_invalid_intervals(intervals: int) -> None:
    """Reject unsupported grid sizes."""
    with pytest.raises(ValueError, match="intervals"):
        _ = FlipSearch(intervals=intervals)


@pytest.mark.parametrize("price", [0, -1, float("inf"), float("nan")])
def test_invalid_prices(price: float) -> None:
    """Reject nonpositive and nonfinite boundary data."""
    with pytest.raises(ValueError, match="spot"):
        _ = FlipSearch().prices(price)
    with pytest.raises(ValueError, match="strikes"):
        _ = FlipSearch().prices(100, strikes=(price,))


def test_nearest_tie_and_one_sided_chain() -> None:
    """Break ties downward and avoid manufacturing roots for call-only data."""
    result = FlipResult(
        search=FlipSearch(), spot=100, lower=50, upper=150, roots=(110, 90)
    )
    assert result.nearest == min(result.roots)
    snapshot = parse_snapshots(EXAMPLE)[0]
    calls = replace(
        snapshot, options=tuple(o for o in snapshot.options if o.side == "call")
    )
    result = search_flips(calls)
    assert result.nearest is None
    assert result.status is FlipStatus.NOT_FOUND
