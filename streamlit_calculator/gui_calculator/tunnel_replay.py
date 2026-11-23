# Copyright 2026 anchored-vwam-backtest contributors
"""Attach fixed snapshot tunnel signals at observable opening quotes."""

from __future__ import annotations

import math
from bisect import bisect_right
from datetime import timedelta
from typing import TYPE_CHECKING

import pandas as pd
from shared.candles import candle_rows
from shared.strategy_data import validate_prices
from shared.tunnel import (
    TunnelLevels,
    TunnelQuote,
    long_target_ceiling,
    regime_state,
)
from snapshot_tunnel.options_model import strike_exposures
from snapshot_tunnel.tunnel_plans import selected_snapshots, tunnel_plans

from gui_calculator.ranked_levels import ranked_price_columns

_MINUTE = timedelta(minutes=1)
from gui_calculator.rust_backend import ranked_walls

if TYPE_CHECKING:
    from shared.candles import Candle
    from shared.tunnel import TunnelSettings
    from snapshot_tunnel.options_model import Snapshot
    from snapshot_tunnel.tunnel_flow import TunnelFlow
    from snapshot_tunnel.tunnel_plans import TunnelPlan


def replay_tunnel(
    data: pd.DataFrame,
    snapshots: tuple[Snapshot, ...],
    *,
    settings: TunnelSettings,
    flow: TunnelFlow,
    interval: timedelta = _MINUTE,
) -> pd.DataFrame:
    """Evaluate fixed plans and fresh filters using only each opening quote.

    Returns:
        Executable directions, insurance triggers and auditable plan metadata.

    """
    validate_prices(data)
    plans = tunnel_plans(snapshots, level_range=settings.level_range)
    rank_prices = {
        snapshot.timestamp: ranked_price_columns(
            ranked_walls(
                strike_exposures(snapshot),
                spot=snapshot.spot,
                level_range=settings.level_range,
            )
        )
        for snapshot in selected_snapshots(snapshots)
    }
    missing_prices: dict[str, float] = dict.fromkeys(
        ("options_call_1", "options_call_2", "options_put_1", "options_put_2"),
        math.nan,
    )
    records: list[dict[str, object]] = []
    previous: Candle | None = None
    for bar in candle_rows(data):
        index = (
            bisect_right(plans, bar.time, key=lambda item: item.available) - 1
        )
        plan = plans[index] if index >= 0 else None
        if plan is not None and bar.time >= plan.expires:
            plan = None
        effective = settings.for_gex(plan.levels.gex if plan else None)
        decision = flow.entry(
            TunnelQuote(
                time=bar.time.to_pydatetime(),
                price=bar.open,
                interval=interval,
                previous=(
                    previous
                    if plan
                    and previous is not None
                    and previous.time >= plan.available
                    else None
                ),
            ),
            settings=effective,
            levels=plan.levels if plan else None,
        )
        direction = decision.direction
        records.append({
            **_plan_columns(plan, settings),
            **flow.confirmations(bar.time.to_pydatetime(), settings=effective),
            **(
                {"tunnel_confirmation_gex": decision.gex_direction}
                if settings.use_gex
                else {}
            ),
            **(
                rank_prices.get(plan.available, missing_prices)
                if plan is not None
                else missing_prices
            ),
            "options_direction": direction,
            "options_entry": bar.open if direction else math.nan,
            "options_stop": math.nan,
            "options_intrabar": 0.0,
            "options_insurance": math.nan,
            "options_target_ceiling": (
                long_target_ceiling(plan.levels, settings)
                if plan
                and settings.use_gex
                and plan.levels.gex < 0
                and direction == 1
                else math.nan
            ),
            "tunnel_oi_mode": effective.oi_mode.value,
            "tunnel_votes": decision.votes,
            "tunnel_gex_enabled": settings.use_gex,
            "tunnel_oscillators_available": (
                len(
                    flow.available(bar.time.to_pydatetime(), settings=effective)
                )
                >= settings.votes
            ),
            "tunnel_status": (
                "Calculatable" if decision.calculatable else "Uncalculatable"
            ),
        })
        previous = bar
    return pd.concat(
        [data.reset_index(drop=True), pd.DataFrame(records)], axis=1
    )


def _plan_columns(
    plan: TunnelPlan | None, settings: TunnelSettings
) -> dict[str, object]:
    """Serialize regime and optional positive entry structure for the audit.

    Returns:
        Plan fields with missing values confined to the dataframe boundary.

    """
    structure = (
        plan.levels
        if plan is not None and isinstance(plan.levels, TunnelLevels)
        else None
    )
    flip = plan.levels.flip if plan is not None else None
    return {
        "options_gex": plan.levels.gex if plan else math.nan,
        "options_gamma_flip": flip if flip is not None else math.nan,
        "options_call_wall": structure.upper if structure else math.nan,
        "options_put_wall": structure.lower if structure else math.nan,
        "options_gex_time": plan.available if plan else pd.NaT,
        "options_valid_until": plan.expires if plan else pd.NaT,
        "tunnel_state": int(regime_state(plan.levels, settings)) if plan else 0,
    }
