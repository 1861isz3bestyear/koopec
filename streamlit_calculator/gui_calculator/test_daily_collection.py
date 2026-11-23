# Copyright 2026 anchored-vwam-backtest contributors
"""Check durable daily scheduling, catch-up and failed collection retries."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import requests
from shared.daily_gex import DailySettings
from snapshot_tunnel.options_model import parse_snapshots

from gui_calculator.daily_collection import run_daily_collection
from gui_calculator.options_collector import main
from gui_calculator.options_gex import EXAMPLE

if TYPE_CHECKING:
    from pathlib import Path


def test_daily_collector_catches_up_and_waits(tmp_path: Path) -> None:
    """A successful catch-up is followed by bounded waits."""
    collect = MagicMock(return_value=4)
    with (
        patch(
            "gui_calculator.daily_collection.load_snapshots", return_value=()
        ),
        patch(
            "gui_calculator.daily_collection.sleep",
            side_effect=KeyboardInterrupt,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        run_daily_collection(
            collect,
            asset="BTC",
            path=tmp_path / "options.sqlite",
            settings=DailySettings(),
        )
    collect.assert_called_once_with()


def test_daily_collector_reuses_saved_receipt(tmp_path: Path) -> None:
    """Restarting retains the published daily observation."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], timestamp=datetime.now(UTC))
    collect = MagicMock(return_value=4)
    with (
        patch(
            "gui_calculator.daily_collection.load_snapshots",
            return_value=(snapshot,),
        ),
        patch(
            "gui_calculator.daily_collection.sleep",
            side_effect=KeyboardInterrupt,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        run_daily_collection(
            collect,
            asset="BTC",
            path=tmp_path / "options.sqlite",
            settings=DailySettings(),
        )
    collect.assert_not_called()


def test_daily_collector_retries_failure(tmp_path: Path) -> None:
    """A failed observation remains due and does not wait an entire day."""
    collect = MagicMock(side_effect=requests.Timeout)
    with (
        patch(
            "gui_calculator.daily_collection.load_snapshots", return_value=()
        ),
        patch(
            "gui_calculator.daily_collection.sleep",
            side_effect=KeyboardInterrupt,
        ) as sleep,
        pytest.raises(KeyboardInterrupt),
    ):
        run_daily_collection(
            collect,
            asset="BTC",
            path=tmp_path / "options.sqlite",
            settings=DailySettings(),
        )
    sleep.assert_called_once_with(60)


def test_daily_cli_dispatch() -> None:
    """The CLI accepts a configurable UTC time and defaults to 08:15."""
    with (
        patch("sys.argv", ["collector", "--daily"]),
        patch("gui_calculator.options_collector.run_daily_collection") as daily,
    ):
        main()
    assert daily.call_args is not None
    assert daily.call_args.kwargs["settings"] == DailySettings()


@pytest.mark.parametrize("invalid", [timedelta(0), timedelta(seconds=-1)])
def test_daily_invalid_limits(invalid: timedelta) -> None:
    """Reject invalid limits before collecting or simulating."""
    with pytest.raises(ValueError, match="positive"):
        _ = DailySettings(snapshot_age=invalid)
