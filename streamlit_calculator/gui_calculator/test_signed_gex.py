# Copyright 2026 anchored-vwam-backtest contributors
"""Exercise signed GEX confirmation, causal replay and frozen TP ceilings."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from shared.gex_rules import GexHypothesis
from shared.strategy import backtest
from shared.test_gex_wall_events import NEGATIVE, NOW, POSITIVE, wall_quote
from shared.tunnel import NegativeGex, OiConfirmationMode, TunnelSettings
from snapshot_tunnel.tunnel_flow import OscillatorObservation, TunnelFlow
from snapshot_tunnel.tunnel_plans import TunnelPlan

from gui_calculator.tunnel_replay import replay_tunnel


@pytest.mark.parametrize("negative", [False, True])
def test_gex_sign_selects_only_its_matching_oi_regime(
    *, negative: bool
) -> None:
    """The manual selector cannot substitute the opposite OI confirmation."""
    price = 110.05 if negative else 109.95
    close = price
    quote = wall_quote(price, previous=(109.9, 110.1, 109.8, close))
    long = OscillatorObservation(available=quote.time, direction=1)
    short = replace(long, direction=-1)
    flow = TunnelFlow(oi=(short,), oi_convergence=(long,))
    settings = TunnelSettings(
        use_book=False,
        use_oi=True,
        oi_mode=(
            OiConfirmationMode.DIVERGENCE
            if negative
            else OiConfirmationMode.CONVERGENCE
        ),
    )
    levels = NEGATIVE if negative else POSITIVE
    expected = 1 if negative else -1
    assert (
        flow.entry(quote, settings=settings, levels=levels).direction
        == expected
    )
    missing = (
        replace(flow, oi_convergence=()) if negative else replace(flow, oi=())
    )
    assert missing.entry(quote, settings=settings, levels=levels).direction == 0


@pytest.mark.parametrize("negative", [False, True])
def test_signed_replay_records_effective_mode_and_never_insures(
    *, negative: bool
) -> None:
    """Audit both regime streams and preserve the independent GEX toggle."""
    price = 110.05 if negative else 109.95
    quote = wall_quote(price, previous=(109.9, 110.1, 109.8, price))
    assert quote.previous is not None
    previous = quote.previous
    data = pd.DataFrame([
        {
            "time": previous.time,
            "open": previous.open,
            "high": previous.high,
            "low": previous.low,
            "close": previous.close,
        },
        {
            "time": NOW,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
        },
    ])
    plan = TunnelPlan(
        available=previous.time.to_pydatetime(),
        expires=quote.time + timedelta(hours=24),
        levels=NEGATIVE if negative else POSITIVE,
    )
    long = OscillatorObservation(available=quote.time, direction=1)
    flow = TunnelFlow(
        oi=(replace(long, direction=-1),),
        oi_convergence=(long,),
    )
    with patch(
        "gui_calculator.tunnel_replay.tunnel_plans", return_value=(plan,)
    ):
        replay = replay_tunnel(
            data,
            (),
            settings=TunnelSettings(use_book=False, use_oi=True),
            flow=flow,
        )
    assert replay["options_direction"].tolist() == [0, 1 if negative else -1]
    assert replay["options_insurance"].isna().all()
    expected_mode = "convergence" if negative else "divergence"
    assert replay["tunnel_oi_mode"].eq(expected_mode).all()
    if negative:
        assert replay["options_target_ceiling"].iloc[-1] < NEGATIVE.flip
        assert "tunnel_confirmation_oi_convergence" in replay
    else:
        assert replay["options_target_ceiling"].isna().all()
        assert "tunnel_confirmation_oi" in replay
    late = replace(plan, available=plan.available + timedelta(seconds=30))
    with patch(
        "gui_calculator.tunnel_replay.tunnel_plans", return_value=(late,)
    ):
        unpublished = replay_tunnel(
            data, (), settings=TunnelSettings(), flow=TunnelFlow()
        )
    assert unpublished["options_direction"].eq(0).all()


@pytest.mark.parametrize("capped", [False, True])
def test_public_negative_long_tp_cap_is_optional_and_frozen(
    *, capped: bool
) -> None:
    """Keep an optional long TP below the original flip across plan changes."""
    start = NOW - timedelta(minutes=1)
    first = TunnelPlan(
        available=start.to_pydatetime(),
        expires=(NOW + timedelta(minutes=1)).to_pydatetime(),
        levels=NEGATIVE,
    )
    following = replace(
        first,
        available=first.expires,
        expires=first.expires + timedelta(hours=24),
        levels=replace(NEGATIVE, flip=120),
    )
    data = pd.DataFrame({
        "time": pd.date_range(start, periods=3, freq="min"),
        "open": [109.9, 110.05, 110.5],
        "high": [110.1, 111, 113],
        "low": [109.8, 110, 110],
        "close": [110.05, 110.5, 112.5],
        "anchored_vwap": 100.0,
        "anchored_std": 1.0,
    })
    with patch(
        "gui_calculator.tunnel_replay.tunnel_plans",
        return_value=(first, following),
    ):
        replay = replay_tunnel(
            data,
            (),
            settings=TunnelSettings(cap_negative_long_tp=capped),
            flow=TunnelFlow(
                book=(OscillatorObservation(available=NOW, direction=1),)
            ),
        )
    _, trades = backtest(
        replay,
        start,
        strategy_end_at=NOW + timedelta(minutes=1),
        initial_capital=1000,
        fee_pct=0.04,
        slippage_bps=2,
        stop_loss_pct=5,
        take_profit_pct=10,
        allow_reentry=True,
        strategy_mode="GEX",
        gex_hypothesis=GexHypothesis.TUNNEL,
        band_sigma=1,
    )
    assert len(trades) == 1
    assert trades[0].deposit_size == pytest.approx(1000)
    if capped:
        assert trades[0].exit_reason == "Take profit"
        assert trades[0].exit_price < NEGATIVE.flip
    else:
        assert trades[0].exit_reason == "End of strategy"
        assert trades[0].exit_price > NEGATIVE.flip


@pytest.mark.parametrize("direction", [-1, 1])
@pytest.mark.parametrize("confirmation", [-1, 0, 1])
def test_negative_gex_requires_directional_oi_convergence(
    direction: int, confirmation: int
) -> None:
    """Strong OI momentum cannot replace matching convergence evidence."""
    quote = wall_quote(105, previous=(105, 106, 104, 105))
    point = OscillatorObservation(available=quote.time, direction=confirmation)
    flow = TunnelFlow(
        book=(replace(point, direction=direction),),
        oi_convergence=(point,),
        oi_momentum=(replace(point, direction=0, momentum=100),),
    )
    settings = TunnelSettings(use_oi=True)
    expected = direction if confirmation == direction else 0
    assert (
        flow.entry(quote, settings=settings, levels=NEGATIVE).direction
        == expected
    )
    for unavailable in (
        replace(point, available=quote.time + timedelta(seconds=1)),
        replace(point, available=quote.time - timedelta(hours=1)),
        replace(point, calculatable=False),
    ):
        assert (
            replace(flow, oi_convergence=(unavailable,))
            .entry(quote, settings=settings, levels=NEGATIVE)
            .direction
            == 0
        )


def test_missing_flip_allows_negative_long_with_percentage_target() -> None:
    """Missing gamma flip permits oscillator entry and leaves TP uncapped."""
    plan = TunnelPlan(
        available=NOW.to_pydatetime(),
        expires=(NOW + timedelta(days=1)).to_pydatetime(),
        levels=NegativeGex(gex=-10),
    )
    data = pd.DataFrame({
        "time": [NOW],
        "open": [110.0],
        "high": [110.0],
        "low": [110.0],
        "close": [110.0],
    })
    with patch(
        "gui_calculator.tunnel_replay.tunnel_plans", return_value=(plan,)
    ):
        replay = replay_tunnel(
            data,
            (),
            settings=TunnelSettings(),
            flow=TunnelFlow(
                book=(OscillatorObservation(available=NOW, direction=1),)
            ),
        )
    assert replay["options_direction"].tolist() == [1]
    assert replay["options_target_ceiling"].isna().all()
