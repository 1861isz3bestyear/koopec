# Copyright 2026 anchored-vwam-backtest contributors
"""Verify independent market feeds, calculation boundaries and live controls."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests
from streamlit.testing.v1 import AppTest

from gui_calculator.live_oscillator_data import (
    fetch_book,
    parse_book,
)

STAMP = datetime(2026, 10, 30, tzinfo=UTC)
BOOK = {
    "retCode": 0,
    "time": int(STAMP.timestamp() * 1000),
    "result": {"s": "BTCUSDT", "b": [["99", "3"]], "a": [["101", "1"]]},
}


def test_book_uses_actual_depth_and_exchange_time() -> None:
    """Unequal resting depth gives a percentage without using price RSI."""
    book = parse_book(json.dumps(BOOK), symbol="BTCUSDT")
    assert book.price == pytest.approx(100)
    assert book.oscillator == pytest.approx(75)
    assert book.timestamp == STAMP
    with patch(
        "requests.Session.get", return_value=MagicMock(text=json.dumps(BOOK))
    ) as get:
        with requests.Session() as session:
            assert fetch_book(session, asset="BTC") == book
        expected_depth = 50
        assert get.call_args.kwargs["params"]["limit"] == expected_depth


@pytest.mark.parametrize(
    "changes",
    [
        {"retCode": 10001},
        {"result": {"s": "ETHUSDT"}},
        {"result": {"s": "BTCUSDT", "b": [], "a": [["101", "1"]]}},
        {"result": {"s": "BTCUSDT", "b": [["99"]], "a": [["101", "1"]]}},
        {"result": {"s": "BTCUSDT", "b": [["0", "3"]], "a": [["101", "1"]]}},
        {"result": {"s": "BTCUSDT", "b": [["99", "-1"]], "a": [["101", "1"]]}},
        {"result": {"s": "BTCUSDT", "b": [["102", "3"]], "a": [["101", "1"]]}},
        {"result": {"s": "BTCUSDT", "b": [["99", "0"]], "a": [["101", "0"]]}},
    ],
)
def test_invalid_books(changes: dict[str, object]) -> None:
    """Reject exchange failures, mismatched symbols and unusable depth."""
    with pytest.raises(ValueError, match=r".+"):
        _ = parse_book(json.dumps({**BOOK, **changes}), symbol="BTCUSDT")


def test_options_workspace_omits_legacy_live_charts() -> None:
    """Snapshot controls appear without unrelated live oscillator panels."""
    app = AppTest.from_string(
        "from gui_calculator.options_gex import render_options_gex\n"
        "render_options_gex()\n"
    ).run()
    assert not app.exception
    assert not app.get("plotly_chart")
    titles = [heading.value for heading in app.subheader]
    assert "Order-book imbalance oscillator" not in titles
    assert "Margin-loan oscillator" not in titles
    assert not app.metric
    assert not app.radio


def test_reference_arrows_mark_entries_without_repeating_extremes() -> None:
    """Mark each extreme entry once and skip warmup and gaps."""
    from shared.validation import json_object, object_list, object_mapping

    from gui_calculator.live_oscillators import (
        add_oscillator_trace,
        oscillator_chart,
    )

    chart = oscillator_chart(title="Reference", price_label="BTCUSDT")
    values = [None, 20.0, 50.0, 29.0, 25.0, 50.0, 71.0, 80.0, None, 75.0]
    times = [STAMP + timedelta(minutes=index) for index in range(len(values))]
    add_oscillator_trace(chart, times, values)
    payload = json_object(chart.to_json())
    traces = [object_mapping(item) for item in object_list(payload["data"])]
    entries = {
        trace["name"]: trace["y"]
        for trace in traces
        if "threshold entry" in str(trace["name"])
    }
    assert entries == {
        "LONG threshold entry": [29.0],
        "SHORT threshold entry": [71.0],
    }
    layout = object_mapping(payload["layout"])
    assert object_mapping(layout["xaxis"])["type"] == "date"
    assert object_mapping(layout["xaxis2"])["type"] == "date"
    shapes = [object_mapping(item) for item in object_list(layout["shapes"])]
    assert [shape["y0"] for shape in shapes] == [30, 62, 30, 50, 70]
    assert all(shape["yref"] == "y2" for shape in shapes)
    assert object_mapping(layout["yaxis"])["side"] == "right"
    assert object_mapping(layout["yaxis2"])["range"] == [0, 100]


def test_live_margin_uses_bitget_without_legacy_selector() -> None:
    """Render Bitget independently even when the order-book feed fails."""
    with (
        patch("gui_calculator.bitget_view.render_live_bitget") as render_margin,
        patch(
            "gui_calculator.live_oscillators.fetch_book",
            side_effect=ValueError("bad book"),
        ),
    ):
        app = AppTest.from_string(
            "from gui_calculator.live_oscillators import"
            " render_live_oscillators\nrender_live_oscillators()\n"
        ).run()
        render_margin.assert_not_called()
        _ = app.toggle[0].set_value(True).run()
        _ = app.toggle[1].set_value(True).run()
        assert not app.exception
        render_margin.assert_called_with("BTC")
        assert "Order-book feed unavailable" in app.error[0].value
        assert [control.label for control in app.radio] == ["Oscillator market"]
