# Copyright 2026 anchored-vwam-backtest contributors
"""Verify snapshot selection, scenario decisions, causal votes and insurance."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest
from shared.candles import Candle
from shared.gex_rules import GexHypothesis
from shared.order_book import BookLevel, BookSnapshot
from shared.spot_execution import SpotAccount, SpotRisk
from shared.test_strategy import run
from shared.tunnel import (
    TunnelLevels,
    TunnelSettings,
    TunnelState,
    oscillator_vote,
)
from shared.tunnel_execution import TunnelEngine, TunnelExecutionSettings
from snapshot_tunnel.options_model import Snapshot, parse_snapshots
from snapshot_tunnel.tunnel_flow import (
    OscillatorObservation,
    TunnelFlow,
    margin_votes,
    oi_votes,
    saved_book_votes,
)
from snapshot_tunnel.tunnel_plans import (
    TunnelPlan,
    selected_snapshots,
    tunnel_plans,
)

from gui_calculator.app import warn_tunnel_dates
from gui_calculator.options_gex import EXAMPLE
from gui_calculator.settings import CalculatorSettings
from gui_calculator.test_oi_divergence import market_samples
from gui_calculator.tunnel_replay import replay_tunnel

if TYPE_CHECKING:
    from collections.abc import Iterator

    from shared.spot_execution import Side

NOW = datetime(2026, 11, 1, 8, 15, tzinfo=UTC)
LEVELS = TunnelLevels(gex=10, lower=100, upper=110, flip=90)


@pytest.mark.parametrize(
    ("levels", "state"),
    [
        (LEVELS, TunnelState.BOTH),
        (replace(LEVELS, upper=100.2), TunnelState.LONG),
        (replace(LEVELS, flip=105), TunnelState.SHORT),
        (replace(LEVELS, gex=-1), TunnelState.OSCILLATORS),
        (replace(LEVELS, gex=0), TunnelState.INACTIVE),
        (replace(LEVELS, flip=math.nan), TunnelState.INACTIVE),
        (replace(LEVELS, lower=0), TunnelState.INACTIVE),
    ],
)
def test_tunnel_state(levels: TunnelLevels, state: TunnelState) -> None:
    """Classify all three configurable scenarios and reject inactive chains."""
    assert levels.state(TunnelSettings()) == state


@pytest.mark.parametrize(
    ("state", "price", "direction"),
    [
        (TunnelState.LONG, 100, 1),
        (TunnelState.LONG, 110, 0),
        (TunnelState.SHORT, 110, -1),
        (TunnelState.SHORT, 100, 0),
        (TunnelState.BOTH, 110, -1),
        (TunnelState.BOTH, 100, 1),
        (TunnelState.BOTH, 90, 0),
        (TunnelState.BOTH, 105, 0),
    ],
)
def test_reference_border_directions(
    state: TunnelState, price: float, direction: int
) -> None:
    """Match the image's exact border directions, gated by gamma flip."""
    settings = TunnelSettings(state_override=state)
    assert LEVELS.direction(price, settings) == direction
    assert replace(LEVELS, gex=-1).direction(price, settings) == 0


def test_custom_tight_threshold_and_ambiguous_borders() -> None:
    """Configure width and proximity without selecting competing sides."""
    assert LEVELS.state(TunnelSettings(tight_width=0.2)) == TunnelState.LONG
    assert LEVELS.direction(105, TunnelSettings(proximity=0.1)) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"votes": 2},
        {"use_book": False},
        {"insurance_offset": 0.0},
        {"proximity": math.nan},
        {"maximum_age": timedelta(0)},
        {"long_threshold": 30.0},
    ],
)
def test_invalid_settings(
    changes: dict[str, float | int | bool | timedelta],
) -> None:
    """Reject impossible quorum and malformed distances before replay."""
    with pytest.raises(ValueError, match=r"must|thresholds"):
        _ = replace(TunnelSettings(), **changes)


def test_select_nearest_snapshot_per_utc_date() -> None:
    """Prefer earlier ties, handle singleton days and exclude other assets."""
    base = Snapshot(timestamp=NOW, asset="BTC", spot=100, options=())
    early = replace(base, timestamp=NOW - timedelta(minutes=1))
    late = replace(base, timestamp=NOW + timedelta(minutes=1))
    next_day = replace(base, timestamp=NOW + timedelta(days=1, hours=4))
    assert selected_snapshots(
        (late, next_day, early, replace(base, asset="ETH"))
    ) == (early, next_day)
    assert selected_snapshots(()) == ()
    assert tunnel_plans((base,)) == ()


