# Copyright 2026 anchored-vwam-backtest contributors
"""Test main."""

import unittest
from datetime import UTC
from typing import TYPE_CHECKING, cast, final
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from shared.indicators import (
    RecurringAnchor,
    add_daily_anchored_vwap,
    add_recurring_anchored_vwap,
)
from shared.strategy import backtest
from shared.validation import numeric_string

from gui_calculator.data_sources import (
    fetch_bybit_klines,
    fetch_bybit_linear_klines,
    fetch_bybit_live_price,
    fetch_mexc_klines,
    reverse_candles,
)
from tests.support import uncached

if TYPE_CHECKING:
    from tests.scenarios import BacktestOptions


@final
class Response:
    """Group related behavior checks."""

    def __init__(self, payload: object) -> None:
        """Initialize the instance."""
        self.payload: object = payload

    def json(self) -> object:
        """Verify expected behavior.

        Returns:
            The constructed test value.

        """
        return self.payload

    @staticmethod
    def raise_for_status() -> None:
        """Verify expected behavior."""
        return


class BybitHistoryTests(unittest.TestCase):
    """Group related behavior checks."""

    @staticmethod
    @patch("gui_calculator.data_sources.requests.get")
    def test_live_paper_uses_linear_completed_candles_only(get: Mock) -> None:
        """Verify expected behavior."""
        page = Response({
            "retCode": 0,
            "result": {
                "list": [
                    ["60000", "11", "12", "10", "11", "1", "11"],
                    ["0", "10", "11", "9", "10", "1", "10"],
                ]
            },
        })
        empty = Response({"retCode": 0, "result": {"list": []}})
        get.side_effect = [page, empty]

        candles = fetch_bybit_linear_klines(
            "BTCUSDT", "1m", start_ms=0, end_ms=90_000
        )

        assert len(candles) == 1
        expected_value = 10
        assert candles.iloc[0]["close"] == expected_value
        assert get.call_args_list[0].kwargs["params"]["category"] == "linear"

    @staticmethod
    @patch("gui_calculator.data_sources.requests.get")
    def test_fetches_live_linear_price(get: Mock) -> None:
        """Verify expected behavior."""
        get.return_value = Response({
            "retCode": 0,
            "result": {"list": [{"lastPrice": "12345.67"}]},
        })

        price = uncached(fetch_bybit_live_price)("BTCUSDT")

        assert price == pytest.approx(12345.67)
        assert get.call_args.kwargs["params"]["category"] == "linear"

    @staticmethod
    @patch("gui_calculator.data_sources.requests.get")
    def test_fetch_bybit_klines_paginates_and_normalizes_oldest_first(
        get: Mock,
    ) -> None:
        """Verify expected behavior."""
        responses: list[Response] = [
            Response({"retCode": 0, "retMsg": "OK", "result": {"list": rows}})
            for rows in [
                [
                    ["3000", "30", "34", "29", "33", "2", "66"],
                    ["2000", "20", "24", "19", "23", "3", "69"],
                ],
                [["1000", "10", "14", "9", "13", "4", "52"]],
                [],
            ]
        ]
        get.side_effect = responses

        result = uncached(fetch_bybit_klines)(
            "BTCUSDT", "1m", start_ms=999, end_ms=4000
        )

        assert result["open"].tolist() == [10, 20, 30]
        assert result["number_of_trades"].tolist() == [0, 0, 0]
        assert result["time"].tolist() == list(
            pd.to_datetime([1000, 2000, 3000], unit="ms", utc=True)
        )
        assert get.call_args_list[0].kwargs["params"]["interval"] == "1"
        expected_value = 1999
        assert get.call_args_list[1].kwargs["params"]["end"] == expected_value

    @staticmethod
    @patch("gui_calculator.data_sources.requests.get")
    def test_fetch_bybit_klines_surfaces_api_errors(get: Mock) -> None:
        """Verify expected behavior."""
        response = Response({"retCode": 10001, "retMsg": "invalid symbol"})
        get.return_value = response

        with pytest.raises(ValueError, match="invalid symbol"):
            _ = uncached(fetch_bybit_klines)(
                "BAD", "1h", start_ms=0, end_ms=1000
            )


