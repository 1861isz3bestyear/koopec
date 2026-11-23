# Copyright 2026 anchored-vwam-backtest contributors
"""Check direct tunnel execution parity and rejected account parameters."""

import math
from typing import TYPE_CHECKING

import pandas as pd
import pytest
from shared.gex_rules import GexHypothesis
from shared.strategy import backtest
from shared.strategy_data import BacktestWindow

from gui_calculator.test_app import settings as settings
from gui_calculator.tunnel_backtest import simulate_tunnel, validate_tunnel_run

if TYPE_CHECKING:
    from gui_calculator.settings import CalculatorSettings


@pytest.mark.parametrize("direction", [-1, 1])
@pytest.mark.parametrize("capped", [False, True])
def test_direct_executor_preserves_tunnel_fills(
    settings: CalculatorSettings, direction: int, *, capped: bool
) -> None:
    """Removing generic dispatch preserves BTC fills, costs and frozen caps."""
    times = pd.date_range("2026-01-01", periods=3, freq="5min", tz="UTC")
    data = pd.DataFrame({
        "time": times,
        "open": [100, 100, 100],
        "high": [100, 104, 110],
        "low": [100, 99, 90],
        "close": [100, 102, 100],
        "options_direction": [direction, 0, 0],
        "options_target_ceiling": 103 if capped else math.nan,
        "anchored_vwap": math.nan,
        "anchored_std": math.nan,
    })
    window = BacktestWindow(start=times[0], end=times[-1])
    actual = simulate_tunnel(data, settings=settings, window=window)
    expected = backtest(
        data,
        times[0],
        strategy_end_at=times[-1],
        initial_capital=settings.initial_capital,
        fee_pct=settings.fee_pct,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        minimum_order_size=settings.minimum_order_size,
        slippage_bps=settings.slippage_bps,
        allow_reentry=settings.allow_reentry,
        strategy_mode="GEX",
        gex_hypothesis=GexHypothesis.TUNNEL,
        band_sigma=0,
    )
    pd.testing.assert_frame_equal(actual[0], expected[0])
    assert actual[1] == expected[1]
    assert len(actual[1]) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("initial_capital", 0),
        ("initial_capital", math.inf),
        ("fee_pct", -1),
        ("fee_pct", 100),
        ("fee_pct", math.nan),
        ("minimum_order_size", -1),
        ("stop_loss_pct", -1),
        ("take_profit_pct", math.nan),
        ("slippage_bps", -1),
        ("leverage", 2),
        ("reverse_ticker", True),
    ],
)
def test_invalid_tunnel_account_is_rejected(
    settings: CalculatorSettings, field: str, *, value: float | bool
) -> None:
    """Bad risk parameters cannot bypass removed generic validation."""
    setattr(settings, field, value)
    with pytest.raises(ValueError, match=r"capital|Fee|Risk|Snapshot"):
        validate_tunnel_run(settings)