def test_causal_quorum_and_stale_filters() -> None:
    """Count independent enabled votes and never consume future observations."""
    point = OscillatorObservation(available=NOW, direction=1)
    flow = TunnelFlow(
        book=(point,), margin=(point,), oi=(replace(point, direction=-1),)
    )
    settings = TunnelSettings(use_margin=True, use_oi=True, votes=2)
    assert flow.count(1, NOW, settings=settings) == settings.votes
    assert flow.count(-1, NOW, settings=settings) == 1
    assert flow.count(1, NOW - timedelta(seconds=1), settings=settings) == 0
    assert flow.count(1, NOW + timedelta(minutes=11), settings=settings) == 0
    assert oscillator_vote(math.nan, settings) == 0
    assert oscillator_vote(50, settings) == 0
    assert oscillator_vote(40, settings) == -1
    assert saved_book_votes((), settings) == ()


def margin_csv(*, gap: bool = False) -> str:
    """Build real receipt-stamped hourly rates with an optional warmup gap.

    Returns:
        A rising rate series that becomes bullish only after warmup.

    """
    rows = ["time,available_at,growth_rate"]
    for index in range(16):
        stamp = NOW + timedelta(
            hours=index + (2 if gap and index == len(range(16)) - 1 else 0)
        )
        rows.append(f"{stamp.isoformat()},{stamp.isoformat()},{index}")
    return "\n".join(rows)


def test_margin_warmup_and_gaps() -> None:
    """Require all fourteen growth samples and restart warmup across a gap."""
    votes = margin_votes(margin_csv(), TunnelSettings())
    assert all(point.direction == 0 for point in votes[:13])
    assert not any(point.calculatable for point in votes[:13])
    assert votes[13].calculatable
    assert votes[13].direction == 1
    assert (
        margin_votes(margin_csv(gap=True), TunnelSettings())[-1].direction == 0
    )
    with pytest.raises(ValueError, match="available_at"):
        _ = margin_votes("time,annual_rate\n", TunnelSettings())


def test_oi_starts_unknown() -> None:
    """Avoid fabricating OI direction before momentum and swing warmup."""
    content = "time,available_at,open_interest,price\n" + "\n".join(
        f"{(NOW + timedelta(hours=index)).isoformat()},"
        f"{(NOW + timedelta(hours=index, minutes=1)).isoformat()},100,100"
        for index in range(20)
    )
    assert all(point.direction == 0 for point in oi_votes(content))


@pytest.fixture
def fixed_plan() -> Iterator[TunnelPlan]:
    """Isolate expensive options valuation from chronological execution tests.

    Yields:
        A fixed positive-GEX plan available at a known receipt time.

    """
    plan = TunnelPlan(
        available=NOW, expires=NOW + timedelta(hours=24), levels=LEVELS
    )
    with patch(
        "gui_calculator.tunnel_replay.tunnel_plans", return_value=(plan,)
    ):
        yield plan


def price_frame() -> pd.DataFrame:
    """Provide aligned observed quotes above gamma flip.

    Returns:
        Valid candles including the existing indicator boundary columns.

    """
    times = pd.date_range(NOW - timedelta(minutes=1), periods=4, freq="min")
    return pd.DataFrame({
        "time": times,
        "open": 110.0,
        "high": 111.0,
        "low": 109.0,
        "close": 110.0,
        "anchored_vwap": 100.0,
        "anchored_std": 1.0,
    })


def rejection_frame() -> pd.DataFrame:
    """Provide completed lower-wall rejection evidence after plan receipt.

    Returns:
        Opening quotes still close enough to buy above the rejected wall.

    """
    frame = price_frame()
    frame["open"] = 100.05
    frame["high"] = 100.1
    frame["low"] = 99.9
    frame["close"] = 100.05
    return frame


