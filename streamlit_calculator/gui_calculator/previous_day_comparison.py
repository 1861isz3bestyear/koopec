# Copyright 2026 anchored-vwam-backtest contributors
"""Compare a live observation with recorded data from the prior UTC day."""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import TYPE_CHECKING

from gui_calculator.snapshot_analytics import select_observation

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot


def previous_day_snapshot(
    current: Snapshot, history: tuple[Snapshot, ...]
) -> Snapshot:
    """Match the requested minute, or the closest observation that UTC day.

    Returns:
        The earliest observation in that minute, or the nearest that day.

    Raises:
        ValueError: If no previous-day observation or valid options exist.

    """
    requested = (current.timestamp.astimezone(UTC) - timedelta(days=1)).replace(
        second=0, microsecond=0
    )
    available = tuple(
        item
        for item in history
        if item.asset == current.asset
        and item.timestamp.astimezone(UTC).date() == requested.date()
    )
    if not available:
        msg = (
            f"No saved {current.asset} snapshots for {requested:%Y-%m-%d} UTC. "
            "Import a recorded options CSV for that day. Historical open "
            "interest and implied volatility cannot be recovered from "
            "Deribit's current-chain API."
        )
        raise ValueError(msg)
    in_minute = tuple(
        item
        for item in available
        if requested <= item.timestamp < requested + timedelta(minutes=1)
    )
    nearest = min(
        in_minute or available,
        key=lambda item: (abs(item.timestamp - requested), item.timestamp),
    )
    return select_observation(
        (nearest,), asset=current.asset, requested=nearest.timestamp
    )
