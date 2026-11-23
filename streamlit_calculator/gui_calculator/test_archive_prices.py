# Copyright 2026 anchored-vwam-backtest contributors
"""Verify historical price boundaries and explicit download interactions."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
import requests
from shared.validation import json_object, object_list, object_mapping
from snapshot_tunnel.options_model import CandleClose
from streamlit.testing.v1 import AppTest

from gui_calculator.archive_prices import PriceRequest, load_archive_prices
from gui_calculator.snapshot_history_view import history_chart


def test_prices_use_completed_close_times_in_archive_window() -> None:
    """Never plot future closes or prices outside the requested period."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    request = PriceRequest(
        asset="ETH", interval="1m", start=start, end=start + timedelta(hours=1)
    )
    frame = pd.DataFrame({
        "time": [
            start + timedelta(minutes=offset) for offset in (-2, -1, 0, 1)
        ],
        "close": [99, 100, 101, 102],
    })
    with patch(
        "gui_calculator.archive_prices.fetch_bybit_klines", return_value=frame
    ) as fetch:
        candles = load_archive_prices(
            request, now=start + timedelta(minutes=1, seconds=30)
        )
    assert [candle.close for candle in candles] == [100, 101]
    assert candles[0].timestamp == start
    assert candles[-1].timestamp == start + timedelta(minutes=1)
    assert fetch.call_args.args == ("ETHUSDT", "1m")
    with patch("gui_calculator.archive_prices.fetch_bybit_klines") as fetch:
        assert load_archive_prices(request, now=start) == ()
        fetch.assert_not_called()
    with patch(
        "gui_calculator.archive_prices.fetch_bybit_klines",
        return_value=pd.DataFrame(),
    ):
        assert load_archive_prices(request, now=request.end) == ()


@pytest.mark.parametrize("failure", [False, True])
def test_download_is_explicit_and_scoped(*, failure: bool) -> None:
    """Retain successful downloads and invalidate them on scope changes."""
    script = (
        "from dataclasses import replace\n"
        "from datetime import timedelta\n"
        "from gui_calculator.options_gex import EXAMPLE\n"
        "from snapshot_tunnel.options_model import parse_snapshots\n"
        "from gui_calculator.archive_prices import render_archive_prices\n"
        "snapshot = parse_snapshots(EXAMPLE)[0]\n"
        "render_archive_prices((snapshot, replace(snapshot, "
        "timestamp=snapshot.timestamp + timedelta(days=1))))\n"
    )
    with patch(
        "gui_calculator.archive_prices.load_archive_prices",
        return_value=(
            CandleClose(timestamp=datetime(2026, 1, 1, tzinfo=UTC), close=100),
        ),
        side_effect=requests.Timeout("offline") if failure else None,
    ) as fetch:
        app = AppTest.from_string(script).run()
        _ = app.toggle[0].set_value(True).run()
        fetch.assert_not_called()
        _ = app.button[0].click().run()
        assert not app.exception
        fetch.assert_called_once()
        if failure:
            assert app.error
            assert not app.get("download_button")
        else:
            assert app.get("download_button")
            _ = app.run()
            fetch.assert_called_once()
            assert app.get("download_button")
            _ = app.selectbox[0].select_index(0).run()
            assert not app.get("download_button")
            fetch.assert_called_once()


def test_overlay_keeps_snapshot_metrics_on_their_own_timeline() -> None:
    """Detailed prices share the price axis without fabricating GEX samples."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    history = pd.DataFrame({
        "Timestamp (UTC)": [start, start + timedelta(hours=1)],
        "Price": [100, 110],
        "Net GEX": [200, 300],
        "Gamma flip": [90, 95],
        "Put 1": [80, 85],
        "Put 2": [75, 80],
        "Call 1": [120, 125],
        "Call 2": [130, 135],
    })
    prices = tuple(
        CandleClose(
            timestamp=start + timedelta(minutes=index), close=100 + index
        )
        for index in range(4)
    )
    payload = json_object(history_chart(history, prices=prices).to_json())
    traces = [object_mapping(item) for item in object_list(payload["data"])]
    snapshot_price = traces[0]
    gex = next(trace for trace in traces if trace["name"] == "Net GEX")
    overlay = traces[-1]
    assert snapshot_price["mode"] == "markers"
    assert overlay["yaxis"] == snapshot_price["yaxis"]
    assert gex["yaxis"] != overlay["yaxis"]
    assert len(object_list(overlay["x"])) == len(prices)
    assert len(object_list(gex["x"])) == len(history)
