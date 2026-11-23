# Copyright 2026 anchored-vwam-backtest contributors
"""Verify explicit source selection and visible live collection failures."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests
from snapshot_tunnel.options_model import parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.options_gex import EXAMPLE

SCRIPT = (
    "from gui_calculator.options_source import render_source\n"
    "from gui_calculator.options_gex import EXAMPLE\n"
    "snapshots = render_source(EXAMPLE)\n"
)


def test_saved_history_manual_and_automatic_refresh() -> None:
    """Both controls collect explicitly and preserve the source display."""
    history = parse_snapshots(EXAMPLE)
    with (
        patch(
            "gui_calculator.options_source.load_snapshots", return_value=history
        ),
        patch(
            "gui_calculator.options_source.collect_once", return_value=4
        ) as collect,
    ):
        app = AppTest.from_string(SCRIPT).run()
        assert not app.exception
        collect.assert_not_called()
        _ = app.button[0].click().run()
        collect.assert_called_once_with(asset="BTC")
        assert "complete observation" in app.success[0].value
        collect.reset_mock()
        _ = app.selectbox[1].select("ETH").run()
        _ = app.toggle[0].set_value(True).run()
        collect.assert_called_once_with(asset="ETH")
        assert any("Last receipt" in item.value for item in app.caption)


def test_update_failure_is_visible_and_does_not_create_history() -> None:
    """A network outage is not displayed as a successful empty observation."""
    with (
        patch("gui_calculator.options_source.load_snapshots", return_value=()),
        patch(
            "gui_calculator.options_source.collect_once",
            side_effect=requests.Timeout("unreachable"),
        ),
    ):
        app = AppTest.from_string(SCRIPT).run()
        _ = app.button[0].click().run()
        assert not app.exception
        assert "unreachable" in app.error[0].value
        assert "No saved options history" in app.info[0].value
        assert not app.success


def test_csv_requires_an_explicit_upload() -> None:
    """Selecting CSV without a file never silently loads synthetic data."""
    with patch("gui_calculator.options_source.load_snapshots", return_value=()):
        app = AppTest.from_string(SCRIPT).run()
        _ = app.selectbox[0].select("CSV").run()
    assert not app.exception
    assert not app.warning


def test_daily_source_collects_when_due() -> None:
    """Daily UI refresh uses the selected UTC boundary."""
    history = parse_snapshots(EXAMPLE)
    with (
        patch(
            "gui_calculator.options_source.load_snapshots", return_value=history
        ),
        patch(
            "gui_calculator.options_source.collect_once", return_value=4
        ) as collect,
    ):
        app = AppTest.from_string(SCRIPT).run()
        _ = (
            next(
                item
                for item in app.toggle
                if item.label == "Daily Deribit refresh (UTC)"
            )
            .set_value(True)
            .run()
        )
        assert not app.exception
        collect.assert_called_once_with(asset="BTC")


@pytest.mark.parametrize("age_minutes", [1, 5, 10])
def test_combined_refresh_keeps_five_minute_schedule(age_minutes: int) -> None:
    """Daily refresh must not disable automatic intraday observations."""
    now = datetime(2026, 10, 21, 12, tzinfo=UTC)
    history = (
        replace(
            parse_snapshots(EXAMPLE)[0],
            timestamp=now - timedelta(minutes=age_minutes),
        ),
    )
    with (
        patch(
            "gui_calculator.options_source.datetime",
            MagicMock(now=MagicMock(return_value=now)),
        ),
        patch(
            "gui_calculator.options_source.load_snapshots", return_value=history
        ),
        patch(
            "gui_calculator.options_source.collect_once", return_value=4
        ) as collect,
    ):
        app = AppTest.from_string(SCRIPT).run()
        _ = app.toggle[1].set_value(True).run()
        collect.assert_not_called()
        _ = app.toggle[0].set_value(True).run()
        assert not app.exception
        refresh_minutes = 5
        if age_minutes >= refresh_minutes:
            collect.assert_called_once_with(asset="BTC")
        else:
            collect.assert_not_called()


@pytest.mark.parametrize("research", [True, False])
def test_research_csv_warning(*, research: bool) -> None:
    """Research provenance remains visible after uploading a prepared CSV."""
    from gui_calculator.options_source import render_source

    content = (
        EXAMPLE.replace("DERIBIT", "DERIBIT_RESEARCH_APPROXIMATE")
        if research
        else EXAMPLE
    )
    warning = MagicMock()
    upload = MagicMock(getvalue=MagicMock(return_value=content.encode()))
    with (
        patch("gui_calculator.options_source.st.selectbox", return_value="CSV"),
        patch(
            "gui_calculator.options_source.st.file_uploader",
            return_value=upload,
        ),
        patch("gui_calculator.options_source.st.caption"),
        patch("gui_calculator.options_source.st.warning", warning),
    ):
        snapshots = render_source(EXAMPLE)
        assert snapshots
        if research:
            warning.assert_called_once()
        else:
            warning.assert_not_called()
