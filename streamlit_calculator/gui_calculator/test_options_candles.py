# Copyright 2026 anchored-vwam-backtest contributors
"""Verify automatic candle loading and its UI failure boundary."""

from datetime import timedelta
from unittest.mock import patch

import pandas as pd
import pytest
import requests
from snapshot_tunnel.options_model import parse_candle_closes, parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.options_candles import load_completed_candles
from gui_calculator.options_gex import EXAMPLE


def test_completed_candles_use_close_time_and_selected_asset() -> None:
    """Exclude pre-observation and still-open bars without shifting prices."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    minute = snapshot.timestamp.replace(second=0, microsecond=0)
    expected_close = 81_000
    frame = pd.DataFrame({
        "time": [
            minute - timedelta(minutes=2),
            minute,
            minute + timedelta(minutes=1),
        ],
        "close": [80_000, 81_000, 82_000],
    })
    with patch(
        "gui_calculator.options_candles.fetch_bybit_klines", return_value=frame
    ) as fetch:
        candles = load_completed_candles(
            snapshot, now=minute + timedelta(minutes=1, seconds=30)
        )
    assert len(candles) == 1
    assert candles[0].timestamp == minute + timedelta(minutes=1)
    assert candles[0].close == expected_close
    assert fetch.call_args.args == (f"{snapshot.asset}USDT", "1m")


def test_empty_and_future_candle_windows() -> None:
    """Avoid a request for future observations and accept empty history."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    with patch(
        "gui_calculator.options_candles.fetch_bybit_klines",
        return_value=pd.DataFrame(),
    ) as fetch:
        assert not load_completed_candles(snapshot, now=snapshot.timestamp)
        fetch.assert_not_called()
        assert not load_completed_candles(
            snapshot, now=snapshot.timestamp + timedelta(minutes=1)
        )


@pytest.mark.parametrize("failure", [False, True])
def test_successful_collection_triggers_candles(*, failure: bool) -> None:
    """Load candles after collection and show candle outages independently."""
    history = parse_snapshots(EXAMPLE)
    script = (
        "from gui_calculator.options_gex import EXAMPLE, _render_live_candles\n"
        "from gui_calculator.options_source import render_source\n"
        "history = render_source(EXAMPLE)\n"
        "if history: _render_live_candles(history[0])"
    )
    with (
        patch(
            "gui_calculator.options_source.load_snapshots", return_value=history
        ),
        patch("gui_calculator.options_source.collect_once", return_value=4),
        patch("gui_calculator.options_gex._render_profile"),
        patch(
            "gui_calculator.options_candles.load_completed_candles",
            return_value=(),
            side_effect=requests.Timeout("offline") if failure else None,
        ) as fetch,
    ):
        app = AppTest.from_string(script).run()
        fetch.assert_not_called()
        _ = app.toggle[0].set_value(True).run()
        fetch.assert_called_once()
        assert not app.exception
        if failure:
            assert "offline" in app.error[0].value
        else:
            assert "Candle check complete" in app.info[-1].value
        fetch.reset_mock()
        _ = app.selectbox[0].select("Synthetic demo").run()
        fetch.assert_not_called()


def test_failed_collection_does_not_trigger_candles() -> None:
    """Saved observations must not turn a failed collection into success."""
    with (
        patch(
            "gui_calculator.options_source.load_snapshots",
            return_value=parse_snapshots(EXAMPLE),
        ),
        patch(
            "gui_calculator.options_source.collect_once",
            side_effect=requests.Timeout("offline"),
        ),
        patch("gui_calculator.options_gex._render_profile"),
        patch("gui_calculator.options_candles.load_completed_candles") as fetch,
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import EXAMPLE,"
            " _render_live_candles\nfrom gui_calculator.options_source import"
            " render_source\nhistory = render_source(EXAMPLE)\nif history:"
            " _render_live_candles(history[0])"
        ).run()
        _ = app.toggle[0].set_value(True).run()
        assert not app.exception
        assert "Deribit update failed" in app.error[0].value
        fetch.assert_not_called()


def test_invalid_exchange_close_is_rejected() -> None:
    """Reject invalid external prices before calculating exposure."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    with (
        patch(
            "gui_calculator.options_candles.fetch_bybit_klines",
            return_value=pd.DataFrame({
                "time": [snapshot.timestamp],
                "close": [-1],
            }),
        ),
        pytest.raises(ValueError, match="positive"),
    ):
        _ = load_completed_candles(
            snapshot, now=snapshot.timestamp + timedelta(minutes=2)
        )


def test_candle_refresh_reuses_observation_without_collecting() -> None:
    """A later candle check can populate GEX without fetching a new chain."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    candle = parse_candle_closes(
        "timestamp,close\n"
        f"{(snapshot.timestamp + timedelta(minutes=1)).isoformat()},81000\n"
    )
    script = (
        "from gui_calculator.options_gex import EXAMPLE, _render_live_candles\n"
        "from snapshot_tunnel.options_model import parse_snapshots\n"
        "_render_live_candles(parse_snapshots(EXAMPLE)[0])"
    )
    with (
        patch(
            "gui_calculator.options_candles.load_completed_candles",
            side_effect=[(), candle],
        ) as fetch,
        patch("gui_calculator.options_source.collect_once") as collect,
        patch("gui_calculator.options_gex._render_candle_updates") as render,
    ):
        app = AppTest.from_string(script)
        app.session_state["options_data_source"] = "Saved history / Deribit API"
        app.session_state[f"options_candles_ready_{snapshot.asset}"] = True
        _ = app.run()
        assert not app.exception
        assert "Candle check complete" in app.info[0].value
        render.assert_not_called()
        _ = app.run()
        assert not app.exception
        assert not app.info
        assert "loaded 1 completed" in app.caption[0].value
        assert fetch.call_args.args == (snapshot,)
        assert render.call_args.args[:2] == (snapshot, candle)
        collect.assert_not_called()
