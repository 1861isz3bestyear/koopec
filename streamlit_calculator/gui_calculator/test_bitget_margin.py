# Copyright 2026 anchored-vwam-backtest contributors
"""Verify Bitget lending context and historical snapshot boundaries."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest
import requests
from snapshot_tunnel.bitget import Growth, LoanRate
from streamlit.testing.v1 import AppTest

from gui_calculator.bitget_view import load_bitget_growth, load_bitget_rate

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot

STAMP = datetime(2026, 11, 1, tzinfo=UTC)
APP = """
from datetime import UTC, datetime
from snapshot_tunnel.options_model import Snapshot
from gui_calculator.bitget_view import render_bitget_margin
snapshot = Snapshot(
    timestamp=datetime(2026,11,1,tzinfo=UTC),
    asset="BTC", spot=1, options=(),
)
render_bitget_margin(snapshot, days=7)
"""


def test_cached_public_loaders() -> None:
    """Cache growth and current interest quotes independently."""
    load_bitget_growth.clear()
    load_bitget_rate.clear()
    with (
        patch(
            "gui_calculator.bitget_margin.fetch_growth", return_value=()
        ) as growth,
        patch(
            "gui_calculator.bitget_margin.fetch_rate",
            return_value=LoanRate(timestamp=STAMP, daily=0.001, annual=0.365),
        ) as rate,
    ):
        assert load_bitget_growth("BTC", period="24h") == ()
        assert load_bitget_rate("BTC").timestamp == STAMP
    growth.assert_called_once_with("BTC", period="24h")
    rate.assert_called_once_with("BTC")
    load_bitget_growth.clear()
    load_bitget_rate.clear()


@pytest.mark.parametrize(
    "scenario", ["normal", "empty", "growth-error", "price-error", "rate-error"]
)
def test_snapshot_bitget_chart(scenario: str) -> None:
    """Exclude future growth and tolerate partial feed failures."""
    history = tuple(
        Growth(timestamp=STAMP + timedelta(days=i), growth=1)
        for i in range(-29, 2)
    )
    with (
        patch(
            "gui_calculator.bitget_view.load_bitget_growth",
            return_value=() if scenario == "empty" else history,
            side_effect=(
                requests.ConnectionError("offline")
                if scenario == "growth-error"
                else None
            ),
        ),
        patch(
            "gui_calculator.bitget_view.load_price_history",
            return_value=(),
            side_effect=(
                ValueError("bad price") if scenario == "price-error" else None
            ),
        ),
        patch(
            "gui_calculator.bitget_view.load_bitget_rate",
            return_value=LoanRate(
                timestamp=STAMP + timedelta(days=1), daily=0.001, annual=0.365
            ),
            side_effect=(
                ValueError("bad rate") if scenario == "rate-error" else None
            ),
        ),
        patch("gui_calculator.bitget_view.add_oscillator_trace") as trace,
    ):
        app = AppTest.from_string(APP).run()
    assert not app.exception
    assert len(app.get("iframe")) == 1
    times = cast("list[datetime]", trace.call_args.args[1])
    assert all(time <= STAMP for time in times)
    if scenario in {"empty", "growth-error"}:
        assert not times
        assert app.info
    else:
        assert times[-1] == STAMP
        assert all(
            value == pytest.approx(100)
            for value in cast("list[float | None]", trace.call_args.args[2])
        )
    if scenario.endswith("error"):
        assert app.warning
    if scenario != "rate-error":
        assert any(
            "excluded from historical" in str(caption.value)
            for caption in app.caption
        )


def test_live_bitget_without_options() -> None:
    """Load public live lending without options or credentials."""
    with (
        patch(
            "gui_calculator.bitget_view.load_bitget_growth", return_value=()
        ) as growth,
        patch("gui_calculator.bitget_view.load_price_history", return_value=()),
        patch(
            "gui_calculator.bitget_view.load_bitget_rate",
            side_effect=ValueError("offline"),
        ),
    ):
        app = AppTest.from_string(
            "from gui_calculator.bitget_view import render_live_bitget\n"
            'render_live_bitget("ETH")\n'
        ).run()
        assert not app.exception
        growth.assert_called_with("ETH", period="24h")
        _ = app.selectbox[0].select("30 days").run()
        assert not app.exception
        growth.assert_called_with("ETH", period="30d")


def test_snapshot_defaults_to_public_bitget() -> None:
    """Dispatch the GEX toggle to Bitget without requesting legacy feeds."""
    with (
        patch("gui_calculator.snapshot_margin.render_latest_bitget") as render,
        patch(
            "gui_calculator.snapshot_margin.load_public_margin_history"
        ) as legacy,
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import EXAMPLE\n"
            "from snapshot_tunnel.options_model import parse_snapshots\n"
            "from gui_calculator.snapshot_margin import"
            " render_snapshot_margin\n"
            "render_snapshot_margin(parse_snapshots(EXAMPLE)[0])\n"
        ).run()
        render.assert_not_called()
        _ = app.toggle[0].set_value(True).run()
        assert not app.exception
        assert app.selectbox[1].value == "Bitget public loan growth"
        assert render.call_args.kwargs == {"days": 1}
        legacy.assert_not_called()


def test_latest_margin_advances_past_options_snapshot() -> None:
    """Live lending includes new observations without recollecting options."""
    with patch("gui_calculator.bitget_view.render_bitget_margin") as render:
        app = AppTest.from_string(
            APP.replace("render_bitget_margin", "render_latest_bitget")
        ).run()
    assert not app.exception
    current = cast("Snapshot", render.call_args.args[0])
    assert current.timestamp > STAMP
    assert current.asset == "BTC"
    assert render.call_args.kwargs == {"days": 7}


def test_latest_mode_dispatches_live_margin() -> None:
    """Latest options mode refreshes lending independently of its snapshot."""
    with (
        patch("gui_calculator.snapshot_margin.render_latest_bitget") as live,
        patch("gui_calculator.snapshot_margin.render_bitget_margin") as saved,
    ):
        app = AppTest.from_string(
            "import streamlit as st\n"
            'st.session_state["options_data_source"] = '
            '"Deribit API (latest snapshot)"\n'
            "from gui_calculator.options_gex import EXAMPLE\n"
            "from snapshot_tunnel.options_model import parse_snapshots\n"
            "from gui_calculator.snapshot_margin import "
            "render_snapshot_margin\n"
            "render_snapshot_margin(parse_snapshots(EXAMPLE)[0])\n"
        ).run()
        _ = app.toggle[0].set_value(True).run()
    assert not app.exception
    live.assert_called_once()
    assert live.call_args.kwargs == {"days": 1}
    saved.assert_not_called()


def test_margin_can_select_historical_cutoff() -> None:
    """Allow historical inspection without silently replacing its cutoff."""
    with (
        patch("gui_calculator.snapshot_margin.render_latest_bitget") as live,
        patch("gui_calculator.snapshot_margin.render_bitget_margin") as saved,
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import EXAMPLE\n"
            "from snapshot_tunnel.options_model import parse_snapshots\n"
            "from gui_calculator.snapshot_margin import"
            " render_snapshot_margin\n"
            "render_snapshot_margin(parse_snapshots(EXAMPLE)[0])\n"
        ).run()
        _ = app.toggle[0].set_value(True).run()
        assert live.call_args.kwargs == {"days": 1}
        _ = app.selectbox[2].select("Selected options snapshot").run()
        assert not app.exception
        saved.assert_called_once()
        _ = app.selectbox[0].select("Week").run()
        assert saved.call_args.kwargs == {"days": 7}


def test_manual_refresh_fetches_new_growth_through_real_cache() -> None:
    """Bypass cached lending without requesting another options snapshot."""
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    old = tuple(
        Growth(timestamp=end - timedelta(hours=i), growth=1)
        for i in range(26, 1, -1)
    )
    fresh = (*old, Growth(timestamp=end - timedelta(hours=1), growth=-1))
    load_bitget_growth.clear()
    load_bitget_rate.clear()
    with (
        patch(
            "gui_calculator.bitget_margin.fetch_growth",
            side_effect=[old, fresh],
        ) as growth,
        patch(
            "gui_calculator.bitget_margin.fetch_rate",
            return_value=LoanRate(timestamp=end, daily=0.001, annual=0.365),
        ) as rate,
        patch("gui_calculator.bitget_view.load_price_history", return_value=()),
        patch("gui_calculator.bitget_view.add_oscillator_trace") as trace,
    ):
        app = AppTest.from_string(
            "from datetime import UTC, datetime\n"
            "from snapshot_tunnel.options_model import Snapshot\n"
            "from gui_calculator.bitget_view import render_bitget_margin\n"
            "render_bitget_margin(Snapshot(timestamp=datetime.now(UTC),"
            'asset="BTC", spot=1, options=()), days=1)\n'
        ).run()
        assert not app.exception
        assert trace.call_args.args[1][-1] == old[-1].timestamp
        _ = app.run()
        growth.assert_called_once_with("BTC", period="24h")
        _ = app.button[0].click().run()
        assert not app.exception
        assert trace.call_args.args[1][-1] == fresh[-1].timestamp
        expected_requests = 2
        assert growth.call_count == expected_requests
        assert rate.call_count == expected_requests
    load_bitget_growth.clear()
    load_bitget_rate.clear()
