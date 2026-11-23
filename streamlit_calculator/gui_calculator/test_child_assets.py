# Copyright 2026 anchored-vwam-backtest contributors
"""Verify BTC-only actions, child prices and separate account ownership."""

from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from shared.child_assets import (
    ChildFunding,
    ChildPrice,
    replay_child,
)
from shared.gex import OPTIONS_GEX_MODE
from shared.models import Trade
from streamlit.testing.v1 import AppTest

from gui_calculator.candle_cache import CandleMarket
from gui_calculator.child_assets import (
    child_prices,
    father_orders,
    load_child_result,
    render_child_assets,
)
from gui_calculator.settings import CalculatorSettings
from tests.support import call_args, call_args_at, frame, mock_child

if TYPE_CHECKING:
    from shared.spot_execution import Side

TIMES = pd.date_range("2026-11-01", periods=4, freq="min", tz="UTC")
FUNDING = ChildFunding(capital=100, fee_pct=0, slippage_bps=0, leverage=1)


def father_trade(*, side: Side = "Long", reason: str = "Take profit") -> Trade:
    """Build a BTC ledger record with prices distinct from the child.

    Returns:
        A completed father trade.

    """
    return Trade(
        deposit_size=100,
        side=side,
        entry_time=TIMES[0],
        exit_time=TIMES[2],
        entry_price=60000,
        exit_price=61000,
        quantity=0.001,
        pnl=1,
        return_pct=1,
        exit_reason=reason,
    )


def price_frame() -> pd.DataFrame:
    """Supply price-only candles with a large intermediate adverse move.

    Returns:
        Child prices without indicators or volume.

    """
    return pd.DataFrame({
        "time": TIMES,
        "open": [1, 0.1, 1.2, 1.3],
        "close": [1.1, 0.05, 1.25, 1.3],
    })


@pytest.mark.parametrize("side", ["Long", "Short"])
@pytest.mark.parametrize(
    "reason",
    ["Take profit", "Stop loss", "Options GEX reversal", "End of strategy"],
)
def test_children_follow_only_executed_father_actions(
    side: Side, reason: str
) -> None:
    """Ignore child price extremes and preserve father's direction and exit."""
    father = father_trade(side=side, reason=reason)
    result = replay_child(
        child_prices(price_frame()), father_orders([father]), funding=FUNDING
    )
    child = result.trades[0]
    assert len(result.trades) == 1
    assert child.side == father.side
    assert child.entry_time == father.entry_time
    assert child.exit_time == father.exit_time
    assert child.exit_reason == reason
    assert child.entry_price == 1
    assert child.exit_price == pytest.approx(1.2)
    expected = 20 if side == "Long" else -20
    assert child.pnl == pytest.approx(expected)
    assert result.marks[-1].equity == pytest.approx(100 + expected)
    assert father.entry_price == pytest.approx(60000)


def test_separate_accounts_compound_without_mutating_father() -> None:
    """Fund each child independently and compound only its own P&L."""
    father = father_trade()
    second = replace(father, entry_time=TIMES[2], exit_time=TIMES[3])
    orders = father_orders([father, second])
    prices = child_prices(price_frame())
    doge = replay_child(prices, orders, funding=FUNDING)
    xrp = replay_child(
        tuple(replace(price, opening=2, close=2) for price in prices),
        orders,
        funding=FUNDING,
    )
    assert doge.trades[1].deposit_size == pytest.approx(120)
    assert doge.marks[-1].equity == pytest.approx(130)
    assert xrp.marks[-1].equity == FUNDING.capital
    assert xrp.trades[1].deposit_size == FUNDING.capital


@pytest.mark.parametrize("side", ["Long", "Short"])
def test_same_candle_round_trip_charges_fees_and_slippage(side: Side) -> None:
    """Keep same-candle action order and never use a future closing price."""
    father = replace(father_trade(side=side), exit_time=TIMES[0])
    funding = replace(FUNDING, fee_pct=0.1, slippage_bps=10, leverage=2)
    result = replay_child(
        child_prices(price_frame()), father_orders([father]), funding=funding
    )
    trade = result.trades[0]
    entry = 1.001 if side == "Long" else 0.999
    exit_price = 0.999 if side == "Long" else 1.001
    assert trade.entry_price == pytest.approx(entry)
    assert trade.exit_price == pytest.approx(exit_price)
    assert trade.quantity == pytest.approx(100 / (0.5 + 0.002) / entry)
    assert trade.pnl < 0


