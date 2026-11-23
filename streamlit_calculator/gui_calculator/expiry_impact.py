# Copyright 2026 anchored-vwam-backtest contributors
"""Calculate exposure removed by an options expiry without UI dependencies."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from snapshot_tunnel.options_model import (
    Snapshot,
    gamma_flips,
    net_exposure,
    strike_exposures,
    wall_tunnel,
)

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class ExpiryImpact:
    """Constant-time removal scenario for one expiration."""

    before: Snapshot
    remaining: Snapshot
    expiring: Snapshot
    expiry: datetime

    @property
    def absolute_share(self) -> float:
        """Fraction of absolute gamma exposure removed."""
        total = sum(level.absolute for level in strike_exposures(self.before))
        removed = sum(
            level.absolute for level in strike_exposures(self.expiring)
        )
        return removed / total if total else 0.0


def analyze_expiry(snapshot: Snapshot, *, expiry: datetime) -> ExpiryImpact:
    """Partition an active snapshot without changing spot, IV, OI or time.

    Returns:
        Exposure partitions for the selected expiry.

    Raises:
        ValueError: If the expiry is absent or already expired.

    """
    if expiry <= (snapshot.valuation_time or snapshot.timestamp) or not any(
        option.expiry == expiry for option in snapshot.options
    ):
        msg = "Select an upcoming expiry present in the snapshot."
        raise ValueError(msg)
    return ExpiryImpact(
        before=snapshot,
        remaining=replace(
            snapshot,
            options=tuple(o for o in snapshot.options if o.expiry != expiry),
        ),
        expiring=replace(
            snapshot,
            options=tuple(o for o in snapshot.options if o.expiry == expiry),
        ),
        expiry=expiry,
    )


def wall_label(snapshot: Snapshot, *, side: Literal["call", "put"]) -> str:
    """Format the upper or lower ranked-strike tunnel boundary.

    Returns:
        Wall price, or unavailable when there is no ranked exposure.

    """
    tunnel = wall_tunnel(strike_exposures(snapshot), spot=snapshot.spot)
    if tunnel is None:
        return "Unavailable"
    price = tunnel.call if side == "call" else tunnel.put
    return f"${price:,.2f}"


def expiry_outlook(impact: ExpiryImpact) -> str:
    """Describe removal effects using the same flip search for both chains.

    Returns:
        Compact scenario text suitable for the analysis chart.

    """
    prices = tuple(
        impact.before.spot * (0.8 + index * 0.001) for index in range(401)
    )
    flips: list[str] = []
    for chain in (impact.before, impact.remaining):
        roots = gamma_flips(chain, prices)
        nearest = min(
            roots,
            key=lambda price: (abs(price - chain.spot), price),
            default=None,
        )
        flips.append(
            f"${nearest:,.2f}" if nearest is not None else "No crossing"
        )
    before = net_exposure(impact.before, impact.before.spot)
    after = net_exposure(impact.remaining, impact.before.spot)
    return (
        "Expiry outlook · current → without selected expiry"
        f"<br>Put wall: {wall_label(impact.before, side='put')} → "
        f"{wall_label(impact.remaining, side='put')}"
        f" · Call wall: {wall_label(impact.before, side='call')} → "
        f"{wall_label(impact.remaining, side='call')}"
        f"<br>Net GEX: ${before:+,.0f} → ${after:+,.0f} / 1% move"
        f" (change ${after - before:+,.0f})"
        f"<br>Nearest gamma flip: {flips[0]} → {flips[1]}"
        " · search: spot ±20%"
        "<br>Fixed spot, IV, time and surviving OI; rolls and new trades "
        "can change this scenario."
    )