def test_replay_waits_for_receipt_and_votes(fixed_plan: TunnelPlan) -> None:
    """Forbid pre-snapshot entries and record frozen insurance placement."""
    flow = TunnelFlow(book=(OscillatorObservation(available=NOW, direction=1),))
    result = replay_tunnel(
        rejection_frame(), (), settings=TunnelSettings(), flow=flow
    )
    assert result["options_direction"].tolist() == [0, 1, 1, 1]
    assert result["options_insurance"].isna().all()
    assert fixed_plan.available == NOW
    missing = replay_tunnel(
        rejection_frame(), (), settings=TunnelSettings(), flow=TunnelFlow()
    )
    assert missing["options_direction"].eq(0).all()
    assert missing["tunnel_status"].eq("Uncalculatable").all()
    assert not missing["tunnel_oscillators_available"].any()
    assert result["tunnel_status"].tolist() == [
        "Uncalculatable",
        "Calculatable",
        "Calculatable",
        "Calculatable",
    ]
    expired = rejection_frame()
    expired["time"] += timedelta(days=1)
    assert (
        replay_tunnel(expired, (), settings=TunnelSettings(), flow=flow)[
            "options_direction"
        ]
        .eq(0)
        .all()
    )


def engine(*, stop: float = 0, profit: float = 0) -> TunnelEngine:
    """Build two independently funded, fee-free legs for exact PnL assertions.

    Returns:
        An engine using the backtester's actual account and protective exits.

    """
    return TunnelEngine(
        main=SpotAccount(cash=500, fee_pct=0),
        insurance=SpotAccount(cash=500, fee_pct=0),
        settings=TunnelExecutionSettings(
            risk=SpotRisk(
                fee_pct=0,
                stop_loss_pct=stop,
                take_profit_pct=profit,
                minimum_order_size=5,
            )
        ),
    )


def quote(*, low: float = 100, high: float = 100, minutes: int = 0) -> Candle:
    """Build an opening market entry with a frozen insurance trigger at 90.

    Returns:
        A typed executable candle.

    """
    return Candle(
        time=pd.Timestamp(NOW + timedelta(minutes=minutes)),
        open=100,
        high=high,
        low=low,
        close=100,
        options_direction=1,
        options_insurance=90,
    )


def test_insurance_is_armed_after_entry_and_only_fills_once() -> None:
    """Retain the main long and open one additional short below gamma flip."""
    trader = engine()
    trader.process(quote())
    assert trader.main.position is not None
    assert trader.insurance.position is None
    trader.process(quote(low=89, minutes=1))
    assert trader.main.position is not None
    assert trader.insurance.position is not None
    assert trader.insurance.position.price == pytest.approx(90)
    assert trader.insurance.position.side == "Short"
    assert math.isnan(trader.trigger)
    trader.process(quote(low=88, minutes=2))
    assert trader.insurance.position.price == pytest.approx(90)
    trader.close(quote(minutes=3), session=False)
    assert len(trader.main.trades) == len(trader.insurance.trades) == 1
    assert trader.insurance.trades[0].pnl == pytest.approx(-500 / 9)


def test_main_exit_cancels_pending_insurance() -> None:
    """A settled main leg leaves no pending hedge on later falling prices."""
    trader = engine(profit=5)
    trader.process(quote(high=106))
    assert trader.main.position is None
    assert math.isnan(trader.trigger)
    trader.settings = replace(trader.settings, allow_reentry=False)
    trader.process(quote(low=80, minutes=1))
    assert trader.insurance.position is None


def test_stop_priority_and_gap_fill() -> None:
    """Apply existing stop-first protection and adverse opening-gap prices."""
    trader = engine(stop=5, profit=5)
    trader.process(quote(high=106, low=94))
    assert trader.main.trades[0].exit_reason == "Stop loss"
    assert trader.main.trades[0].exit_price == pytest.approx(95)
    trader = engine()
    trader.process(quote())
    trader.process(replace(quote(low=85, minutes=1), open=85, close=85))
    assert trader.insurance.position is not None
    assert trader.insurance.position.price == pytest.approx(85)


def test_public_backtest_dispatch(fixed_plan: TunnelPlan) -> None:
    """Exercise the real public backtester with tunnel signal columns."""
    flow = TunnelFlow(book=(OscillatorObservation(available=NOW, direction=1),))
    frame = replay_tunnel(
        rejection_frame(), (), settings=TunnelSettings(), flow=flow
    )
    equity, trades = run(
        frame, strategy_mode="GEX", gex_hypothesis=GexHypothesis.TUNNEL
    )
    assert fixed_plan.available == NOW
    assert not equity.empty
    assert len(trades) == 1
    assert trades[0].side == "Long"


