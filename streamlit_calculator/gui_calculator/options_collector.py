# Copyright 2026 anchored-vwam-backtest contributors
"""Collect options independently of the Streamlit process."""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import time as clock_time
from functools import partial
from pathlib import Path
from time import sleep
from typing import Literal, cast

import requests
from shared.daily_gex import DailySettings
from snapshot_tunnel.options_data import fetch_snapshot

from gui_calculator.daily_collection import run_daily_collection
from gui_calculator.options_store import DEFAULT_OPTIONS_DB, store_snapshot

LOGGER = logging.getLogger(__name__)
MINIMUM_INTERVAL = 60


def collect_once(
    *, asset: Literal["BTC", "ETH"], path: Path = DEFAULT_OPTIONS_DB
) -> int:
    """Persist one complete chain; failures leave no partial observation.

    Returns:
        The number of contracts stored.

    """
    with requests.Session() as session:
        observation = fetch_snapshot(session, asset=asset)
    store_snapshot(
        observation.snapshot,
        observed_at=observation.observed_at.isoformat(),
        path=path,
    )
    return len(observation.snapshot.options)


def main() -> None:
    """Collect periodically, retaining earlier history if a request fails.

    Raises:
        ValueError: If a single requested observation is invalid.
        TypeError: If API field types are invalid.
        KeyError: If required API fields are absent.
        requests.RequestException: If a single requested download fails.
        sqlite3.Error: If a single requested database write fails.

    """
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--asset", choices=("BTC", "ETH"), default="BTC")
    _ = parser.add_argument("--database", type=Path, default=DEFAULT_OPTIONS_DB)
    _ = parser.add_argument("--interval", type=int, default=300)
    _ = parser.add_argument("--once", action="store_true")
    _ = parser.add_argument("--daily", action="store_true")
    _ = parser.add_argument(
        "--daily-at", default="08:15", help="Daily UTC time, HH:MM"
    )
    args = cast("dict[str, object]", vars(parser.parse_args()))
    asset: Literal["BTC", "ETH"] = "ETH" if args["asset"] == "ETH" else "BTC"
    path = Path(str(args["database"]))
    interval = int(str(args["interval"]))
    if interval < MINIMUM_INTERVAL:
        parser.error("--interval must be at least 60 seconds")
    logging.basicConfig(level=logging.INFO)
    if args["daily"] and not args["once"]:
        refresh = clock_time.fromisoformat(str(args["daily_at"]))
        run_daily_collection(
            partial(collect_once, asset=asset, path=path),
            asset=asset,
            path=path,
            settings=DailySettings(refresh=refresh),
        )
        return
    while True:
        try:
            count = collect_once(asset=asset, path=path)
            LOGGER.info("Saved %s contracts for %s", count, asset)
        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
            sqlite3.Error,
        ):
            LOGGER.exception("Collection failed; no partial snapshot published")
            if args["once"]:
                raise
        if args["once"]:
            return
        sleep(interval)


if __name__ == "__main__":
    main()
