# Copyright 2026 anchored-vwam-backtest contributors
"""Explicit, minute-specific historical snapshot requests."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from snapshot_tunnel.options_model import Snapshot


def select_observation(
    snapshots: tuple[Snapshot, ...], *, asset: str, requested: datetime
) -> Snapshot:
    """Find an observation in the requested UTC minute without stale fallback.

    Returns:
        The earliest observation within the selected minute.

    Raises:
        ValueError: If the minute or required options sides are unavailable.

    """
    end = requested + timedelta(minutes=1)
    available = tuple(
        item
        for item in snapshots
        if item.asset == asset and requested <= item.timestamp < end
    )
    if not available:
        msg = (
            f"Cannot pull {asset} data for {requested:%Y-%m-%d %H:%M} UTC: "
            "no saved snapshot in this minute. Missing historical spot price, "
            "options chain, open interest and implied volatility. Deribit's "
            "current-chain API cannot reconstruct historical OI or IV. "
            "Import a recorded CSV or select a minute with saved data."
        )
        raise ValueError(msg)
    snapshot = min(available, key=lambda item: item.timestamp)
    for side in ("call", "put"):
        if not any(
            option.side == side and option.open_interest > 0
            for option in snapshot.options
        ):
            msg = f"Missing {asset} {side} options with positive open interest."
            raise ValueError(msg)
    return snapshot