def test_daily_plan_uses_actual_receipt_and_twenty_four_hour_limit() -> None:
    """Value real saved option chains and replace an older plan at receipt."""
    original = parse_snapshots(EXAMPLE)[0]
    snapshot = replace(
        original,
        timestamp=NOW,
        options=tuple(
            replace(option, expiry=NOW + timedelta(days=7))
            for option in original.options
        ),
    )
    following = replace(snapshot, timestamp=NOW + timedelta(hours=23))
    plans = tunnel_plans((snapshot, following))
    assert plans[0].available == NOW
    assert plans[0].expires == following.timestamp
    assert plans[1].expires == following.timestamp + timedelta(hours=24)


def test_saved_depth_votes_use_book_receipt() -> None:
    """Use stored depth, exclude other assets and prevent future attachments."""
    book = BookSnapshot(
        observed=NOW,
        available=NOW,
        bids=(BookLevel(price=100, quantity=9),),
        asks=(BookLevel(price=101, quantity=1),),
    )
    snapshot = Snapshot(
        timestamp=NOW, asset="BTC", spot=100, options=(), order_book=book
    )
    votes = saved_book_votes(
        (snapshot, replace(snapshot, asset="ETH")), TunnelSettings()
    )
    assert votes == (OscillatorObservation(available=NOW, direction=1),)
    future = replace(
        snapshot, order_book=replace(book, available=NOW + timedelta(seconds=1))
    )
    assert saved_book_votes((future,), TunnelSettings()) == ()


def test_oi_votes_follow_confirmed_pivot_detection() -> None:
    """Translate existing real divergence signals only when detectable."""
    samples = market_samples()
    rows = ["time,available_at,open_interest,price"]
    for sample in samples:
        stamp = sample.interest.timestamp
        receipt = stamp + timedelta(minutes=1)
        rows.append(
            f"{stamp.isoformat()},{receipt.isoformat()},{sample.interest.value},{sample.price}"
        )
    votes = oi_votes("\n".join(rows))
    assert [point.direction for point in votes] == [0] * 26 + [-1]


def test_tunnel_main_side_and_minimum_order_constraints() -> None:
    """Do not arm insurance when an entry is disallowed or unfunded."""
    trader = engine()
    trader.settings = replace(trader.settings, side="Short")
    trader.process(quote())
    assert trader.main.position is None
    trader.settings = replace(
        trader.settings,
        side="Both",
        risk=replace(trader.settings.risk, minimum_order_size=501),
    )
    trader.process(quote())
    assert trader.main.position is None
    assert math.isnan(trader.trigger)


def test_main_downward_stop_precedes_lower_insurance_trigger() -> None:
    """Cancel a hedge when a higher stop necessarily closes its main first."""
    trader = engine(stop=5)
    trader.process(quote(low=80))
    assert trader.main.position is None
    assert trader.insurance.position is None
    assert trader.main.trades[0].exit_price == pytest.approx(95)
    assert math.isnan(trader.trigger)


def test_tunnel_date_warning_respects_strategy_period() -> None:
    """List missing dates only within the selected strategy period."""
    settings = CalculatorSettings(
        start_day=NOW.date(),
        end_day=(NOW + timedelta(days=2)).date(),
        use_full_history_range=False,
        strategy_start_day=NOW.date(),
        strategy_end_day=NOW.date(),
        strategy_end_hour=23,
    )
    data = price_frame()
    data["tunnel_oscillators_available"] = [False, True, True, True]
    outside = data.copy()
    outside["time"] += timedelta(days=1)
    outside["tunnel_oscillators_available"] = False
    with patch("gui_calculator.app.st.warning") as warning:
        warn_tunnel_dates(pd.concat([data, outside]), settings)
    warning.assert_called_once()
    message = str(warning.call_args)
    assert NOW.date().isoformat() in message
    assert "part of date" in message
    assert (NOW + timedelta(days=1)).date().isoformat() not in message


