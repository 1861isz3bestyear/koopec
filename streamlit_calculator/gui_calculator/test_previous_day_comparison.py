# Copyright 2026 anchored-vwam-backtest contributors
"""Verify previous-day matching and live calculator rerun persistence."""

from dataclasses import replace
from datetime import timedelta, timezone
from unittest.mock import patch

import pytest
from snapshot_tunnel.options_data import ChainObservation
from snapshot_tunnel.options_model import parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.previous_day_view import previous_day_snapshot


def test_previous_day_matches_asset_and_utc_minute() -> None:
    """Prefer the requested minute and keep asset and UTC date boundaries."""
    current = replace(
        parse_snapshots(EXAMPLE)[0],
        timestamp=parse_snapshots(EXAMPLE)[0].timestamp.replace(second=45),
    )
    target = (current.timestamp - timedelta(days=1)).replace(second=0)
    expected = replace(current, timestamp=target + timedelta(seconds=10))
    wrong_asset = replace(expected, asset="ETH")
    too_early = replace(current, timestamp=target - timedelta(seconds=1))
    too_late = replace(current, timestamp=target + timedelta(minutes=1))
    later_in_minute = replace(
        expected, timestamp=target + timedelta(seconds=40)
    )
    assert (
        previous_day_snapshot(
            current,
            (too_late, later_in_minute, wrong_asset, expected, too_early),
        )
        == expected
    )
    local = replace(
        current,
        timestamp=current.timestamp.astimezone(timezone(timedelta(hours=3))),
    )
    assert previous_day_snapshot(local, (expected,)) == expected
    assert (
        previous_day_snapshot(current, (wrong_asset, too_early, too_late))
        == too_early
    )
    with pytest.raises(ValueError, match="No saved BTC snapshots"):
        _ = previous_day_snapshot(current, (wrong_asset, current))


@pytest.mark.parametrize("offset", [0, 90])
@pytest.mark.parametrize("available", [True, False])
def test_live_comparison_retains_current_snapshot(
    *, available: bool, offset: int
) -> None:
    """Compare without redownloading today's chain or hiding it on failure."""
    current = parse_snapshots(EXAMPLE)[0]
    previous = replace(
        current,
        timestamp=current.timestamp
        - timedelta(days=1)
        + timedelta(minutes=offset),
    )
    with (
        patch(
            "gui_calculator.snapshot_request_view.fetch_snapshot",
            return_value=ChainObservation(
                snapshot=current, observed_at=current.timestamp
            ),
        ) as fetch,
        patch("gui_calculator.snapshot_request_view.store_snapshot"),
        patch(
            "gui_calculator.previous_day_view.load_snapshots",
            return_value=(previous,) if available else (),
        ) as load,
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import render_options_gex\n"
            "render_options_gex()"
        ).run()
        fetch.assert_not_called()
        _ = app.button[0].click().run()
        assert not app.exception
        load.assert_not_called()
        assert app.button[1].label == "Compare with previous day"
        _ = app.button[1].click().run()
        assert not app.exception
        fetch.assert_called_once()
        load.assert_called_once()
        expected_charts = 9 if available else 6
        assert len(app.get("plotly_chart")) == expected_charts
        if not available:
            assert any(
                "No saved BTC snapshots" in item.value for item in app.info
            )
        _ = app.run()
        assert not app.exception
        fetch.assert_called_once()
        assert len(app.get("plotly_chart")) == expected_charts
        _ = app.selectbox[0].select("ETH").run()
        assert not app.exception
        assert not app.get("plotly_chart")
        fetch.assert_called_once()


def test_loaded_historical_day_compares_to_its_previous_day() -> None:
    """A loaded historical date anchors comparison independently of today."""
    current = parse_snapshots(EXAMPLE)[0]
    previous = replace(current, timestamp=current.timestamp - timedelta(days=1))
    with (
        patch(
            "gui_calculator.snapshot_request_view.load_snapshots",
            return_value=(previous, current),
        ),
        patch(
            "gui_calculator.previous_day_view.load_snapshots",
            return_value=(previous, current),
        ),
        patch("gui_calculator.snapshot_request_view.fetch_snapshot") as fetch,
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import render_options_gex\n"
            "render_options_gex()"
        ).run()
        assert app.date_input[0].disabled
        assert app.time_input[0].disabled
        _ = app.selectbox[1].select("Saved history / Deribit API").run()
        _ = app.button[0].click().run()
        assert not app.exception
        assert not app.error
        _ = app.button[1].click().run()
        assert not app.exception
        assert not app.error
        expected_charts = 9
        assert len(app.get("plotly_chart")) == expected_charts
        assert any(
            f"Before: {previous.timestamp.isoformat()}" in caption.value
            and f"After: {current.timestamp.isoformat()}" in caption.value
            for caption in app.caption
        )
        fetch.assert_not_called()
        _ = app.selectbox[2].select_index(0).run()
        assert not app.exception
        assert not app.get("plotly_chart")
