# Copyright 2026 anchored-vwam-backtest contributors
"""Replay daily plans, price approaches and point-in-time confirmations."""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import TYPE_CHECKING

import pandas as pd
from shared.candles import Candle, candle_rows
from shared.daily_gex import PlanStatus
from snapshot_tunnel.daily_plans import (
    DailyPlan,
    OptionConfirmation,
    daily_plans,
    plan_from_snapshot,
)
from snapshot_tunnel.options_model import CandleClose, value_snapshot

if TYPE_CHECKING:
    from datetime import timedelta

    from shared.daily_gex import DailySettings
    from snapshot_tunnel.daily_flow import FlowHistory
    from snapshot_tunnel.options_model import Snapshot


@dataclass(frozen=True, kw_only=True)
class WallEntry:
    """Keep a confirmed order's direction, fill and absolute stop together."""

    direction: int
    price: float
    stop: float


def wall_entry(
    bar: Candle, plan: DailyPlan, settings: DailySettings
) -> WallEntry | None:
    """Resolve competing wall touches conservatively before account mutation.

    Returns:
        One candidate, or none if neither or both walls qualify.

    """
    if plan.is_neutral(settings.walls):
        return None
    if plan.gex > 0:
        lower = plan.put_wall * (1 + settings.walls.proximity)
        upper = plan.call_wall * (1 - settings.walls.proximity)
        long = bar.low <= lower and bar.high >= plan.put_wall
        short = bar.high >= upper and bar.low <= plan.call_wall
    else:
        upper = plan.call_wall * (1 + settings.walls.momentum_offset)
        lower = plan.put_wall * (1 - settings.walls.momentum_offset)
        long = (bar.high if settings.intrabar else bar.close) >= upper
        short = (bar.low if settings.intrabar else bar.close) <= lower
    if long == short:
        return None
    direction = 1 if long else -1
    wall = plan.put_wall if long else plan.call_wall
    if plan.gex < 0:
        wall = plan.call_wall if long else plan.put_wall
    price = bar.close
    if settings.intrabar:
        level = lower if (long == (plan.gex > 0)) else upper
        upward = long == (plan.gex < 0)
        price = max(bar.open, level) if upward else min(bar.open, level)
    stop = math.nan
    if settings.walls.stop_offset is not None:
        stop = wall * (1 - direction * settings.walls.stop_offset)
    if math.isfinite(stop) and direction * (price - stop) <= 0:
        return None
    return WallEntry(direction=direction, price=price, stop=stop)


def quote_entry(
    bar: Candle, plan: DailyPlan, settings: DailySettings
) -> WallEntry | None:
    """Recheck the wall at an observed price, never at an inferred touch.

    Returns:
        An executable candidate at the timestamped opening quote.

    """
    quote = replace(bar, high=bar.open, low=bar.open, close=bar.open)
    return wall_entry(quote, plan, settings)


