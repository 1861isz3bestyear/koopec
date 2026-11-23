# Copyright 2026 anchored-vwam-backtest contributors
"""Verify optional GEX gating, oscillator-only funding and raw OI regimes."""

from dataclasses import replace
from datetime import timedelta

import pandas as pd
import pytest
from shared.gex_rules import GexHypothesis
from shared.strategy import backtest
from shared.tunnel import (
    OiConfirmationMode,
    TunnelLevels,
    TunnelQuote,
    TunnelSettings,
)
from shared.tunnel_config import parse_tunnel, tunnel_values
from snapshot_tunnel.local_archive import divergence_votes
from snapshot_tunnel.oi_divergence import DivergenceSettings, divergence_series
from snapshot_tunnel.tunnel_flow import (
    OscillatorObservation,
    TunnelFlow,
    oi_confirmation_series,
    oi_signal_direction,
    oi_votes,
)

from gui_calculator.test_oi_divergence import PRICES, market_samples
from gui_calculator.test_tunnel_strategy import NOW, price_frame
from gui_calculator.tunnel_replay import replay_tunnel


@pytest.mark.parametrize("gex", [-10, 10])
def test_gex_toggle_removes_all_tunnel_prerequisites(gex: int) -> None:
    """Oscillators can authorize trades below flip, far from tunnel borders."""
    flow = TunnelFlow(book=(OscillatorObservation(available=NOW, direction=1),))
    levels = TunnelLevels(gex=gex, lower=200, upper=250, flip=150)
    enabled = TunnelSettings()
    assert flow.entry(
        TunnelQuote(time=NOW, price=100), settings=enabled, levels=levels
    ).direction == (1 if gex < 0 else 0)
    disabled = replace(enabled, use_gex=False)
    assert (
        flow.entry(
            TunnelQuote(time=NOW, price=100), settings=disabled, levels=levels
        ).direction
        == 1
    )
    assert (
        flow.entry(
            TunnelQuote(time=NOW, price=100), settings=disabled, levels=None
        ).direction
        == 1
    )
    assert (
        flow.entry(
            TunnelQuote(time=NOW, price=100), settings=enabled, levels=None
        ).direction
        == 0
    )


def test_oscillator_only_funding() -> None:
    """Public execution funds one full-size leg without GEX insurance."""
    flow = TunnelFlow(
        book=(OscillatorObservation(available=NOW, direction=-1),)
    )
    parameters = TunnelSettings(use_gex=False)
    data = replay_tunnel(price_frame(), (), settings=parameters, flow=flow)
    assert data["options_direction"].tolist() == [0, -1, -1, -1]
    assert data["options_insurance"].isna().all()
    assert "tunnel_confirmation_gex" not in data
    _, trades = backtest(
        data,
        pd.Timestamp(NOW - timedelta(minutes=1)),
        strategy_end_at=pd.Timestamp(NOW + timedelta(minutes=2)),
        initial_capital=1000,
        fee_pct=0.04,
        slippage_bps=2,
        stop_loss_pct=5,
        take_profit_pct=5,
        allow_reentry=True,
        strategy_mode="GEX",
        gex_hypothesis=GexHypothesis.TUNNEL,
        band_sigma=1,
        tunnel_use_gex=False,
    )
    assert len(trades) == 1
    assert trades[0].side == "Short"
    assert trades[0].deposit_size == pytest.approx(1000)
    assert trades[0].entry_price == pytest.approx(110 * 0.9998)


def test_conflicting_missing_and_disabled_confirmations() -> None:
    """Equal quorums, warmup and empty selections never invent a direction."""
    point = OscillatorObservation(available=NOW, direction=1)
    flow = TunnelFlow(book=(point,), margin=(replace(point, direction=-1),))
    parameters = TunnelSettings(use_gex=False, use_margin=True)
    assert flow.direction(NOW, settings=parameters) == 0
    assert flow.direction(NOW, settings=replace(parameters, votes=2)) == 0
    assert (
        flow.direction(NOW, settings=replace(parameters, use_margin=False)) == 1
    )
    assert flow.direction(NOW - timedelta(seconds=1), settings=parameters) == 0
    stale = NOW + parameters.maximum_age + timedelta(seconds=1)
    assert flow.direction(stale, settings=parameters) == 0
    empty = TunnelSettings(use_gex=False, use_book=False, votes=0)
    assert (
        flow.entry(
            TunnelQuote(time=NOW, price=100), settings=empty, levels=None
        ).direction
        == 0
    )
    with pytest.raises(ValueError, match="at least one"):
        _ = TunnelSettings(use_gex=False, votes=0)


