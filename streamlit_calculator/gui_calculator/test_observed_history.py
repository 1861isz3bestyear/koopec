# Copyright 2026 anchored-vwam-backtest contributors
"""Keep chart observations independent of sparse daily execution plans."""

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pandas as pd
import pytest
from market_storage.archive import Archive
from snapshot_tunnel.archive_export import (
    archive_collections,
    archived_snapshot,
)
from snapshot_tunnel.local_archive import (
    load_archive_snapshot_at,
    load_archive_snapshots,
)
from snapshot_tunnel.options_model import (
    grid_exposures,
    net_exposure,
    parse_snapshots,
)

from gui_calculator.local_archive import inspect_archive
from gui_calculator.local_archive_view import archive_gex_history
from gui_calculator.observed_history import (
    observation_history,
    visible_observations,
)
from gui_calculator.options_gex import EXAMPLE
from tests.frontend.archive_fixture import store_chain

if TYPE_CHECKING:
    from pathlib import Path

OBSERVATION_COUNT = 3


def test_archive_keeps_all_five_minute_collections(tmp_path: Path) -> None:
    """Three observations remain visible although execution selects one."""
    first = parse_snapshots(EXAMPLE)[0]
    archive = Archive(path=tmp_path / "inputs.sqlite")
    for index in range(OBSERVATION_COUNT):
        store_chain(
            archive,
            replace(first, spot=first.spot + index * 100),
            stamp=first.timestamp + timedelta(minutes=5 * index),
        )
    source = inspect_archive(archive.path)
    assert len(load_archive_snapshots(source)) == 1
    history = archive_gex_history(source)
    assert len(history) == OBSERVATION_COUNT
    assert history["options_gex"].nunique() == OBSERVATION_COUNT
    assert history["time"].diff().dropna().eq(timedelta(minutes=5)).all()
    assert history["time"].iloc[0] == first.timestamp + timedelta(seconds=2)
    expected = observation_history(
        archived_snapshot(packet)
        for packet in archive_collections(archive.path, asset="BTC")
    )
    pd.testing.assert_frame_equal(
        history[expected.columns],
        expected,
        check_dtype=False,
        check_exact=False,
        rtol=1e-9,
        atol=1e-8,
    )
    assert load_archive_snapshot_at(source, first.timestamp) is None
    profile = load_archive_snapshot_at(
        source, first.timestamp + timedelta(minutes=5)
    )
    assert profile is not None
    assert profile.timestamp == history["time"].iloc[0]
    latest = load_archive_snapshot_at(source, source.end)
    assert latest is not None
    assert latest.timestamp == source.end


def test_visibility_does_not_fill_or_connect_missing_collections() -> None:
    """Retain receipts, clip future data and put a blank break inside a gap."""
    first = parse_snapshots(EXAMPLE)[0]
    snapshots = tuple(
        replace(
            first,
            timestamp=first.timestamp + timedelta(minutes=m),
            spot=first.spot + m,
        )
        for m in (-5, 0, 5, 20, 25)
    )
    history = observation_history(snapshots)
    candles = pd.DataFrame(
        {"time": [first.timestamp, first.timestamp + timedelta(minutes=20)]}
    )
    visible = visible_observations(history, candles)
    real = visible.dropna(subset=["options_gex_time"])
    assert len(real) == OBSERVATION_COUNT
    assert list(real["time"]) == [s.timestamp for s in snapshots[1:-1]]
    missing = visible.loc[visible["options_gex_time"].isna()]
    assert len(missing) == 1
    assert missing["options_gex"].isna().all()
    assert visible_observations(history.iloc[:0], candles).empty
    assert visible_observations(history, candles.iloc[:0]).empty
    assert len(visible_observations(history.iloc[:2], candles)) == 1
    assert observation_history((replace(first, asset="ETH"),)).empty


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0])
def test_grid_preserves_scalar_gamma_model(scale: float) -> None:
    """Vectorization retains the same formula and expired-option handling."""
    first = parse_snapshots(EXAMPLE)[0]
    snapshot = replace(
        first,
        options=(
            *first.options,
            replace(first.options[0], expiry=first.timestamp),
        ),
    )
    prices = tuple(first.spot * scale * x for x in (0.8, 1, 1.2))
    assert grid_exposures(snapshot, prices) == pytest.approx(
        [net_exposure(snapshot, price) for price in prices], rel=1e-12, abs=1e-8
    )
    assert grid_exposures(replace(snapshot, options=()), prices) == (0, 0, 0)
    assert grid_exposures(snapshot, ()) == ()


@pytest.mark.parametrize("iv", [0.0, float("inf")])
def test_grid_rejects_invalid_volatility(iv: float) -> None:
    """Reject invalid volatility instead of plotting made-up values."""
    first = parse_snapshots(EXAMPLE)[0]
    with pytest.raises(ValueError, match="Volatility"):
        _ = grid_exposures(
            replace(first, options=(replace(first.options[0], iv=iv),)),
            (first.spot,),
        )


def test_grid_rejects_nonfinite_exposure() -> None:
    """An overflowed curve cannot become a chart observation."""
    first = parse_snapshots(EXAMPLE)[0]
    with pytest.raises(ValueError, match="Exposure"):
        _ = grid_exposures(
            replace(
                first,
                options=(
                    replace(first.options[0], open_interest=float("inf")),
                ),
            ),
            (first.spot,),
        )