@dataclass(kw_only=True)
class PlanReplay:
    """Own approach state independently of account and position state."""

    settings: DailySettings
    flow: FlowHistory
    plans: tuple[DailyPlan, ...]
    fresh: tuple[OptionConfirmation, ...]
    snapshots: tuple[Snapshot, ...] = ()
    active: DailyPlan | None = None
    armed: bool = True
    cancelled: bool = False
    monitoring_index: int = -1
    monitored_gex: float = math.nan

    def status_at(self, now: pd.Timestamp) -> PlanStatus:
        """Describe whether the fixed daily setup can authorize new entries.

        Returns:
            The recommendation, independent of account position state.

        """
        if (
            self.active is None
            or not self.active.available <= now < self.active.expires
        ):
            return PlanStatus.UNAVAILABLE
        if self.active.is_neutral(self.settings.walls):
            return PlanStatus.NEUTRAL
        if self.cancelled:
            return PlanStatus.CANCELLED
        if self.active.gex > 0:
            return PlanStatus.REVERSION
        return PlanStatus.MOMENTUM

    def evaluate(
        self, bar: Candle, *, available_at: pd.Timestamp
    ) -> WallEntry | None:
        """Apply the plan already published before a candle began.

        Returns:
            A confirmed entry, consuming this approach until price leaves.

        """
        index = (
            bisect_right(self.plans, bar.time, key=lambda item: item.available)
            - 1
        )
        plan = self.plans[index] if index >= 0 else None
        if plan is not None and bar.time >= plan.expires:
            plan = None
        if plan != self.active:
            self.active = plan
            self.armed = True
            self.cancelled = False
            self.monitored_gex = math.nan
        if plan is None or available_at >= plan.expires:
            return None
        self._monitor_regime(plan, available_at)
        price = bar.open if self.settings.intrabar else bar.close
        self._monitor_price(price, available_at=available_at)
        if self.cancelled:
            return None
        candidate = (
            quote_entry(bar, plan, self.settings)
            if self.settings.intrabar
            else wall_entry(bar, plan, self.settings)
        )
        if candidate is None:
            self.armed = True
            return None
        if not self.armed:
            return None
        if not self.confirms(candidate, available_at=available_at):
            return None
        self.armed = False
        return candidate

    def confirms(self, entry: WallEntry, *, available_at: pd.Timestamp) -> bool:
        """Recalculate all filters at the proposed execution timestamp.

        Returns:
            Whether the active plan and independently available evidence agree.

        """
        plan = self.active
        if plan is None or not plan.available <= available_at < plan.expires:
            return False
        self._monitor_regime(plan, available_at)
        self._monitor_price(entry.price, available_at=available_at)
        if self.cancelled:
            return False
        if self.settings.gamma_flip_direction and not (
            math.isfinite(plan.gamma_flip)
            and entry.direction * (plan.gamma_flip - entry.price) > 0
        ):
            return False
        if self.settings.fresh_confirmation and not self._fresh_agrees(
            plan, available_at
        ):
            return False
        evidence = self.flow.at(
            available_at.to_pydatetime(), self.settings.flow
        )
        return evidence.confirms(
            entry.direction, gex=plan.gex, settings=self.settings.flow
        )

    def _monitor_regime(self, plan: DailyPlan, now: pd.Timestamp) -> None:
        """Consume newly available chains and latch cancellation for the day."""
        index = bisect_right(self.fresh, now, key=lambda item: item.available)
        for observation in self.fresh[self.monitoring_index + 1 : index]:
            if observation.available < plan.available:
                continue
            latest = observation.plan
            if (
                latest is None
                or latest.is_neutral(self.settings.walls)
                or latest.gex * plan.gex < 0
            ):
                self.cancelled = True
        self.monitoring_index = index - 1

    def _monitor_price(
        self, price: float, *, available_at: pd.Timestamp
    ) -> None:
        """Reprice only the chain already available at the decision time."""
        if self.active is None or self.cancelled or not self.snapshots:
            return
        index = (
            bisect_right(
                self.snapshots, available_at, key=lambda item: item.timestamp
            )
            - 1
        )
        if index < 0:
            return
        snapshot = value_snapshot(
            self.snapshots[index],
            CandleClose(timestamp=available_at.to_pydatetime(), close=price),
        )
        current = plan_from_snapshot(
            snapshot, self.settings, include_flip=False
        )
        self.monitored_gex = current.gex if current is not None else math.nan
        if (
            current is None
            or current.is_neutral(self.settings.walls)
            or current.gex * self.active.gex < 0
        ):
            self.cancelled = True

    def execution_entry(
        self, pending: WallEntry | None, bar: Candle
    ) -> WallEntry | None:
        """Cancel a pending entry if its price, plan or filters changed.

        Returns:
            A newly priced and confirmed order, or no executable order.

        """
        if pending is None or self.active is None:
            return None
        current = quote_entry(bar, self.active, self.settings)
        if (
            current is None
            or current.direction != pending.direction
            or not self.confirms(current, available_at=bar.time)
        ):
            self.armed = True
            return None
        return current

    def _fresh_agrees(self, plan: DailyPlan, now: pd.Timestamp) -> bool:
        confirmation = self.settings.fresh_confirmation
        index = (
            bisect_right(self.fresh, now, key=lambda item: item.available) - 1
        )
        if index < 0 or confirmation is None:
            return False
        latest = self.fresh[index].plan
        if latest is None or now - latest.available >= confirmation.maximum_age:
            return False
        return (
            now < latest.expires
            and not latest.is_neutral(self.settings.walls)
            and plan.agrees(latest, tolerance=confirmation.wall_drift)
        )