def test_new_confirmation_settings_round_trip() -> None:
    """Validate external modes and preserve independent switches."""
    parameters = TunnelSettings(
        use_gex=False, use_oi=True, oi_mode=OiConfirmationMode.CONVERGENCE
    )
    assert parse_tunnel(tunnel_values(parameters)) == parameters
    assert parse_tunnel({}).use_gex
    with pytest.raises(ValueError, match="not a valid"):
        _ = parse_tunnel({"oi_mode": "unknown"})
    with pytest.raises(TypeError, match="boolean"):
        _ = parse_tunnel({"use_gex": "false"})


@pytest.mark.parametrize("sign", [1, -1])
def test_raw_oi_convergence_at_confirmed_price_extremes(sign: int) -> None:
    """Confirm matching raw OI extremes after two right-hand samples."""
    samples = tuple(
        replace(
            sample,
            price=200 + sign * sample.price,
            interest=replace(sample.interest, value=1000 + sign * sample.price),
        )
        for sample in market_samples()
    )
    series = oi_confirmation_series(
        samples, mode=OiConfirmationMode.CONVERGENCE
    )
    assert series.signals
    for signal in series.signals:
        assert signal.state == 0
        assert (
            oi_signal_direction(signal, mode=OiConfirmationMode.CONVERGENCE)
            == sign
        )
        assert (
            oi_signal_direction(signal, mode=OiConfirmationMode.DIVERGENCE) == 0
        )
        assert signal.detected == signal.current.point.available + timedelta(
            hours=2
        )
    rows = ["time,available_at,open_interest,price"]
    for sample in samples:
        stamp = sample.interest.timestamp
        rows.append(
            f"{stamp.isoformat()},{(stamp + timedelta(minutes=1)).isoformat()},"
            f"{sample.interest.value},{sample.price}"
        )
    votes = oi_votes("\n".join(rows), mode=OiConfirmationMode.CONVERGENCE)
    assert all(point.direction == 0 for point in votes[:22])
    assert votes[-1].direction == sign
    prefix = oi_confirmation_series(
        samples[:22], mode=OiConfirmationMode.CONVERGENCE
    )
    assert not prefix.signals


def test_raw_oi_rejects_monotonic_participation() -> None:
    """A continuously rising OI line is not a confirmed OI peak."""
    samples = tuple(
        replace(sample, interest=replace(sample.interest, value=1000 + index))
        for index, sample in enumerate(market_samples())
    )
    assert not oi_confirmation_series(
        samples, mode=OiConfirmationMode.CONVERGENCE
    ).signals


def test_archived_convergence_uses_real_receipts_and_resets_on_gaps() -> None:
    """Keep five-minute raw OI votes at their actual receipts."""
    template = market_samples()[0]
    samples = tuple(
        replace(
            template,
            price=200 + price,
            interest=replace(
                template.interest,
                value=1000 + price,
                timestamp=NOW + timedelta(minutes=5 * index),
            ),
            received=NOW + timedelta(minutes=5 * index, seconds=7),
        )
        for index, price in enumerate((90,) * 146 + PRICES)
    )
    series = divergence_series(
        samples, settings=DivergenceSettings(interval=timedelta(minutes=5))
    )
    votes = divergence_votes(series, mode=OiConfirmationMode.CONVERGENCE)
    assert votes[-1].direction == 1
    assert votes[-1].available == samples[-1].received
    missing = samples[:153] + samples[154:]
    gap = divergence_series(
        missing, settings=DivergenceSettings(interval=timedelta(minutes=5))
    )
    assert (
        divergence_votes(gap, mode=OiConfirmationMode.CONVERGENCE)[-1].direction
        == 0
    )
