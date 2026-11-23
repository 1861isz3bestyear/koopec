# Copyright 2026 anchored-vwam-backtest contributors
"""Check causal daily plans, independent filters and executable wall orders."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pandas as pd
import pytest
from shared.candles import Candle
from shared.daily_gex import (
    DailySettings,
    FlowEvidence,
    FlowMode,
    FlowSettings,
    FreshConfirmation,
    PlanStatus,
    WallSettings,
    normalized_slope,
)
from shared.gex_rules import GexHypothesis
from shared.test_strategy import run
from snapshot_tunnel.daily_flow import (
    FlowHistory,
    FlowPoint,
    flow_points,
    recorded_points,
)
from snapshot_tunnel.daily_plans import (
    DailyPlan,
    OptionConfirmation,
    daily_boundary,
    daily_plans,
    plan_from_snapshot,
)
from snapshot_tunnel.options_model import parse_snapshots

from gui_calculator.daily_strategy import PlanReplay, replay_daily, wall_entry
from gui_calculator.options_gex import EXAMPLE

NOW = datetime(2026, 9, 21, 9, tzinfo=UTC)
REPLAY_DAYS = 7


@pytest.fixture
def plan() -> DailyPlan:
    """Provide valid ordered daily walls.

    Returns:
        A positive-gamma plan around the price of 100.

    """
    return DailyPlan(
        available=NOW,
        expires=NOW + timedelta(hours=23),
        gex=10,
        call_wall=110,
        put_wall=90,
        gamma_flip=100,
        call_gex=20,
        put_gex=-10,
    )


@pytest.fixture
def flow() -> FlowHistory:
    """Provide flat OI and volume with positive directional pressure.

    Returns:
        Fully covered minute and five-minute observations.

    """
    minutes = tuple(
        FlowPoint(
            time=NOW + timedelta(minutes=i),
            available=NOW + timedelta(minutes=i),
            value=1,
            auxiliary=3,
        )
        for i in range(-60, 61)
    )
    oi = tuple(
        FlowPoint(
            time=NOW + timedelta(minutes=i),
            available=NOW + timedelta(minutes=i + 1),
            value=100,
        )
        for i in range(-60, 61, 5)
    )
    return FlowHistory(trades=minutes, interest=oi)


def price_bar(
    *, low: float = 90, high: float = 100, opened: float = 95
) -> Candle:
    """Construct a candle touching the lower wall.

    Returns:
        An execution-domain candle.

    """
    return Candle(
        time=pd.Timestamp(NOW), open=opened, high=high, low=low, close=95
    )


def test_flow_windows_and_regression(flow: FlowHistory) -> None:
    """Flat activity is neutral while executed buys remain directional."""
    evidence = flow.at(NOW, FlowSettings())
    assert evidence.trades == pytest.approx(0.5)
    assert evidence.volume_change == 0
    assert evidence.oi_slope == 0
    assert evidence.confirms(1, gex=10, settings=FlowSettings())
    assert evidence.confirms(1, gex=-10, settings=FlowSettings())
    assert not evidence.confirms(-1, gex=10, settings=FlowSettings())
    assert math.isnan(normalized_slope(((0, 10), (1, 11))))
    assert math.isnan(normalized_slope(((0, 0), (1, 0), (2, 0))))
    assert normalized_slope(((0, 100), (5, 105), (10, 110))) == pytest.approx(
        1 / 105
    )


@pytest.mark.parametrize("mode", list(FlowMode))
def test_independent_flow_confirmation(mode: FlowMode) -> None:
    """Combined mode requires both oscillators and respects regime direction."""
    config = FlowSettings(mode=mode)
    good = FlowEvidence(
        trades=0.5, book=0.5, oi_slope=-0.01, volume_change=-0.2
    )
    assert good.confirms(1, gex=10, settings=config)
    assert not good.confirms(1, gex=-10, settings=config)
    assert not replace(good, oi_slope=math.nan).confirms(
        1, gex=10, settings=config
    )
    assert good.confirms(
        1, gex=-10, settings=replace(config, use_oi=False, use_volume=False)
    )
    if mode != FlowMode.TRADES:
        assert not replace(good, book=-0.5).confirms(1, gex=10, settings=config)


def test_missing_stale_and_delayed_flow(flow: FlowHistory) -> None:
    """Missing minutes and unpublished samples never become neutral values."""
    incomplete = replace(
        flow, trades=tuple(point for point in flow.trades if point.time != NOW)
    )
    assert math.isnan(incomplete.at(NOW, FlowSettings()).trades)
    stale = flow.at(NOW + timedelta(hours=2), FlowSettings())
    assert math.isnan(stale.oi_slope)
    assert math.isnan(stale.volume_change)
    delayed = replace(
        flow,
        interest=tuple(
            replace(point, available=NOW + timedelta(days=1))
            for point in flow.interest
        ),
    )
    assert math.isnan(delayed.at(NOW, FlowSettings()).oi_slope)
    gaps = replace(flow, interest=flow.interest[::2])
    assert math.isnan(gaps.at(NOW, FlowSettings()).oi_slope)
    short = replace(flow, interest=flow.interest[11:])
    assert math.isnan(short.at(NOW, FlowSettings()).oi_slope)


def test_book_receipt_and_age(flow: FlowHistory) -> None:
    """Books require actual publication and expire independently of candles."""
    point = FlowPoint(
        time=NOW, available=NOW + timedelta(seconds=1), value=8, auxiliary=2
    )
    history = replace(flow, book=(point,))
    assert math.isnan(history.at(NOW, FlowSettings()).book)
    assert history.at(
        NOW + timedelta(seconds=1), FlowSettings()
    ).book == pytest.approx(0.6)
    assert math.isnan(
        history.at(NOW + timedelta(seconds=11), FlowSettings()).book
    )
    zero = replace(
        flow, book=(replace(point, available=NOW, value=0, auxiliary=0),)
    )
    assert math.isnan(zero.at(NOW, FlowSettings()).book)


@pytest.mark.parametrize("bad", ["NaT", "2026-01-01", "not a time"])
def test_invalid_external_times(bad: str) -> None:
    """Reject missing, naive and malformed timestamps before replay."""
    with pytest.raises((ValueError, TypeError)):
        _ = flow_points(
            pd.DataFrame({"time": [bad], "open_interest": [1]}),
            ("open_interest",),
        )


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_invalid_external_quantities(value: float) -> None:
    """Reject quantities that cannot describe a finite market observation."""
    with pytest.raises(ValueError, match="finite"):
        _ = flow_points(
            pd.DataFrame({"time": [NOW], "open_interest": [value]}),
            ("open_interest",),
        )


def test_external_flow_validation() -> None:
    """Validate receipt order, required fields, duplicates and default delay."""
    frame = pd.DataFrame({"time": [NOW], "open_interest": [100]})
    points = flow_points(frame, ("open_interest",), delay=timedelta(minutes=1))
    assert points[0].available == NOW + timedelta(minutes=1)
    with pytest.raises(ValueError, match="missing"):
        _ = flow_points(frame, ("size",))
    with pytest.raises(ValueError, match="Duplicate"):
        _ = flow_points(pd.concat([frame, frame]), ("open_interest",))
    frame["available_at"] = NOW - timedelta(seconds=1)
    with pytest.raises(ValueError, match="causal"):
        _ = flow_points(frame, ("open_interest",))


def test_plan_schedule_and_expiry() -> None:
    """Delayed receipt activates a plan without retroactive fills."""
    config = DailySettings()
    snapshot = replace(parse_snapshots(EXAMPLE)[0], timestamp=NOW)
    later = replace(snapshot, timestamp=NOW + timedelta(hours=1), spot=100000)
    plans = daily_plans(
        (later, snapshot, replace(snapshot, asset="ETH")), config
    )
    assert len(plans) == 1
    assert plans[0].available == NOW
    assert plans[0].expires == datetime(2026, 9, 22, 8, 15, tzinfo=UTC)
    assert (
        daily_boundary(NOW.replace(hour=8), config).date()
        == (NOW - timedelta(days=1)).date()
    )
    assert (
        daily_boundary(NOW.replace(hour=8, minute=15), config).date()
        == NOW.date()
    )
    assert plan_from_snapshot(replace(snapshot, options=()), config) is None
    assert (
        plan_from_snapshot(
            snapshot, replace(config, expiry_horizon=timedelta(hours=1))
        )
        is None
    )
    inverted = replace(
        snapshot,
        options=tuple(
            replace(option, strike=100) for option in snapshot.options
        ),
    )
    assert plan_from_snapshot(inverted, config) is None


@pytest.mark.parametrize(
    ("gex", "low", "high", "direction"),
    [
        (10, 90, 100, 1),
        (10, 100, 110, -1),
        (-10, 100, 111, 1),
        (-10, 89, 100, -1),
    ],
)
def test_wall_candidates(
    plan: DailyPlan, *, gex: float, low: float, high: float, direction: int
) -> None:
    """Both regimes choose the proper side and stop beyond the entry wall."""
    bar = replace(
        price_bar(low=low, high=high),
        close=(high if direction > 0 else low) if gex < 0 else (low + high) / 2,
    )
    config = DailySettings(walls=WallSettings(stop_offset=None))
    entry = wall_entry(bar, replace(plan, gex=gex), config)
    assert entry is not None
    assert entry.direction == direction
    intrabar = wall_entry(
        bar, replace(plan, gex=gex), replace(config, intrabar=True)
    )
    assert intrabar is not None
    assert math.isfinite(intrabar.price)


def test_ambiguous_and_invalid_wall_entries(plan: DailyPlan) -> None:
    """Do not choose an unknown first touch or enter beyond the stop."""
    assert (
        wall_entry(price_bar(low=85, high=115), plan, DailySettings()) is None
    )
    assert (
        wall_entry(price_bar(), replace(plan, gex=0), DailySettings()) is None
    )
    assert (
        wall_entry(
            price_bar(low=85),
            plan,
            replace(
                DailySettings(),
                intrabar=True,
                walls=WallSettings(stop_offset=0),
            ),
        )
        is not None
    )
    assert (
        wall_entry(replace(price_bar(), close=80), plan, DailySettings())
        is None
    )


def test_replay_rearms_after_leaving_wall(
    plan: DailyPlan, flow: FlowHistory
) -> None:
    """A continuous touch yields one order until price leaves the zone."""
    replay = PlanReplay(
        settings=DailySettings(), flow=flow, plans=(plan,), fresh=()
    )
    bar = price_bar()
    assert (
        replay.evaluate(bar, available_at=bar.time + timedelta(minutes=1))
        is not None
    )
    assert (
        replay.evaluate(bar, available_at=bar.time + timedelta(minutes=1))
        is None
    )
    assert (
        replay.evaluate(
            replace(bar, low=95), available_at=bar.time + timedelta(minutes=1)
        )
        is None
    )
    assert (
        replay.evaluate(bar, available_at=bar.time + timedelta(minutes=1))
        is not None
    )
    assert replay.evaluate(bar, available_at=pd.Timestamp(plan.expires)) is None


def test_fresh_confirmation_blocks_changed_walls(
    plan: DailyPlan, flow: FlowHistory
) -> None:
    """Fresh checks cancel entries while keeping original daily levels."""
    settings = DailySettings(fresh_confirmation=FreshConfirmation())
    replay = PlanReplay(
        settings=settings,
        flow=flow,
        plans=(plan,),
        fresh=(
            OptionConfirmation(
                available=NOW, plan=replace(plan, call_wall=120)
            ),
        ),
    )
    bar = price_bar()
    assert replay.evaluate(bar, available_at=bar.time) is None
    replay.fresh = ()
    assert replay.evaluate(bar, available_at=bar.time) is None
    replay.fresh = (OptionConfirmation(available=NOW, plan=plan),)
    assert replay.evaluate(bar, available_at=bar.time) is not None


def test_replay_missing_flow_blocks_entries(plan: DailyPlan) -> None:
    """Unavailable activity blocks opening, not existing protective orders."""
    replay = PlanReplay(
        settings=DailySettings(),
        flow=FlowHistory(trades=(), interest=()),
        plans=(plan,),
        fresh=(),
    )
    assert replay.evaluate(price_bar(), available_at=pd.Timestamp(NOW)) is None


def daily_candles() -> pd.DataFrame:
    """Create candles touching a real synthetic option wall.

    Returns:
        A minute history with a gap-free execution timeline.

    """
    return pd.DataFrame({
        "time": pd.date_range(NOW, periods=4, freq="min"),
        "anchored_vwap": [78000.0] * 4,
        "anchored_std": [100.0] * 4,
        "open": [78000.0] * 4,
        "high": [80500.0] * 4,
        "low": [78000.0] * 4,
        "close": [80200.0] * 4,
    })


def test_daily_replay_prefix_and_next_open(flow: FlowHistory) -> None:
    """Appending future candles cannot change an earlier execution decision."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], timestamp=NOW)
    data = daily_candles()
    settings = DailySettings()
    result = replay_daily(
        data,
        (snapshot,),
        flow=flow,
        settings=settings,
        interval=timedelta(minutes=1),
    )
    prefix = replay_daily(
        data.iloc[:2],
        (snapshot,),
        flow=flow,
        settings=settings,
        interval=timedelta(minutes=1),
    )
    pd.testing.assert_frame_equal(result.iloc[:2], prefix)
    assert result.loc[0, "options_direction"] == 0
    assert result.loc[1, "options_direction"] == 1
    assert result.loc[1, "options_entry"] == data.loc[1, "open"]
    assert result.loc[1, "options_stop"] == pytest.approx(77844)
    _, trades = run(
        result, strategy_mode="GEX", gex_hypothesis=GexHypothesis.DAILY
    )
    assert len(trades) == 1
    assert trades[0].entry_time == data.loc[1, "time"]


