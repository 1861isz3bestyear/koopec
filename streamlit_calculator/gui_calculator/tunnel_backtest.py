# Copyright 2026 anchored-vwam-backtest contributors
"""Run Snapshot tunnel directly, without a legacy strategy dispatcher."""

from __future__ import annotations

import math
from itertools import pairwise
from typing import TYPE_CHECKING

import koopec_calculus
import pandas as pd
from shared.candles import candle_rows
from shared.gex import OPTIONS_GEX_MODE
from shared.gex_rules import GexHypothesis
from shared.models import Trade
from shared.strategy_data import prepare_backtest
from shared.strategy_runner import validate_trade_timeline
from snapshot_tunnel.validation import unix_microseconds

MAXIMUM_PERCENT = 100

if TYPE_CHECKING:
    from shared.candles import Candle
    from shared.strategy_data import BacktestWindow, PreparedBacktest

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
    bars = tuple(candle_rows(prepared.data))
    marks, fills = koopec_calculus.simulate_snapshot_tunnel(
        _native_bars(bars, prepared),
        settings.initial_capital,
        (
            settings.fee_pct,
            settings.stop_loss_pct,
            settings.take_profit_pct,
            settings.minimum_order_size,
            settings.slippage_bps,
            settings.funding_rate_pct,
            settings.allow_reentry,
        ),
    )
    trades = [_trade(fill, bars) for fill in fills]
    validate_trade_timeline(trades, prepared.window)
    return (
        pd.DataFrame([
            {
                "time": bar.time,
                "equity": equity,
                "position": quantity,
                "close": bar.close,
                "anchored_vwap": bar.anchored_vwap,
            }
            for bar, (equity, quantity) in zip(bars, marks, strict=True)
        ]),
        trades,
    )


def _native_bars(
    bars: tuple[Candle, ...], prepared: PreparedBacktest
) -> list[koopec_calculus.TunnelBarRow]:
    days = (
        prepared.scheduled_days.tolist()
        if prepared.scheduled_days is not None
        else [None] * len(bars)
    )
    return [
        (
            unix_microseconds(bar.time.to_pydatetime()),
            (bar.open, bar.high, bar.low, bar.close),
            (
                int(bar.options_direction)
                if bar.options_direction in {-1, 1}
                else 0
            ),
            (
                bar.options_target_ceiling
                if math.isfinite(bar.options_target_ceiling)
                else None
            ),
            day is not None and day != following,
        )
        for bar, (day, following) in zip(
            bars, pairwise([*days, None]), strict=True
        )
    ]


def _trade(
    fill: koopec_calculus.TunnelTradeRow, bars: tuple[Candle, ...]
) -> Trade:
    (
        capital,
        side,
        entry,
        exit_at,
        paid,
        received,
        quantity,
        pnl,
        rate,
        reason,
    ) = fill
    return Trade(
        deposit_size=capital,
        side=side,
        entry_time=bars[entry].time,
        exit_time=bars[exit_at].time,
        entry_price=paid,
        exit_price=received,
        quantity=quantity,
        pnl=pnl,
        return_pct=rate,
        exit_reason=reason,
    )
