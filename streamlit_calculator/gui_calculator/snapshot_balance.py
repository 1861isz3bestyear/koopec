# Copyright 2026 anchored-vwam-backtest contributors
"""Describe strike balance and wall distances without directional forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from shared.option_levels import DEFAULT_LEVEL_RANGE, OptionLevelRange
from snapshot_tunnel.options_model import strike_exposures, wall_tunnel

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Exposure, Snapshot

type StrikeRegion = Literal["Below spot", "At spot", "Above spot"]


@dataclass(frozen=True, kw_only=True)
class StrikeBalance:
    """Signed side exposure aggregated relative to observed spot."""

    region: StrikeRegion
    call: float
    put: float


@dataclass(frozen=True, kw_only=True)
class SnapshotBalance:
    """Snapshot measurements, with absent walls represented explicitly."""

    regions: tuple[StrikeBalance, ...]
    call_distance: float | None
    put_distance: float | None
    net_percent: float | None
    extremum_distances: tuple[ExtremumDistance, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ExtremumDistance:
    """A shared ranked strike and its signed percentage move from spot."""

    strike: float
    percent: float


def snapshot_balance(
    snapshot: Snapshot, *, level_range: OptionLevelRange = DEFAULT_LEVEL_RANGE
) -> SnapshotBalance:
    """Calculate side balance and signed wall distances as percentages.

    Returns:
        Measurements at recorded spot; no dealer-position inference.

    """
    levels = strike_exposures(snapshot)
    tunnel = wall_tunnel(levels, spot=snapshot.spot, level_range=level_range)
    groups: tuple[tuple[StrikeRegion, tuple[Exposure, ...]], ...] = (
        ("Below spot", tuple(x for x in levels if x.strike < snapshot.spot)),
        ("At spot", tuple(x for x in levels if x.strike == snapshot.spot)),
        ("Above spot", tuple(x for x in levels if x.strike > snapshot.spot)),
    )
    absolute = sum(level.absolute for level in levels)
    return SnapshotBalance(
        regions=tuple(
            StrikeBalance(
                region=name,
                call=sum(level.call for level in group),
                put=sum(level.put for level in group),
            )
            for name, group in groups
        ),
        call_distance=(
            (tunnel.call / snapshot.spot - 1) * 100
            if tunnel is not None
            else None
        ),
        put_distance=(
            (tunnel.put / snapshot.spot - 1) * 100
            if tunnel is not None
            else None
        ),
        net_percent=(
            sum(level.net for level in levels) / absolute * 100
            if absolute > 0
            else None
        ),
        extremum_distances=tuple(
            ExtremumDistance(
                strike=strike, percent=(strike / snapshot.spot - 1) * 100
            )
            for strike in (tunnel.extrema if tunnel is not None else ())
        ),
    )