class MexcHistoryTests(unittest.TestCase):
    """Group related behavior checks."""

    @staticmethod
    @patch("gui_calculator.data_sources.requests.get")
    def test_empty_response_preserves_standard_candle_schema(get: Mock) -> None:
        """Verify expected behavior."""
        get.return_value = Response([])

        result = uncached(fetch_mexc_klines)(
            "SHIBUSDT", "1h", start_ms=0, end_ms=3000
        )

        assert result.empty
        assert "time" in result.columns

    @staticmethod
    @patch("gui_calculator.data_sources.requests.get")
    def test_limits_each_mexc_request_to_one_thousand_candles(
        get: Mock,
    ) -> None:
        """Verify expected behavior."""
        get.return_value = Response([])

        _ = uncached(fetch_mexc_klines)(
            "SHIBUSDT", "1m", start_ms=0, end_ms=100_000_000
        )

        expected_value = 59999999
        assert get.call_args.kwargs["params"]["endTime"] == expected_value

    @staticmethod
    @patch("gui_calculator.data_sources.requests.get")
    def test_fetches_and_normalizes_mexc_klines(get: Mock) -> None:
        """Verify expected behavior."""
        page = Response([
            [1000, "1", "3", "0.5", "2", "10", 1999, "20"],
            [2000, "2", "4", "1.5", "3", "11", 2999, "33"],
        ])
        empty = Response([])
        get.side_effect = [page, empty]

        result = uncached(fetch_mexc_klines)(
            "SHIBUSDT", "1h", start_ms=0, end_ms=3000
        )

        assert result["close"].tolist() == [2, 3]
        assert result["number_of_trades"].tolist() == [0, 0]
        assert get.call_args_list[0].kwargs["params"]["symbol"] == "SHIBUSDT"
        assert get.call_args_list[0].kwargs["params"]["interval"] == "60m"
        expected_value = 2001
        assert (
            get.call_args_list[1].kwargs["params"]["startTime"]
            == expected_value
        )

    @staticmethod
    @patch("gui_calculator.data_sources.requests.get")
    def test_surfaces_mexc_api_errors(get: Mock) -> None:
        """Verify expected behavior."""
        get.return_value = Response({"code": -1121, "msg": "Invalid symbol."})

        with pytest.raises(ValueError, match="Invalid symbol"):
            _ = uncached(fetch_mexc_klines)(
                "VEDUSDT", "1h", start_ms=0, end_ms=1000
            )


class ReversedTickerTests(unittest.TestCase):
    """Provide the reversedtickertests test double."""

    @staticmethod
    def test_reverses_ohlc_and_swaps_volumes() -> None:
        """Verify expected behavior."""
        candles = pd.DataFrame({
            "time": pd.to_datetime([0], unit="ms", utc=True),
            "open": [2.0],
            "high": [4.0],
            "low": [1.0],
            "close": [2.5],
            "volume": [3.0],
            "quote_asset_volume": [7.5],
            "number_of_trades": [4],
        })

        result = reverse_candles(candles).iloc[0]

        assert tuple(
            numeric_string(cast("object", result[name]))
            for name in ("open", "high", "low", "close")
        ) == (0.5, 1.0, 0.25, 0.4)
        assert tuple(
            numeric_string(cast("object", result[name]))
            for name in ("volume", "quote_asset_volume")
        ) == (7.5, 3.0)


