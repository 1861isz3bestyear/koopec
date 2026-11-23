# Copyright 2026 anchored-vwam-backtest contributors
"""Run Snapshot tunnel directly, without a legacy strategy dispatcher."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd
from shared.gex import OPTIONS_GEX_MODE
from shared.gex_rules import GexHypothesis
from shared.spot_execution import SpotRisk
from shared.strategy_data import prepare_backtest
from shared.tunnel_execution import TunnelExecutionSettings, run_tunnel_backtest

MAXIMUM_PERCENT = 100

if TYPE_CHECKING:
    from shared.models import Trade
    from shared.strategy_data import BacktestWindow

    from gui_calculator.settings import CalculatorSettings


def validate_tunnel_run(settings: CalculatorSettings) -> None:
    """Reject unsupported strategies and invalid account inputs.

    Raises:
        ValueError: If the run is not a valid local Snapshot tunnel simulation.

    """
    if (
        settings.strategy_mode != OPTIONS_GEX_MODE
        or settings.gex_hypothesis != GexHypothesis.TUNNEL
        or settings.local_archive is None
    ):
        msg = "Only Snapshot tunnel with a local GEX archive is supported."
        raise ValueError(msg)
    if settings.leverage != 1 or settings.reverse_ticker:
        msg = "Snapshot tunnel requires non-reversed BTC_USDT at 1x."
        raise ValueError(msg)
    if (
        not math.isfinite(settings.initial_capital)
        or settings.initial_capital <= 0
    ):
        msg = "Initial capital must be finite and positive."
        raise ValueError(msg)
    if (
        not math.isfinite(settings.fee_pct)
        or not 0 <= settings.fee_pct < MAXIMUM_PERCENT
    ):
        msg = "Fee percentage must be finite and between 0 and 100."
        raise ValueError(msg)
    if not math.isfinite(settings.funding_rate_pct):
        msg = "Funding rate must be finite."
        raise ValueError(msg)
    values = (
        settings.minimum_order_size,
        settings.stop_loss_pct,
        settings.take_profit_pct,
        settings.slippage_bps,
    )
    if any(not math.isfinite(value) or value < 0 for value in values):
        msg = "Risk, minimum order and slippage must be finite and nonnegative."
        raise ValueError(msg)


def simulate_tunnel(
    data: pd.DataFrame,
    *,
    settings: CalculatorSettings,
    window: BacktestWindow,
) -> tuple[pd.DataFrame, list[Trade]]:
    """Apply the single supported executor to validated chronological candles.

    Returns:
        BTC equity and executed trades for child assets to mirror.

    """
    validate_tunnel_run(settings)
    # The shared timeline/accounting format retains indicator columns. They are
    # unavailable here: no VWAP is calculated or consulted by this strategy.
    candles = data.assign(anchored_vwap=math.nan, anchored_std=math.nan)
    prepared = prepare_backtest(candles, window=window)
    if prepared.data.empty:
        return pd.DataFrame(), []
    return run_tunnel_backtest(
        prepared,
        settings.initial_capital,
        settings=TunnelExecutionSettings(
            risk=SpotRisk(
                fee_pct=settings.fee_pct,
                stop_loss_pct=settings.stop_loss_pct,
                take_profit_pct=settings.take_profit_pct,
                minimum_order_size=settings.minimum_order_size,
                slippage_bps=settings.slippage_bps,
            ),
            allow_reentry=settings.allow_reentry,
            funding_rate_pct=settings.funding_rate_pct,
            use_insurance=False,
        ),
    )