def replay_daily(
    data: pd.DataFrame,
    snapshots: tuple[Snapshot, ...],
    *,
    flow: FlowHistory,
    settings: DailySettings,
    interval: timedelta,
) -> pd.DataFrame:
    """Attach causal execution decisions and daily plan metadata.

    Returns:
        Candle rows with auditable daily metrics and executable order fields.

    Raises:
        ValueError: If candles are not ordered, unique and aligned.

    """
    rows = tuple(candle_rows(data))
    _validate_candles(rows, interval)
    if any(right.time <= left.time for left, right in pairwise(rows)):
        msg = "Daily GEX requires strictly ordered unique candles."
        raise ValueError(msg)
    replay = create_replay(snapshots, flow=flow, settings=settings)
    records: list[dict[str, object]] = []
    pending: WallEntry | None = None
    previous: Candle | None = None
    for bar in rows:
        entry = (
            pending
            if previous is not None and bar.time - previous.time == interval
            else None
        )
        entry = replay.execution_entry(entry, bar)
        decision_at = bar.time if settings.intrabar else bar.time + interval
        candidate = replay.evaluate(bar, available_at=decision_at)
        if settings.intrabar:
            entry = candidate
        records.append({
            **replay_record(
                bar, replay.active, entry, intrabar=settings.intrabar
            ),
            "options_setup_cancelled": replay.cancelled,
            "options_monitored_gex": replay.monitored_gex,
            "options_decision_at": decision_at,
            "options_setup_status": replay.status_at(decision_at).value,
        })
        pending = candidate
        previous = bar
    return pd.concat(
        [data.reset_index(drop=True), pd.DataFrame(records)], axis=1
    )


def replay_record(
    bar: Candle,
    plan: DailyPlan | None,
    entry: WallEntry | None,
    *,
    intrabar: bool,
) -> dict[str, object]:
    """Convert a typed decision to the existing execution/chart boundary.

    Returns:
        Metrics and order fields for one execution bar.

    """
    if (
        entry is not None
        and math.isfinite(entry.stop)
        and not intrabar
        and entry.direction * (bar.open - entry.stop) <= 0
    ):
        entry = None
    return {
        "options_gex": plan.gex if plan else math.nan,
        "options_call_gex": plan.call_gex if plan else math.nan,
        "options_put_gex": plan.put_gex if plan else math.nan,
        "options_absolute_gex": (
            plan.call_gex - plan.put_gex if plan else math.nan
        ),
        "options_max_pain": math.nan,
        "options_call_wall": plan.call_wall if plan else math.nan,
        "options_put_wall": plan.put_wall if plan else math.nan,
        "options_gamma_flip": plan.gamma_flip if plan else math.nan,
        "options_gex_time": plan.available if plan else pd.NaT,
        "options_valid_until": plan.expires if plan else pd.NaT,
        "options_direction": entry.direction if entry else 0,
        "options_entry": (
            (entry.price if intrabar else bar.open) if entry else math.nan
        ),
        "options_stop": entry.stop if entry else math.nan,
        "options_intrabar": float(intrabar),
    }


def _validate_candles(rows: tuple[Candle, ...], interval: timedelta) -> None:
    """Reject malformed prices or timestamps before any trading decisions.

    Raises:
        ValueError: If OHLC or execution interval constraints are violated.

    """
    if not rows or interval.total_seconds() <= 0:
        msg = "Daily GEX requires candles and a positive execution interval."
        raise ValueError(msg)
    for row in rows:
        if not (
            0
            < row.low
            <= min(row.open, row.close)
            <= max(row.open, row.close)
            <= row.high
        ):
            msg = "Daily GEX requires positive consistent OHLC prices."
            raise ValueError(msg)
        if row.time.timestamp() % interval.total_seconds():
            msg = "Daily GEX requires aligned candle open timestamps."
            raise ValueError(msg)


def create_replay(
    snapshots: tuple[Snapshot, ...],
    *,
    flow: FlowHistory,
    settings: DailySettings,
) -> PlanReplay:
    """Build immutable daily plans and causal confirmation history.

    Returns:
        Independent approach state for a chronological replay.

    """
    plans = daily_plans(snapshots, settings)
    fresh = tuple(
        OptionConfirmation(
            available=snapshot.timestamp,
            plan=plan_from_snapshot(snapshot, settings, include_flip=False),
        )
        for snapshot in sorted(snapshots, key=lambda item: item.timestamp)
        if snapshot.asset == "BTC"
    )
    return PlanReplay(
        settings=settings,
        flow=flow,
        plans=plans,
        fresh=fresh,
        snapshots=tuple(
            snapshot
            for snapshot in sorted(snapshots, key=lambda item: item.timestamp)
            if snapshot.asset == "BTC"
        ),
    )
