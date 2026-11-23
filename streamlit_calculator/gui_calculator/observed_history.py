# Copyright 2026 anchored-vwam-backtest contributors
"""Recorded GEX observations, independent of fixed trade execution plans."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import pandas as pd
from shared.option_levels import DEFAULT_LEVEL_RANGE, OptionLevelRange
from snapshot_tunnel.gamma_search import search_flips
from snapshot_tunnel.options_model import ranked_walls, strike_exposures

from gui_calculator.ranked_levels import ranked_price_columns

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import timedelta

    from snapshot_tunnel.options_model import Snapshot


@dataclass(frozen=True, kw_only=True)
class OscillatorLine:
    """One oscillator's native receipt timestamps and unavailable values."""

    name: str
    data: pd.DataFrame
    panel: Literal[4, 5, 6, 7]


@dataclass(frozen=True, kw_only=True)
class RecordedCharts:
    """Observed option calculations and independently timed oscillators."""

    gex: pd.DataFrame
    oscillators: tuple[OscillatorLine, ...] = ()


MAX_OBSERVATION_GAP = pd.Timedelta(minutes=7, seconds=30)


def observation_history(
    snapshots: Iterable[Snapshot],
    *,
    level_range: OptionLevelRange = DEFAULT_LEVEL_RANGE,
) -> pd.DataFrame:
    """Value every saved BTC chain at its own receipt time and recorded spot.

    Returns:
        Observed GEX, flip and four ranks without candle resampling or filling.

    """
    rows: list[dict[str, object]] = []
    for snapshot in snapshots:
        if snapshot.asset != "BTC":
            continue
        levels = strike_exposures(snapshot)
        flip = search_flips(snapshot).nearest
        rows.append({
            "time": snapshot.timestamp,
            "options_gex_time": snapshot.timestamp,
            "options_price": snapshot.spot,
            "options_gex": math.fsum(level.net for level in levels),
            "options_call_gex": math.fsum(level.call for level in levels),
            "options_put_gex": math.fsum(level.put for level in levels),
            "options_absolute_gex": math.fsum(
                level.absolute for level in levels
            ),
            "options_gamma_flip": flip if flip is not None else math.nan,
            **ranked_price_columns(
                ranked_walls(
                    levels, spot=snapshot.spot, level_range=level_range
                )
            ),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True)


def visible_observations(
    history: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    maximum_gap: timedelta = MAX_OBSERVATION_GAP,
) -> pd.DataFrame:
    """Clip to the candle window and break lines across missing collections.

    Returns:
        Original receipts plus blank separators; never forward-filled values.

    """
    if history.empty or candles.empty:
        return history.iloc[:0].copy()
    times = pd.to_datetime(candles["time"], utc=True)
    visible = history.loc[history["time"].between(times.min(), times.max())]
    gaps = visible.loc[visible["time"].diff() > maximum_gap].copy()
    if gaps.empty:
        return visible.reset_index(drop=True)
    gaps["time"] -= pd.Timedelta(microseconds=1)
    for column in gaps:
        if column != "time":
            gaps[column] = pd.NaT if column == "options_gex_time" else math.nan
    return (
        pd.concat([visible, gaps], ignore_index=True)
        .sort_values("time")
        .reset_index(drop=True)
    )
