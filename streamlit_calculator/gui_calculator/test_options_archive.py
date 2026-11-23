# Copyright 2026 anchored-vwam-backtest contributors
"""Exercise archive collection, coverage reporting and reusable export."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

from snapshot_tunnel.options_model import parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.options_gex import EXAMPLE

SCRIPT = (
    "from gui_calculator.options_archive import render_options_archive\n"
    "render_options_archive()\n"
)


def test_empty_archive_collection_is_opt_in() -> None:
    """Rendering never silently fetches; enabling collection fetches BTC."""
    with (
        patch("gui_calculator.options_archive.load_snapshots", return_value=()),
        patch("gui_calculator.options_archive.refresh_options") as refresh,
    ):
        app = AppTest.from_string(SCRIPT).run()
        _ = app.toggle[0].set_value(True).run()
        assert not app.exception
        refresh.assert_not_called()
        assert "No saved BTC chains" in app.info[0].value
        assert "--interval 60" in app.code[0].value
        _ = app.toggle[1].set_value(True).run()
        refresh.assert_called_once_with("BTC")


def test_archive_cadence_and_manual_collection() -> None:
    """A recent receipt avoids duplicates and cadence changes the command."""
    history = (
        replace(parse_snapshots(EXAMPLE)[0], timestamp=datetime.now(UTC)),
    )
    with (
        patch(
            "gui_calculator.options_archive.load_snapshots",
            return_value=history,
        ),
        patch("gui_calculator.options_archive.refresh_options") as refresh,
    ):
        app = AppTest.from_string(SCRIPT).run()
        _ = app.toggle[0].set_value(True).run()
        _ = app.toggle[1].set_value(True).run()
        refresh.assert_not_called()
        _ = app.selectbox[0].select("15m").run()
        assert "--interval 900" in app.code[0].value
        assert any("1 BTC observations" in item.value for item in app.caption)
        assert any("Largest interval" in item.value for item in app.caption)
        _ = app.button[0].click().run()
        refresh.assert_called_once_with("BTC")
        assert not app.exception


def test_gap_report_identifies_missing_dates() -> None:
    """Sparse archives expose dates and durations instead of only a count."""
    history = (
        replace(parse_snapshots(EXAMPLE)[0], timestamp=datetime.now(UTC)),
    )
    with patch(
        "gui_calculator.options_archive.load_snapshots", return_value=history
    ):
        app = AppTest.from_string(SCRIPT).run()
        _ = app.toggle[0].set_value(True).run()
    assert not app.exception
    assert "Missing options observations" in app.warning[0].value
    report = app.table[0].value
    assert "Gap start UTC" in report.columns
    assert "Gap end UTC" in report.columns
    assert len(report) == 1


def test_contiguous_report_does_not_invent_gaps() -> None:
    """A complete short interval does not produce a missing-data warning."""
    script = (
        "from datetime import datetime, timedelta, timezone\n"
        "from gui_calculator.options_archive import _render_gaps\n"
        "now = datetime.now(timezone.utc)\n"
        "_render_gaps((now - timedelta(minutes=1), now), "
        "cadence=timedelta(minutes=1))\n"
    )
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert not app.warning
    assert "No observation intervals" in app.caption[0].value