def test_intrabar_uses_prior_flow(flow: FlowHistory) -> None:
    """A future volume surge cannot confirm an earlier intrabar entry."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], timestamp=NOW)
    settings = DailySettings(
        intrabar=True, fresh_confirmation=FreshConfirmation()
    )
    data = daily_candles()
    result = replay_daily(
        data,
        (snapshot,),
        flow=flow,
        settings=settings,
        interval=timedelta(minutes=1),
    )
    altered = replace(
        flow,
        trades=tuple(
            replace(point, auxiliary=1000) if point.time > NOW else point
            for point in flow.trades
        ),
    )
    other = replay_daily(
        data,
        (snapshot,),
        flow=altered,
        settings=settings,
        interval=timedelta(minutes=1),
    )
    assert result.loc[0, "options_direction"] == 1
    pd.testing.assert_series_equal(result.iloc[0], other.iloc[0])


def test_replay_gaps_and_delayed_plan(flow: FlowHistory) -> None:
    """Do not carry a close signal across missing candles or use late plans."""
    data = daily_candles()
    snapshot = replace(
        parse_snapshots(EXAMPLE)[0], timestamp=NOW + timedelta(seconds=30)
    )
    result = replay_daily(
        data,
        (snapshot,),
        flow=flow,
        settings=DailySettings(),
        interval=timedelta(minutes=1),
    )
    assert result.loc[:1, "options_direction"].eq(0).all()
    with pytest.raises(ValueError, match="ordered"):
        _ = replay_daily(
            data.iloc[::-1],
            (snapshot,),
            flow=flow,
            settings=DailySettings(),
            interval=timedelta(minutes=1),
        )
    snapshot = replace(snapshot, timestamp=NOW)
    gap = replay_daily(
        data.iloc[[0, 2, 3]],
        (snapshot,),
        flow=flow,
        settings=DailySettings(),
        interval=timedelta(minutes=1),
    )
    assert gap.loc[1, "options_direction"] == 0


def test_vanished_wall_is_not_replaced_by_older_confirmation(
    plan: DailyPlan, flow: FlowHistory
) -> None:
    """The latest invalid chain cancels a formerly valid wall."""
    replay = PlanReplay(
        settings=DailySettings(fresh_confirmation=FreshConfirmation()),
        flow=flow,
        plans=(plan,),
        fresh=(
            OptionConfirmation(available=NOW, plan=plan),
            OptionConfirmation(available=NOW + timedelta(seconds=1), plan=None),
        ),
    )
    assert (
        replay.evaluate(
            price_bar(), available_at=pd.Timestamp(NOW + timedelta(minutes=1))
        )
        is None
    )


def test_fixed_wall_stop_survives_next_plan() -> None:
    """A new wall cannot move an existing stop or cause a reversal exit."""
    data = daily_candles().assign(open=80000.0, low=80000.0)
    data["options_direction"] = [1, -1, 0, 0]
    data["options_entry"] = [80000, 80000, math.nan, math.nan]
    data["options_stop"] = [79000, 85000, math.nan, math.nan]
    data.loc[2, "low"] = 78000
    _, trades = run(
        data, strategy_mode="GEX", gex_hypothesis=GexHypothesis.DAILY
    )
    assert len(trades) == 1
    assert trades[0].exit_reason == "Stop loss"
    assert trades[0].exit_price == pytest.approx(79000)
    assert trades[0].exit_time == data.loc[2, "time"]


def test_opening_quote_can_execute_before_later_plan_expiry(
    flow: FlowHistory,
) -> None:
    """An observed opening price may execute before later plan expiry."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], timestamp=NOW)
    data = daily_candles()
    settings = DailySettings(intrabar=True, snapshot_age=timedelta(seconds=30))
    result = replay_daily(
        data,
        (snapshot,),
        flow=flow,
        settings=settings,
        interval=timedelta(minutes=1),
    )
    assert result.loc[0, "options_direction"] == 1
    assert result.loc[1:, "options_direction"].eq(0).all()