@pytest.mark.parametrize(
    ("value", "direction"), [("-1", -1), ("0", 0), ("1", 1)]
)
def test_bitget_signed_growth_votes(value: str, direction: int) -> None:
    """Use signed loan growth, including falling and flat lending activity."""
    rows = ["time,available_at,growth_rate"]
    received = NOW + timedelta(hours=20)
    for index in range(14):
        observed = NOW + timedelta(hours=index)
        rows.append(f"{observed.isoformat()},{received.isoformat()},{value}")
    votes = margin_votes("\n".join(rows), TunnelSettings())
    assert votes[-1].direction == direction
    assert votes[-1].available == received
    assert votes[-1].calculatable
    flow = TunnelFlow(margin=votes)
    settings = TunnelSettings(use_book=False, use_margin=True)
    assert not flow.available(
        received - timedelta(seconds=1), settings=settings
    )
    assert flow.available(received, settings=settings)
    assert not flow.available(
        received + timedelta(minutes=11), settings=settings
    )


@pytest.mark.parametrize(
    "row",
    [
        "2026-01-01,2026-01-02,1",
        "2026-01-02T00:00:00+00:00,2026-01-01T00:00:00+00:00,1",
        "2026-01-01T00:00:00+00:00,2026-01-02T00:00:00+00:00,nan",
        "2026-01-01T00:00:00+00:00,2026-01-02T00:00:00+00:00,inf",
        "missing,fields",
    ],
)
def test_bitget_growth_rejects_invalid_recordings(row: str) -> None:
    """Reject invalid quantities, missing metadata and noncausal receipts."""
    with pytest.raises(ValueError, match=r".+"):
        _ = margin_votes(
            "time,available_at,growth_rate\n" + row, TunnelSettings()
        )


def test_bitget_growth_rejects_duplicates_and_legacy_config() -> None:
    """Prevent legacy rates or saved RSI settings silently changing meaning."""
    from shared.tunnel_config import parse_tunnel, tunnel_values

    content = margin_csv()
    with pytest.raises(ValueError, match="Duplicate"):
        _ = margin_votes(
            content + "\n" + content.splitlines()[1], TunnelSettings()
        )
    with pytest.raises(ValueError, match="Legacy"):
        _ = parse_tunnel({"use_margin": True})
    with pytest.raises(ValueError, match="Only Bitget"):
        _ = parse_tunnel({"margin_source": "bybit"})
    settings = TunnelSettings(use_margin=True)
    assert parse_tunnel(tunnel_values(settings)) == settings


@pytest.mark.parametrize("gex", [-100.0, 0.0])
def test_replay_retains_nonpositive_gex_calculations(gex: float) -> None:
    """Keep inactive plan analytics observable without authorizing trades."""
    levels = replace(LEVELS, gex=gex)
    plan = TunnelPlan(
        available=NOW, expires=NOW + timedelta(hours=24), levels=levels
    )
    with patch(
        "gui_calculator.tunnel_replay.tunnel_plans", return_value=(plan,)
    ):
        result = replay_tunnel(
            price_frame(),
            (),
            settings=TunnelSettings(),
            flow=TunnelFlow(),
        )
    observed = result.iloc[1:]
    assert observed["options_gex"].eq(gex).all()
    assert observed["options_gamma_flip"].eq(levels.flip).all()
    assert observed["options_call_wall"].eq(levels.upper).all()
    assert observed["options_put_wall"].eq(levels.lower).all()
    assert observed["tunnel_status"].eq("Uncalculatable").all()
    expected_state = (
        TunnelState.OSCILLATORS if gex < 0 else TunnelState.INACTIVE
    )
    assert observed["tunnel_state"].eq(expected_state).all()
    assert result["options_direction"].eq(0).all()


@pytest.mark.parametrize(("side", "expected"), [("Long", 5.0), ("Short", -5.0)])
def test_funding_settles_on_utc_boundaries(side: Side, expected: float) -> None:
    """Funding changes equity only across settlement times."""
    from shared.spot_execution import EntryDecision, ExitDecision
    from shared.tunnel_execution import settle_funding

    trader = engine()
    trader.settings = replace(trader.settings, funding_rate_pct=1.0)
    account = trader.main
    account.open(EntryDecision(side=side, price=100), pd.Timestamp(NOW))
    previous = pd.Timestamp(NOW)
    before = quote(minutes=60)
    settle_funding(trader, previous, before)
    assert account.funding_paid == 0
    after = quote(minutes=8 * 60)
    settle_funding(trader, before.time, after)
    assert account.funding_paid == pytest.approx(expected)
    assert account.mark(100).equity == pytest.approx(500 - expected)
    account.close(ExitDecision(price=100, reason="End of strategy"), after.time)
    assert account.trades[-1].pnl == pytest.approx(-expected)
    assert account.funding_paid == 0
