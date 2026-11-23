# Copyright 2026 anchored-vwam-backtest contributors
"""Provide metrics behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from shared.models import Trade


def summarize(
    equity: pd.DataFrame, trades: list[Trade], initial_capital: float
) -> dict[str, float]:
    """Calculate account-performance metrics from equity and closed trades.

    Returns:
        The computed result.

    """
    final_equity = (
        float(equity["equity"].astype(float).iloc[-1])
        if not equity.empty
        else initial_capital
    )
    # Daily returns make annualization independent of the candle interval.
    daily: pd.Series[float] = (
        equity.set_index(pd.to_datetime(equity["time"], utc=True))["equity"]
        .astype(float)
        .resample("1D")
        .last()
        .ffill()
        if not equity.empty
        else pd.Series(dtype=float)
    )
    returns = (
        daily.pct_change()
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .astype(float)
    )
    peaks = equity["equity"].astype(float).cummax().clip(lower=initial_capital)
    drawdown = equity["equity"].astype(float) / peaks - 1
    wins = [trade for trade in trades if trade.pnl > 0]
    return {
        "Final equity": final_equity,
        "Net return": (final_equity / initial_capital - 1) * 100,
        "Max drawdown": (
            float(drawdown.min() * 100) if not drawdown.empty else 0.0
        ),
        "Trades": float(len(trades)),
        "Win rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "Best trade": max((trade.return_pct for trade in trades), default=0.0),
        "Worst trade": min((trade.return_pct for trade in trades), default=0.0),
        "Sharpe": (
            (float(returns.mean()) / float(returns.std())) * 365**0.5
            if len(returns) > 1 and returns.std()
            else 0.0
        ),
    }


def format_metric(
    value: float, metric: str, equity_currency: str = "USDT"
) -> str:
    """Format one named performance metric for display.

    Returns:
        The computed result.

    """
    if metric == "Final equity":
        return f"{value:,.8f} {equity_currency}"
    if metric == "Trades":
        return f"{int(value)}"
    if metric == "Sharpe":
        return f"{value:.2f}"
    return f"{value:.2f}%"