def test_no_father_orders_means_no_child_trades() -> None:
    """Never derive child entries from a price move."""
    result = replay_child(child_prices(price_frame()), (), funding=FUNDING)
    assert result.trades == ()
    assert all(mark.equity == FUNDING.capital for mark in result.marks)


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf")])
def test_reject_invalid_child_prices(invalid: float) -> None:
    """Reject nonpositive or nonfinite price observations."""
    prices = (ChildPrice(time=TIMES[0], opening=invalid, close=1),)
    with pytest.raises(ValueError, match="finite"):
        _ = replay_child(prices, (), funding=FUNDING)


def test_reject_missing_price_at_father_execution() -> None:
    """Do not interpolate or carry a stale price into an order."""
    prices = child_prices(price_frame().drop(index=2))
    with pytest.raises(ValueError, match="Missing child prices"):
        _ = replay_child(
            prices, father_orders([father_trade()]), funding=FUNDING
        )


def test_reject_duplicate_or_unordered_prices() -> None:
    """Require a unique chronological child timeline."""
    prices = child_prices(price_frame())
    for invalid in ((prices[0], prices[0]), tuple(reversed(prices))):
        with pytest.raises(ValueError, match="unique chronological"):
            _ = replay_child(invalid, (), funding=FUNDING)


def test_reject_invalid_father_order_sequence() -> None:
    """Reject backwards, overlapping, unmatched and unclosed actions."""
    orders = father_orders([father_trade()])
    invalid_sequences = (
        tuple(reversed(orders)),
        (orders[0], orders[0], orders[1]),
        (orders[1],),
        (orders[0], replace(orders[1], side="Short")),
        (orders[0],),
    )
    for invalid in invalid_sequences:
        with pytest.raises(
            ValueError, match=r"chronological|overlapping|match|unclosed"
        ):
            _ = replay_child(
                child_prices(price_frame()), invalid, funding=FUNDING
            )


def test_child_depletion_cannot_fabricate_following_entries() -> None:
    """Report depleted capital instead of silently dropping father orders."""
    father = father_trade(side="Short")
    following = replace(father, entry_time=TIMES[2], exit_time=TIMES[3])
    frame = price_frame()
    frame["open"] = [1, 1, 3, 3]
    with pytest.raises(ValueError, match="depleted"):
        _ = replay_child(
            child_prices(frame),
            father_orders([father, following]),
            funding=FUNDING,
        )


@pytest.mark.parametrize(
    "funding",
    [
        {"capital": 0},
        {"capital": float("nan")},
        {"fee_pct": -1},
        {"fee_pct": 100},
        {"fee_pct": float("inf")},
        {"slippage_bps": -1},
        {"slippage_bps": 10000},
        {"leverage": 0},
    ],
)
def test_reject_invalid_funding(funding: dict[str, float]) -> None:
    """Validate external account configuration before replay."""
    with pytest.raises(ValueError, match=r"capital|fee|leverage"):
        _ = replace(FUNDING, **funding)


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame({"close": [1]}),
        pd.DataFrame({"time": ["NaT"], "open": [1], "close": [1]}),
        pd.DataFrame({"time": ["2026-11-01"], "open": [1], "close": [1]}),
        pd.DataFrame({"time": [TIMES[0]], "open": ["bad"], "close": [1]}),
    ],
)
def test_validate_external_price_history(frame: pd.DataFrame) -> None:
    """Require a complete price schema and valid aware timestamps."""
    with pytest.raises(ValueError, match=r"columns|timestamps|convert"):
        _ = child_prices(frame)


def test_validate_father_trade_boundary() -> None:
    """Reject unrecognized directions and exit-before-entry records."""
    for trade in (
        replace(father_trade(), side="invalid"),
        replace(father_trade(), exit_time=TIMES[0] - pd.Timedelta(minutes=1)),
    ):
        with pytest.raises(ValueError, match=r"side|before"):
            _ = father_orders([trade])