@pytest.mark.parametrize("fault", ["empty", "price", "alignment"])
def test_replay_rejects_invalid_candles(flow: FlowHistory, fault: str) -> None:
    """Malformed external candles never reach entry evaluation."""
    data = daily_candles()
    if fault == "empty":
        data = data.iloc[:0]
    elif fault == "price":
        data["low"] = -1
    else:
        data["time"] = pd.to_datetime(data["time"], utc=True) + timedelta(
            seconds=1
        )
    with pytest.raises(ValueError, match="Daily GEX requires"):
        _ = replay_daily(
            data,
            parse_snapshots(EXAMPLE),
            flow=flow,
            settings=DailySettings(),
            interval=timedelta(minutes=1),
        )


def test_bad_flow_and_wall_configuration() -> None:
    """Reject nonfinite thresholds and impossible price distances."""
    with pytest.raises(ValueError, match="Flow"):
        _ = FlowSettings(threshold=math.nan)
    with pytest.raises(ValueError, match="Flow"):
        _ = FlowSettings(volume_recent=timedelta(0))
    with pytest.raises(ValueError, match="wall"):
        _ = WallSettings(stop_offset=1)
    with pytest.raises(ValueError, match="wall"):
        _ = WallSettings(momentum_offset=math.inf)
    with pytest.raises(ValueError, match="UTC"):
        _ = DailySettings(refresh=time(8, 15, tzinfo=UTC))