class BacktestTimelineTests(unittest.TestCase):
    """Provide the backtesttimelinetests test double."""

    @staticmethod
    def test_does_not_open_below_configured_minimum_order_size() -> None:
        """Verify expected behavior."""
        times = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
        data = pd.DataFrame({
            "time": times,
            "open": [10, 8, 10],
            "high": [10, 8, 10],
            "low": [10, 8, 10],
            "close": [10, 8, 10],
            "anchored_vwap": [10] * 3,
            "anchored_std": [1] * 3,
        })

        _, trades = backtest(
            data,
            strategy_start_at=times[0],
            strategy_end_at=times[-1],
            initial_capital=0.10,
            minimum_order_size=0.11,
            fee_pct=0,
            stop_loss_pct=0,
            take_profit_pct=0,
            allow_reentry=True,
            strategy_mode="VWAP band mean reversion",
            band_sigma=1,
        )

        assert trades == []

    @staticmethod
    def test_trend_mode_opens_and_closes_on_directional_sigma_bands() -> None:
        """Verify expected behavior."""
        times = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
        common = {
            "time": times,
            "open": [10, 10, 10],
            "close": [10, 10, 10],
            "anchored_vwap": [10] * 3,
            "anchored_std": [1] * 3,
        }
        long_data = pd.DataFrame(
            {**common, "high": [10, 11, 12], "low": [10, 10, 10]}
        )
        short_data = pd.DataFrame(
            {**common, "high": [10, 10, 10], "low": [10, 9, 8]}
        )

        backtest_options: BacktestOptions = {
            "strategy_start_at": times[0],
            "strategy_end_at": times[-1],
            "initial_capital": 1_000,
            "fee_pct": 0,
            "stop_loss_pct": 0,
            "take_profit_pct": 0,
            "allow_reentry": True,
            "strategy_mode": "VWAP band mean reversion",
            "band_sigma": 1,
            "exit_band_sigma": 2,
            "trend_mode": True,
        }
        long_options: BacktestOptions = {
            **backtest_options,
            "open_position_side": "Long",
        }
        short_options: BacktestOptions = {
            **backtest_options,
            "open_position_side": "Short",
        }
        _, long_trades = backtest(long_data, **long_options)
        _, short_trades = backtest(short_data, **short_options)

        assert (long_trades[0].entry_price, long_trades[0].exit_price) == (
            11,
            12,
        )
        assert (
            long_trades[0].exit_reason
            == "Reached +2\N{GREEK SMALL LETTER SIGMA} exit band"
        )
        assert (short_trades[0].entry_price, short_trades[0].exit_price) == (
            9,
            8,
        )
        assert (
            short_trades[0].exit_reason
            == "Reached -2\N{GREEK SMALL LETTER SIGMA} exit band"
        )

    @staticmethod
    def test_mean_reversion_open_position_side_can_be_selected() -> None:
        """Verify expected behavior."""
        times = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
        data = pd.DataFrame({
            "time": times,
            "open": [10, 8, 12],
            "high": [10, 8, 12],
            "low": [10, 8, 11],
            "close": [10, 8, 12],
            "anchored_vwap": [10] * 3,
            "anchored_std": [1] * 3,
        })

        _, trades = backtest(
            data,
            strategy_start_at=times[0],
            strategy_end_at=times[-1],
            initial_capital=1_000,
            fee_pct=0,
            stop_loss_pct=0,
            take_profit_pct=0,
            allow_reentry=True,
            strategy_mode="VWAP band mean reversion",
            band_sigma=1,
            exit_band_sigma=0,
            open_position_side="Short",
        )

        assert len(trades) == 1
        expected_value = 1000
        assert trades[0].deposit_size == expected_value
        assert trades[0].side == "Short"
        assert trades[0].entry_time == times[2]

    @staticmethod
    def test_mean_reversion_can_close_at_sigma_band() -> None:
        """Verify expected behavior."""
        times = pd.date_range("2026-01-01", periods=4, freq="1h", tz="UTC")
        data = pd.DataFrame({
            "time": times,
            "open": [10, 8, 9.2, 10],
            "high": [10, 9, 9.2, 10],
            "low": [10, 8, 9, 10],
            "close": [10, 8, 9.2, 10],
            "anchored_vwap": [10] * 4,
            "anchored_std": [1] * 4,
        })

        _, trades = backtest(
            data,
            strategy_start_at=times[0],
            strategy_end_at=times[-1],
            initial_capital=1_000,
            fee_pct=0,
            stop_loss_pct=0,
            take_profit_pct=0,
            allow_reentry=True,
            strategy_mode="VWAP band mean reversion",
            band_sigma=1,
            exit_band_sigma=1,
        )

        assert len(trades) == 1
        assert trades[0].entry_time == times[1]
        assert trades[0].exit_time == times[2]
        assert trades[0].exit_price == pytest.approx(9.2)
        assert (
            trades[0].exit_reason
            == "Reached -1\N{GREEK SMALL LETTER SIGMA} exit band"
        )

    @staticmethod
    def test_mean_reversion_close_sigma_beyond_open_is_band_stop() -> None:
        """Verify expected behavior."""
        times = pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC")
        data = pd.DataFrame({
            "time": times,
            "open": [10, 9, 8],
            "high": [10, 9.2, 8.5],
            "low": [10, 8.8, 7.8],
            "close": [10, 9, 8],
            "anchored_vwap": [10] * 3,
            "anchored_std": [1] * 3,
        })

        _, trades = backtest(
            data,
            strategy_start_at=times[0],
            strategy_end_at=times[-1],
            initial_capital=1_000,
            fee_pct=0,
            stop_loss_pct=0,
            take_profit_pct=0,
            allow_reentry=True,
            strategy_mode="VWAP band mean reversion",
            band_sigma=1,
            exit_band_sigma=2,
        )

        assert len(trades) == 1
        expected_value = 9
        assert trades[0].entry_price == expected_value
        expected_value = 8
        assert trades[0].exit_price == expected_value
        assert (
            trades[0].exit_reason
            == "Reached -2\N{GREEK SMALL LETTER SIGMA} exit band"
        )

    @staticmethod
    def test_daily_anchor_resets_at_selected_weekday_time() -> None:
        """Verify expected behavior."""
        times = pd.date_range(
            "2026-01-06", "2026-01-07 03:00", freq="1h", tz="UTC"
        )
        data = pd.DataFrame({
            "time": times,
            "high": range(1, len(times) + 1),
            "low": range(1, len(times) + 1),
            "close": range(1, len(times) + 1),
            "volume": [1] * len(times),
        })

        result = add_daily_anchored_vwap(
            data, pd.Timestamp("02:00").time(), UTC
        )

        result_times = pd.DatetimeIndex(result["time"])
        expected_value = 6
        expected_value_2 = 2
        first_day_before_anchor = (result_times.day == expected_value) & (
            result_times.hour < expected_value_2
        )
        assert result.loc[first_day_before_anchor, "anchored_vwap"].isna().all()
        expected_value = 7
        expected_value_2 = 2
        next_day_before_anchor = (result_times.day == expected_value) & (
            result_times.hour < expected_value_2
        )
        assert result.loc[next_day_before_anchor, "anchored_vwap"].notna().all()
        expected_value = 2
        daily_anchor_rows = result[result_times.hour == expected_value]
        assert (
            daily_anchor_rows["anchored_vwap"].tolist()
            == daily_anchor_rows["close"].tolist()
        )

    @staticmethod
    def test_weekly_anchor_resets_on_selected_weekday() -> None:
        """Verify expected behavior."""
        times = pd.date_range("2026-01-05", "2026-01-13", freq="1h", tz="UTC")
        values = list(range(1, len(times) + 1))
        data = pd.DataFrame({
            "time": times,
            "high": values,
            "low": values,
            "close": values,
            "volume": 1,
        })

        result = add_recurring_anchored_vwap(
            data,
            "Weekly",
            pd.Timestamp("02:00").time(),
            options=RecurringAnchor(selected_timezone=UTC, anchor_weekday=1),
        )

        before_first_anchor = result["time"] < pd.Timestamp(
            "2026-01-06 02:00", tz="UTC"
        )
        assert result.loc[before_first_anchor, "anchored_vwap"].isna().all()
        result_times = pd.DatetimeIndex(result["time"])
        expected_value = 2
        anchors = result[
            (result_times.weekday == 1) & (result_times.hour == expected_value)
        ]
        assert anchors["anchored_vwap"].tolist() == anchors["close"].tolist()

    @staticmethod
    def test_monthly_anchor_resets_on_selected_month_day() -> None:
        """Verify expected behavior."""
        times = pd.date_range("2026-01-31", "2026-03-03", freq="6h", tz="UTC")
        values = list(range(1, len(times) + 1))
        data = pd.DataFrame({
            "time": times,
            "high": values,
            "low": values,
            "close": values,
            "volume": 1,
        })

        result = add_recurring_anchored_vwap(
            data,
            "Monthly",
            pd.Timestamp("00:00").time(),
            options=RecurringAnchor(selected_timezone=UTC, anchor_month_day=2),
        )

        result_times = pd.DatetimeIndex(result["time"])
        expected_value = 2
        anchors = result[
            (result_times.day == expected_value) & (result_times.hour == 0)
        ]
        assert anchors["anchored_vwap"].tolist() == anchors["close"].tolist()

    @staticmethod
    def test_anchor_can_reset_every_two_weeks() -> None:
        """Verify that anchor can reset every two weeks."""
        times = pd.date_range("2026-01-05", "2026-01-21", freq="1h", tz="UTC")
        values = list(range(1, len(times) + 1))
        data = pd.DataFrame({
            "time": times,
            "high": values,
            "low": values,
            "close": values,
            "volume": 1,
        })

        result = add_recurring_anchored_vwap(
            data,
            "Weekly",
            pd.Timestamp("00:00").time(),
            options=RecurringAnchor(
                selected_timezone=UTC,
                anchor_weekday=1,
                interval_count=2,
            ),
        )

        reset_rows = result[
            result["anchored_vwap"].notna()
            & result["anchored_vwap"].eq(result["close"])
        ]
        assert reset_rows["time"].tolist() == [
            pd.Timestamp("2026-01-06", tz="UTC"),
            pd.Timestamp("2026-01-20", tz="UTC"),
        ]

    @staticmethod
    def test_anchor_can_reset_every_two_months() -> None:
        """Verify that anchor can reset every two months."""
        times = pd.date_range("2026-01-01", "2026-03-03", freq="6h", tz="UTC")
        values = list(range(1, len(times) + 1))
        data = pd.DataFrame({
            "time": times,
            "high": values,
            "low": values,
            "close": values,
            "volume": 1,
        })

        result = add_recurring_anchored_vwap(
            data,
            "Monthly",
            pd.Timestamp("00:00").time(),
            options=RecurringAnchor(
                selected_timezone=UTC,
                anchor_month_day=2,
                interval_count=2,
            ),
        )

        reset_rows = result[
            result["anchored_vwap"].notna()
            & result["anchored_vwap"].eq(result["close"])
        ]
        assert reset_rows["time"].tolist() == [
            pd.Timestamp("2026-01-02", tz="UTC"),
            pd.Timestamp("2026-03-02", tz="UTC"),
        ]

    @staticmethod
    def test_trades_are_strictly_limited_to_strategy_timeline() -> None:
        """Verify that trades are strictly limited to strategy timeline."""
        times = pd.date_range("2026-01-01", periods=7, freq="1h", tz="UTC")
        data = pd.DataFrame({
            "time": times,
            "open": [9, 11, 9, 11, 12, 13, 14],
            "high": [9, 11, 9, 11, 12, 13, 14],
            "low": [9, 11, 9, 11, 12, 13, 14],
            "close": [9, 11, 9, 11, 12, 13, 14],
            "anchored_vwap": [10] * 7,
            "anchored_std": [1] * 7,
        })
        strategy_start = times[2]
        strategy_end = times[4]

        equity, trades = backtest(
            data,
            strategy_start_at=strategy_start,
            strategy_end_at=strategy_end,
            initial_capital=1_000,
            fee_pct=0,
            stop_loss_pct=0,
            take_profit_pct=0,
            allow_reentry=True,
            strategy_mode="AVWAP crossover",
            band_sigma=1,
        )

        assert len(trades) == 1
        assert trades[0].entry_time == times[3]
        assert trades[0].exit_time == strategy_end
        assert trades[0].exit_reason == "End of strategy"
        assert equity["time"].between(strategy_start, strategy_end).all()
        assert equity.iloc[-1]["position"] == 0

    @staticmethod
    def test_empty_strategy_timeline_produces_no_trades() -> None:
        """Verify that empty strategy timeline produces no trades."""
        time = pd.Timestamp("2026-01-01", tz="UTC")
        data = pd.DataFrame({
            "time": [time],
            "open": [9],
            "high": [9],
            "low": [9],
            "close": [9],
            "anchored_vwap": [10],
            "anchored_std": [1],
        })

        equity, trades = backtest(
            data,
            strategy_start_at=time + pd.Timedelta(hours=1),
            strategy_end_at=time + pd.Timedelta(hours=2),
            initial_capital=1_000,
            fee_pct=0,
            stop_loss_pct=0,
            take_profit_pct=0,
            allow_reentry=True,
            strategy_mode="AVWAP crossover",
            band_sigma=1,
        )

        assert equity.empty
        assert trades == []

    @staticmethod
    def test_recurring_weekday_schedule_spans_long_timeline() -> None:
        """Verify that recurring weekday schedule spans long timeline."""
        times = pd.date_range(
            "2026-01-01", "2026-07-15 23:00", freq="1h", tz="UTC"
        )
        data = pd.DataFrame({
            "time": times,
            "open": [11] * len(times),
            "high": [11] * len(times),
            "low": [11] * len(times),
            "close": [11] * len(times),
            "anchored_vwap": [10] * len(times),
            "anchored_std": [1] * len(times),
        })

        equity, trades = backtest(
            data,
            strategy_start_at=pd.Timestamp("2026-01-01", tz="UTC"),
            strategy_end_at=pd.Timestamp("2026-07-15 23:00", tz="UTC"),
            initial_capital=1_000,
            fee_pct=0,
            stop_loss_pct=0,
            take_profit_pct=0,
            allow_reentry=True,
            strategy_mode="AVWAP crossover",
            band_sigma=1,
            active_weekdays={1, 2, 3},
            strategy_timezone=UTC,
        )

        assert not equity.empty
        assert set(pd.DatetimeIndex(equity["time"]).weekday) == {1, 2, 3}
        assert equity["time"].min() == pd.Timestamp("2026-01-01", tz="UTC")
        assert equity["time"].max() == pd.Timestamp(
            "2026-07-15 23:00", tz="UTC"
        )
        assert trades
        assert all(trade.entry_time.weekday() in {1, 2, 3} for trade in trades)
        assert all(trade.exit_time.weekday() in {1, 2, 3} for trade in trades)
        assert all(
            trade.exit_reason == "End of scheduled session" for trade in trades
        )

    @staticmethod
    def test_weekday_schedule_limits_trading_to_daily_session() -> None:
        """Verify that weekday schedule limits trading to daily session."""
        times = pd.date_range(
            "2026-01-06", "2026-01-08 23:00", freq="1h", tz="UTC"
        )
        data = pd.DataFrame({
            "time": times,
            "open": [11] * len(times),
            "high": [11] * len(times),
            "low": [11] * len(times),
            "close": [11] * len(times),
            "anchored_vwap": [10] * len(times),
            "anchored_std": [1] * len(times),
        })

        equity, trades = backtest(
            data,
            strategy_start_at=times[0],
            strategy_end_at=times[-1],
            initial_capital=1_000,
            fee_pct=0,
            stop_loss_pct=0,
            take_profit_pct=0,
            allow_reentry=True,
            strategy_mode="AVWAP crossover",
            band_sigma=1,
            active_weekdays={1, 2, 3},
            strategy_timezone=UTC,
            active_session_start=pd.Timestamp("14:00").time(),
            active_session_end=pd.Timestamp("22:00").time(),
        )

        assert set(pd.DatetimeIndex(equity["time"]).hour) == set(range(14, 23))
        expected_value = 14
        assert all(trade.entry_time.hour == expected_value for trade in trades)
        expected_value = 22
        assert all(trade.exit_time.hour == expected_value for trade in trades)

    @staticmethod
    def test_weekday_schedule_can_continue_into_next_day() -> None:
        """Verify that weekday schedule can continue into next day."""
        times = pd.date_range(
            "2026-01-06", "2026-01-07 12:00", freq="1h", tz="UTC"
        )
        data = pd.DataFrame({
            "time": times,
            "open": [11] * len(times),
            "high": [11] * len(times),
            "low": [11] * len(times),
            "close": [11] * len(times),
            "anchored_vwap": [10] * len(times),
            "anchored_std": [1] * len(times),
        })

        equity, trades = backtest(
            data,
            strategy_start_at=times[0],
            strategy_end_at=times[-1],
            initial_capital=1_000,
            fee_pct=0,
            stop_loss_pct=0,
            take_profit_pct=0,
            allow_reentry=True,
            strategy_mode="AVWAP crossover",
            band_sigma=1,
            active_weekdays={1},
            strategy_timezone=UTC,
            active_session_start=pd.Timestamp("14:00").time(),
            active_session_end=pd.Timestamp("08:00").time(),
        )

        assert equity["time"].min() == pd.Timestamp(
            "2026-01-06 14:00", tz="UTC"
        )
        assert equity["time"].max() == pd.Timestamp(
            "2026-01-07 08:00", tz="UTC"
        )
        assert trades[0].entry_time == pd.Timestamp(
            "2026-01-06 14:00", tz="UTC"
        )
        assert trades[0].exit_time == pd.Timestamp("2026-01-07 08:00", tz="UTC")


if __name__ == "__main__":
    _ = unittest.main()