def test_load_only_child_prices_and_reject_gaps() -> None:
    """Use the Bybit cache for the selected child without loading signals."""
    equity = pd.DataFrame({"time": TIMES})
    settings = CalculatorSettings(initial_capital=100, fee_pct=0)
    with patch(
        "gui_calculator.child_assets.load_cached_klines",
        return_value=price_frame(),
    ) as loader:
        result = load_child_result(
            "DOGEUSDT",
            equity,
            orders=father_orders([father_trade()]),
            settings=settings,
        )
    assert result.trades[0].pnl == pytest.approx(20)
    market = call_args(loader)[0]
    assert isinstance(market, CandleMarket)
    assert market.symbol == "DOGEUSDT"
    with (
        patch(
            "gui_calculator.child_assets.load_cached_klines",
            return_value=price_frame().drop(index=1),
        ),
        pytest.raises(ValueError, match="missing price candles"),
    ):
        _ = load_child_result("XRPUSDT", equity, orders=(), settings=settings)


def controls_app() -> None:
    """Render production child controls in a small settings test harness."""
    import streamlit as st

    from gui_calculator.child_assets import render_child_controls

    enabled = st.toggle("Simulate trades", value=True)
    selected = render_child_controls(enabled=enabled)
    st.session_state["selected"] = selected


def test_controls_select_children_and_disable_with_simulation() -> None:
    """Allow both children and clear active selection in analytics mode."""
    at = AppTest.from_function(controls_app).run()
    _ = at.multiselect[0].select("DOGEUSDT").select("XRPUSDT").run()
    assert at.session_state["selected"] == ("DOGEUSDT", "XRPUSDT")
    _ = at.toggle[0].set_value(False).run()
    assert at.multiselect[0].disabled
    assert at.session_state["selected"] == ()


def test_render_child_results_and_unavailable_data() -> None:
    """Render separate histories or a visible error without partial results."""
    settings = CalculatorSettings(
        strategy_mode=OPTIONS_GEX_MODE,
        child_assets=("DOGEUSDT", "XRPUSDT"),
        initial_capital=100,
        fee_pct=0,
    )
    equity = pd.DataFrame({"time": TIMES})
    with (
        patch("gui_calculator.child_assets.st") as ui,
        patch(
            "gui_calculator.child_assets.load_cached_klines",
            return_value=price_frame(),
        ),
    ):
        render_child_assets([father_trade()], equity, settings)
    assert mock_child(cast("Mock", ui), "dataframe").call_count == len(
        ("DOGEUSDT", "XRPUSDT")
    )
    assert mock_child(cast("Mock", ui), "plotly_chart").call_count == 1
    assert mock_child(cast("Mock", ui), "download_button").call_count == 1
    summary = frame(
        call_args_at(mock_child(cast("Mock", ui), "dataframe"), 0)[0]
    )
    assert summary["Final equity (USDT)"].tolist() == pytest.approx([120, 120])
    with (
        patch("gui_calculator.child_assets.st") as ui,
        patch(
            "gui_calculator.child_assets.load_cached_klines",
            side_effect=ValueError("missing data"),
        ),
    ):
        render_child_assets([father_trade()], equity, settings)
    assert mock_child(cast("Mock", ui), "error").call_count == 1
    assert mock_child(cast("Mock", ui), "dataframe").call_count == 0


def test_render_guards_do_not_fetch_prices() -> None:
    """Keep child execution scoped to enabled BTC GEX simulated trades."""
    settings = CalculatorSettings(
        strategy_mode=OPTIONS_GEX_MODE, child_assets=("DOGEUSDT",)
    )
    with (
        patch("gui_calculator.child_assets.st") as ui,
        patch("gui_calculator.child_assets.load_cached_klines") as loader,
    ):
        for inactive in (
            replace(settings, child_assets=()),
            replace(settings, simulate_trades=False),
            replace(settings, strategy_mode="AVWAP crossover"),
            replace(settings, ticker="ETH_USDT"),
            replace(settings, reverse_ticker=True),
        ):
            render_child_assets([father_trade()], pd.DataFrame(), inactive)
        render_child_assets([], pd.DataFrame(), settings)
    assert loader.call_count == 0
    assert mock_child(cast("Mock", ui), "error").call_count == len(
        ("DOGEUSDT", "XRPUSDT")
    )
    assert mock_child(cast("Mock", ui), "info").call_count == 1