def test_fresh_confirmation_has_independent_age(
    plan: DailyPlan, flow: FlowHistory
) -> None:
    """A daily plan may remain valid after its source is too old to confirm."""
    replay = PlanReplay(
        settings=DailySettings(
            fresh_confirmation=FreshConfirmation(
                maximum_age=timedelta(minutes=1)
            )
        ),
        flow=flow,
        plans=(plan,),
        fresh=(OptionConfirmation(available=NOW, plan=plan),),
    )
    assert (
        replay.evaluate(
            price_bar(), available_at=pd.Timestamp(NOW + timedelta(minutes=1))
        )
        is None
    )
    with pytest.raises(ValueError, match="Fresh confirmation"):
        _ = FreshConfirmation(maximum_age=timedelta(0))


def test_intrabar_touch_after_open_does_not_create_a_fill(
    flow: FlowHistory,
) -> None:
    """A later candle low is not an execution-time quote."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], timestamp=NOW)
    data = daily_candles().assign(open=80200.0)
    result = replay_daily(
        data,
        (snapshot,),
        flow=flow,
        settings=DailySettings(intrabar=True),
        interval=timedelta(minutes=1),
    )
    assert result["options_direction"].eq(0).all()


def test_pending_order_rechecks_executable_price(flow: FlowHistory) -> None:
    """A gap away from the wall cancels the earlier touch signal."""
    data = daily_candles()
    data.loc[1, "open"] = 80500.0
    result = replay_daily(
        data,
        (replace(parse_snapshots(EXAMPLE)[0], timestamp=NOW),),
        flow=flow,
        settings=DailySettings(),
        interval=timedelta(minutes=1),
    )
    assert result.loc[1, "options_direction"] == 0


def test_delayed_baseline_is_usable_only_after_receipt(
    flow: FlowHistory,
) -> None:
    """Historical volume received now can confirm now, never an earlier time."""
    received = NOW + timedelta(seconds=30)
    history = replace(
        flow,
        trades=tuple(
            replace(point, available=max(point.available, received))
            for point in flow.trades
        ),
    )
    assert math.isnan(history.at(NOW, FlowSettings()).volume_change)
    assert history.at(received, FlowSettings()).volume_change == 0


def test_pending_order_rechecks_plan_expiry(
    plan: DailyPlan, flow: FlowHistory
) -> None:
    """An old confirmed trigger cannot execute after its plan expires."""
    replay = PlanReplay(
        settings=DailySettings(), flow=flow, plans=(plan,), fresh=()
    )
    pending = replay.evaluate(price_bar(), available_at=pd.Timestamp(NOW))
    assert pending is not None
    expired = replace(price_bar(opened=90), time=pd.Timestamp(plan.expires))
    assert replay.execution_entry(pending, expired) is None


def test_neutral_cancellation_survives_recovery_until_next_plan(
    plan: DailyPlan, flow: FlowHistory
) -> None:
    """A recovered intraday chain cannot resurrect a cancelled daily setup."""
    tomorrow = NOW + timedelta(days=1)
    next_plan = replace(
        plan, available=tomorrow, expires=tomorrow + timedelta(hours=23)
    )
    replay = PlanReplay(
        settings=DailySettings(walls=WallSettings(neutral_gex=1)),
        flow=flow,
        plans=(plan, next_plan),
        fresh=(
            OptionConfirmation(available=NOW, plan=plan),
            OptionConfirmation(
                available=NOW + timedelta(minutes=1),
                plan=replace(plan, gex=0.5),
            ),
            OptionConfirmation(available=NOW + timedelta(minutes=2), plan=plan),
            OptionConfirmation(available=tomorrow, plan=next_plan),
        ),
    )
    # Cancellation must be observed even while price is away from either wall.
    away = replace(price_bar(), low=99, high=101, open=100, close=100)
    assert (
        replay.evaluate(
            away, available_at=pd.Timestamp(NOW + timedelta(minutes=1))
        )
        is None
    )
    assert replay.cancelled
    assert (
        replay.evaluate(
            price_bar(), available_at=pd.Timestamp(NOW + timedelta(minutes=3))
        )
        is None
    )
    tomorrow_bar = replace(price_bar(), time=pd.Timestamp(tomorrow))
    replay.flow = replace(
        flow,
        trades=tuple(
            replace(
                point,
                time=point.time + timedelta(days=1),
                available=point.available + timedelta(days=1),
            )
            for point in flow.trades
        ),
        interest=tuple(
            replace(
                point,
                time=point.time + timedelta(days=1),
                available=point.available + timedelta(days=1),
            )
            for point in flow.interest
        ),
    )
    assert (
        replay.evaluate(tomorrow_bar, available_at=pd.Timestamp(tomorrow))
        is not None
    )
    assert not replay.cancelled


@pytest.mark.parametrize("gex", [0, -10])
def test_unpublished_regime_change_cannot_cancel_past_entries(
    plan: DailyPlan, flow: FlowHistory, gex: float
) -> None:
    """Neutrality and regime reversals only cancel after actual receipt."""
    replay = PlanReplay(
        settings=DailySettings(),
        flow=flow,
        plans=(plan,),
        fresh=(
            OptionConfirmation(
                available=NOW + timedelta(seconds=1),
                plan=replace(plan, gex=gex),
            ),
        ),
    )
    assert (
        replay.evaluate(price_bar(), available_at=pd.Timestamp(NOW)) is not None
    )
    assert (
        replay.evaluate(
            price_bar(), available_at=pd.Timestamp(NOW + timedelta(seconds=1))
        )
        is None
    )
    assert replay.cancelled


@pytest.mark.parametrize("flip", [80, math.nan, 95])
def test_gamma_flip_must_be_ahead_of_entry(
    plan: DailyPlan, flow: FlowHistory, flip: float
) -> None:
    """A long cannot point away from the flip or use a missing flip."""
    replay = PlanReplay(
        settings=DailySettings(gamma_flip_direction=True),
        flow=flow,
        plans=(replace(plan, gamma_flip=flip),),
        fresh=(),
    )
    assert replay.evaluate(price_bar(), available_at=pd.Timestamp(NOW)) is None
    replay.plans = (replace(plan, gamma_flip=100),)
    assert (
        replay.evaluate(price_bar(), available_at=pd.Timestamp(NOW)) is not None
    )


def test_recorded_flow_requires_receipts() -> None:
    """Imported history must carry actual causal availability metadata."""
    with pytest.raises(ValueError, match="available_at"):
        _ = recorded_points(
            "time,open_interest\n2026-09-21T09:00:00Z,100\n", ("open_interest",)
        )
    with pytest.raises(ValueError, match="causal"):
        _ = recorded_points(
            "time,open_interest,available_at\n2026-09-21T09:00:00Z,100,2026-09-21T08:00:00Z\n",
            ("open_interest",),
        )


def test_repriced_neutrality_cancels_without_another_chain(
    flow: FlowHistory,
) -> None:
    """A single daily chain can become neutral as price/time change."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], timestamp=NOW)
    snapshot = replace(
        snapshot,
        options=tuple(
            (
                replace(option, open_interest=option.open_interest * 0.7)
                if option.side == "call"
                else option
            )
            for option in snapshot.options
        ),
    )
    settings = DailySettings(walls=WallSettings(neutral_fraction=0.05))
    plan = plan_from_snapshot(snapshot, settings)
    assert plan is not None
    assert math.isfinite(plan.gamma_flip)
    replay = PlanReplay(
        settings=settings,
        flow=flow,
        plans=(plan,),
        fresh=(),
        snapshots=(snapshot,),
    )
    bar = Candle(
        time=pd.Timestamp(NOW),
        open=snapshot.spot,
        high=snapshot.spot,
        low=snapshot.spot,
        close=snapshot.spot,
    )
    assert replay.evaluate(bar, available_at=bar.time) is None
    assert not replay.cancelled
    neutral = replace(
        bar,
        time=bar.time + timedelta(minutes=1),
        open=plan.gamma_flip,
        high=plan.gamma_flip,
        low=plan.gamma_flip,
        close=plan.gamma_flip,
    )
    assert replay.evaluate(neutral, available_at=neutral.time) is None
    assert replay.cancelled
    assert math.isfinite(replay.monitored_gex)
    recovered = replace(bar, time=bar.time + timedelta(minutes=2))
    assert replay.evaluate(recovered, available_at=recovered.time) is None
    assert replay.cancelled


