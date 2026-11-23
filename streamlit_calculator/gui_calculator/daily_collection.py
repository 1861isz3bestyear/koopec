# Copyright 2026 anchored-vwam-backtest contributors
"""Schedule independent daily collection in UTC with bounded failure retries."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from time import sleep
from typing import TYPE_CHECKING

import requests
from snapshot_tunnel.daily_plans import daily_boundary

from gui_calculator.options_store import load_snapshots

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import Literal

    from shared.daily_gex import DailySettings

LOGGER = logging.getLogger(__name__)


def run_daily_collection(
    collect: Callable[[], int],
    *,
    asset: Literal["BTC", "ETH"],
    path: Path,
    settings: DailySettings,
) -> None:
    """Catch up once on startup, then collect once per scheduled UTC day."""
    published = max(
        (
            item.timestamp
            for item in load_snapshots(path)
            if item.asset == asset
        ),
        default=None,
    )
    while True:
        now = datetime.now(UTC)
        boundary = daily_boundary(now, settings)
        if published is not None and published >= boundary:
            remaining = (boundary + timedelta(days=1) - now).total_seconds()
            sleep(min(60.0, max(1.0, remaining)))
            continue
        try:
            count = collect()
        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
            sqlite3.Error,
        ):
            LOGGER.exception("Daily collection failed; retrying in 60 seconds")
            sleep(60)
            continue
        published = datetime.now(UTC)
        LOGGER.info("Daily observation saved: %s contracts", count)
