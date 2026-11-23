# Copyright 2026 anchored-vwam-backtest contributors
"""Available saved times guide historical snapshot selection."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from snapshot_tunnel.options_model import parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.options_gex import EXAMPLE

_REQUEST_APP = (
    "import streamlit as st\n"
    "from gui_calculator.options_gex import EXAMPLE\n"
    "from gui_calculator.snapshot_request_view import render_snapshot_request\n"
    "snapshot = render_snapshot_request(EXAMPLE)\n"
    "if snapshot is not None:\n"
    "    st.caption('Selected: ' + snapshot.timestamp.isoformat())\n"
)


def test_saved_times_filter_asset_day_and_load_exact_observation() -> None:
    """Only actual observations appear, including distinct sub-minute times."""
    first = parse_snapshots(EXAMPLE)[0]
    first = replace(first, timestamp=first.timestamp.replace(second=10))
    second = replace(first, timestamp=first.timestamp + timedelta(seconds=20))
    another_day = replace(first, timestamp=first.timestamp - timedelta(days=1))
    eth = replace(first, asset="ETH")
    with (
        patch(
            "gui_calculator.snapshot_request_view.load_snapshots",
            return_value=(second, eth, another_day, first),
        ),
        patch("gui_calculator.snapshot_request_view.fetch_snapshot") as fetch,
    ):
        app = AppTest.from_string(_REQUEST_APP).run()
        _ = app.selectbox[1].select("Saved history / Deribit API").run()
        assert not app.exception
        assert app.selectbox[2].value == first.timestamp.date()
        assert app.selectbox[3].options == [
            f"{first.timestamp:%H:%M:%S} UTC · available",
            f"{second.timestamp:%H:%M:%S} UTC · available",
        ]
        _ = app.selectbox[3].select_index(1).run()
        _ = app.button[0].click().run()
        assert not app.exception
        assert any(
            item.value == f"Selected: {second.timestamp.isoformat()}"
            for item in app.caption
        )
        _ = app.selectbox[0].select("ETH").run()
        assert not app.exception
        assert app.selectbox[3].options == [
            f"{eth.timestamp:%H:%M:%S} UTC · available",
        ]
        assert not any(
            item.value.startswith("Selected:") for item in app.caption
        )
        fetch.assert_not_called()


def test_saved_date_change_selects_available_time_automatically() -> None:
    """Dates default to their latest observation and preview available times."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    previous = replace(
        snapshot, timestamp=snapshot.timestamp - timedelta(days=1, hours=2)
    )
    with patch(
        "gui_calculator.snapshot_request_view.load_snapshots",
        return_value=(previous, snapshot),
    ):
        app = AppTest.from_string(_REQUEST_APP).run()
        _ = app.selectbox[1].select("Saved history / Deribit API").run()
        assert app.selectbox[2].value == snapshot.timestamp.date()
        assert app.selectbox[3].value == snapshot.timestamp
        assert any("Available dates" in item.value for item in app.caption)
        _ = app.selectbox[2].select_index(0).run()
        assert app.selectbox[3].value == previous.timestamp
        assert any(
            f"{previous.timestamp:%H:%M:%S}" in item.value
            for item in app.caption
        )
        _ = app.button[0].click().run()
        assert not app.exception
        assert any(
            item.value == f"Selected: {previous.timestamp.isoformat()}"
            for item in app.caption
        )
        _ = app.selectbox[0].select("ETH").run()
        assert not app.exception
        assert any(
            "No archived ETH snapshots" in item.value for item in app.info
        )
        assert not app.button