@pytest.mark.parametrize(
    ("gex", "expected"),
    [
        (10, PlanStatus.REVERSION),
        (-10, PlanStatus.MOMENTUM),
        (0, PlanStatus.NEUTRAL),
    ],
)
def test_daily_recommendation_requires_current_validity(
    plan: DailyPlan, *, gex: float, expected: PlanStatus
) -> None:
    """Expose neutral/no-trade and cancel/expiry states alongside regimes."""
    active = replace(plan, gex=gex)
    replay = PlanReplay(
        settings=DailySettings(),
        flow=FlowHistory(trades=(), interest=()),
        plans=(active,),
        fresh=(),
        active=active,
    )
    assert replay.status_at(pd.Timestamp(NOW)) == expected
    assert (
        replay.status_at(pd.Timestamp(active.expires)) == PlanStatus.UNAVAILABLE
    )
    replay.cancelled = True
    if gex != 0:
        assert replay.status_at(pd.Timestamp(NOW)) == PlanStatus.CANCELLED


def test_week_replay_resets_plans_without_future_data(
    flow: FlowHistory,
) -> None:
    """Each UTC day publishes its own plan and retains prefix invariance."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], timestamp=NOW)
    snapshot = replace(
        snapshot,
        options=tuple(
            replace(option, expiry=NOW + timedelta(days=30))
            for option in snapshot.options
        ),
    )
    snapshots = tuple(
        replace(snapshot, timestamp=NOW + timedelta(days=day))
        for day in range(REPLAY_DAYS)
    )
    candles = daily_candles()
    frames: list[pd.DataFrame] = []
    for day in range(REPLAY_DAYS):
        frame = candles.copy()
        frame["time"] = pd.to_datetime(candles["time"], utc=True) + timedelta(
            days=day
        )
        frames.append(frame)
    history = replace(
        flow,
        trades=tuple(
            replace(
                point,
                time=point.time + timedelta(days=day),
                available=point.available + timedelta(days=day),
            )
            for day in range(REPLAY_DAYS)
            for point in flow.trades
        ),
        interest=tuple(
            replace(
                point,
                time=point.time + timedelta(days=day),
                available=point.available + timedelta(days=day),
            )
            for day in range(REPLAY_DAYS)
            for point in flow.interest
        ),
    )
    settings = DailySettings()
    result = replay_daily(
        pd.concat(frames, ignore_index=True),
        snapshots,
        flow=history,
        settings=settings,
        interval=timedelta(minutes=1),
    )
    prefix = replay_daily(
        frames[0],
        snapshots[:1],
        flow=flow,
        settings=settings,
        interval=timedelta(minutes=1),
    )
    pd.testing.assert_frame_equal(result.iloc[: len(prefix)], prefix)
    assert result["options_gex_time"].nunique() == REPLAY_DAYS
    assert result["options_direction"].eq(1).sum() == REPLAY_DAYS
