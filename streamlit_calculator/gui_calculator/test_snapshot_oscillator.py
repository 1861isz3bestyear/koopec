# Copyright 2026 anchored-vwam-backtest contributors
"""Verify recorded depth rates, causal windows and optional snapshot charts."""

from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import ANY, patch

import pandas as pd
import pytest
import requests
from shared.order_book import BookLevel, BookSnapshot
from snapshot_tunnel.options_model import CandleClose, parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.snapshot_oscillator import (
    limit_order_oscillator_rate,
    load_limit_order_history,
    load_price_history,
)

if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.usefixtures("isolated_depth_history")


@pytest.fixture
def isolated_depth_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep oscillator control tests independent of the user's database."""
    from functools import partial

    from gui_calculator.options_store import load_snapshots

    monkeypatch.setattr(
        "gui_calculator.snapshot_oscillator.load_snapshots",
        partial(load_snapshots, path=tmp_path / "options.sqlite"),
    )


@pytest.mark.parametrize(
    ("bid", "ask", "expected"), [(3, 1, 75), (1, 3, 25), (1, 1, 50)]
)
def test_limit_order_rate(bid: int, ask: int, expected: int) -> None:
    """Quote notional, rather than base quantity or momentum, sets the rate."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    book = BookSnapshot(
        observed=snapshot.timestamp,
        available=snapshot.timestamp,
        bids=(BookLevel(price=100, quantity=bid),),
        asks=(BookLevel(price=200, quantity=ask / 2),),
    )
    assert limit_order_oscillator_rate(book) == expected
    assert (
        limit_order_oscillator_rate(
            replace(
                book,
                bids=(*book.bids, *book.bids),
                asks=(*book.asks, *book.asks),
            )
        )
        == expected
    )
    with pytest.raises(ValueError, match="notional"):
        _ = limit_order_oscillator_rate(replace(book, bids=(), asks=()))
    with pytest.raises(ValueError, match="notional"):
        _ = limit_order_oscillator_rate(
            replace(book, bids=(BookLevel(price=float("inf"), quantity=1),))
        )


def test_book_history_window_and_receipt_causality() -> None:
    """Exclude future receipts, stale depth and books outside the window."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    content = "time,available_at,side,price,quantity\n"
    for offset, latency in [(-8 * 24 * 3600, 0), (-60, 11), (-30, 1), (0, 1)]:
        observed = snapshot.timestamp + timedelta(seconds=offset)
        available = observed + timedelta(seconds=latency)
        for side, price in [("bid", 100), ("ask", 101)]:
            content += f"{observed.isoformat()},{available.isoformat()},"
            content += f"{side},{price},1\n"
    books = load_limit_order_history(content, snapshot, days=7)
    assert len(books) == 1
    assert books[0].available == snapshot.timestamp - timedelta(seconds=29)
    assert [
        book.available
        for book in load_limit_order_history(content, snapshot, days=30)
    ] == [snapshot.timestamp - timedelta(days=8), books[0].available]
    with pytest.raises(ValueError, match="columns"):
        _ = load_limit_order_history("time,close\n", snapshot, days=7)


def test_history_uses_selected_asset_and_excludes_open_candles() -> None:
    """Fetch selected price history and exclude incomplete future candles."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], asset="ETH")
    hour = snapshot.timestamp.replace(minute=0, second=0, microsecond=0)
    frame = pd.DataFrame({
        "time": [hour - timedelta(hours=1), hour],
        "close": [3000, 4000],
    })
    with patch(
        "gui_calculator.snapshot_price_data.fetch_bybit_klines",
        return_value=frame,
    ) as fetch:
        load_price_history.clear()
        candles = load_price_history(snapshot, days=30)
    assert candles == (CandleClose(timestamp=hour, close=3000),)
    fetch.assert_called_once_with(
        "ETHUSDT",
        "1h",
        start_ms=int(
            (snapshot.timestamp - timedelta(days=30)).timestamp() * 1000
        ),
        end_ms=int(snapshot.timestamp.timestamp() * 1000),
    )
    with patch(
        "gui_calculator.snapshot_price_data.fetch_bybit_klines",
        return_value=pd.DataFrame(),
    ):
        load_price_history.clear()
        assert not load_price_history(snapshot, days=7)
    load_price_history.clear()


@pytest.mark.parametrize("failure", [False, True])
def test_chart_controls_and_feed_failure(*, failure: bool) -> None:
    """Opt in to week/month charts; outages stay within the oscillator panel."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    candles = tuple(
        CandleClose(
            timestamp=snapshot.timestamp - timedelta(hours=20 - index),
            close=100 + index,
        )
        for index in range(20)
    )
    script = (
        "from gui_calculator.options_gex import EXAMPLE\n"
        "from snapshot_tunnel.options_model import parse_snapshots\n"
        "from gui_calculator.snapshot_oscillator import "
        "render_snapshot_oscillator\n"
        "render_snapshot_oscillator(parse_snapshots(EXAMPLE)[0])\n"
    )
    with patch(
        "gui_calculator.snapshot_oscillator.load_price_history",
        return_value=candles,
        side_effect=requests.Timeout("offline") if failure else None,
    ) as fetch:
        app = AppTest.from_string(script).run()
        fetch.assert_not_called()
        _ = app.toggle[0].set_value(True).run()
        fetch.assert_called_with(snapshot, days=7)
        assert not app.exception
        if failure:
            assert "offline" in app.warning[0].value
        else:
            assert len(app.get("iframe")) == 1
            _ = app.selectbox[0].select("Month").run()
            fetch.assert_called_with(snapshot, days=30)
            assert not app.exception


@pytest.mark.parametrize("content", ["valid", "invalid", "overflow"])
def test_uploaded_depth_chart(content: str) -> None:
    """Plot actual uploaded notionals and contain malformed depth errors."""
    from gui_calculator.live_oscillators import add_oscillator_trace

    snapshot = parse_snapshots(EXAMPLE)[0]
    stamp = snapshot.timestamp.isoformat()
    quantity = "1e308" if content == "overflow" else "3"
    csv = (
        "time,available_at,side,price,quantity\n"
        f"{stamp},{stamp},bid,100,{quantity}\n"
        f"{stamp},{stamp},ask,200,0.5\n"
    )
    uploaded = BytesIO(("invalid" if content == "invalid" else csv).encode())
    with (
        patch("streamlit.file_uploader", return_value=uploaded),
        patch(
            "gui_calculator.snapshot_oscillator.load_price_history",
            return_value=(),
        ),
        patch(
            "gui_calculator.snapshot_oscillator.add_oscillator_trace",
            wraps=add_oscillator_trace,
        ) as trace,
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import EXAMPLE\n"
            "from snapshot_tunnel.options_model import parse_snapshots\n"
            "from gui_calculator.snapshot_oscillator import "
            "render_snapshot_oscillator\n"
            "render_snapshot_oscillator(parse_snapshots(EXAMPLE)[0])\n"
        ).run()
        _ = app.toggle[0].set_value(True).run()
    assert not app.exception
    if content == "valid":
        trace.assert_called_once_with(ANY, [snapshot.timestamp], [75.0])
        assert len(app.get("iframe")) == 1
        assert "limit_order_oscillator_rate" in app.caption[0].value
    else:
        trace.assert_not_called()
        assert "unavailable" in app.warning[0].value


def test_empty_history_status() -> None:
    """No data produces an empty chart with an explicit status."""
    with patch(
        "gui_calculator.snapshot_oscillator.load_price_history", return_value=()
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import EXAMPLE\n"
            "from snapshot_tunnel.options_model import parse_snapshots\n"
            "from gui_calculator.snapshot_oscillator import "
            "render_snapshot_oscillator\n"
            "render_snapshot_oscillator(parse_snapshots(EXAMPLE)[0])\n"
        ).run()
        _ = app.toggle[0].set_value(True).run()
    assert not app.exception
    assert "No recorded limit-order depth" in app.info[0].value
    assert "No completed price candles" in app.info[1].value


@pytest.mark.parametrize(
    "source",
    [
        "Deribit API (latest snapshot)",
        "Saved history / Deribit API",
        "Synthetic demo",
    ],
)
def test_latest_snapshot_connects_oscillator(source: str) -> None:
    """The current-chain view passes its selected snapshot to the chart."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    with (
        patch(
            "gui_calculator.options_gex.render_snapshot_request",
            return_value=snapshot,
        ),
        patch("gui_calculator.options_gex._render_profile"),
        patch("gui_calculator.options_gex.render_expiry_impact"),
        patch("gui_calculator.options_gex.render_previous_day_comparison"),
        patch("gui_calculator.options_gex.render_snapshot_dashboard") as render,
    ):
        app = AppTest.from_string(
            "import streamlit as st\n"
            "from gui_calculator.options_gex import render_options_gex\n"
            f"st.session_state['options_data_source'] = {source!r}\n"
            "render_options_gex()\n"
        ).run()
    assert not app.exception
    assert not app.toggle
    assert not app.radio
    assert all(
        heading.value != "Live market oscillators" for heading in app.subheader
    )
    if source in {
        "Deribit API (latest snapshot)",
        "Saved history / Deribit API",
    }:
        render.assert_called_once_with(snapshot)
    else:
        render.assert_not_called()


def test_saved_depth_populates_chart_without_upload() -> None:
    """The GEX oscillator automatically renders depth saved with snapshots."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    book = BookSnapshot(
        observed=snapshot.timestamp,
        available=snapshot.timestamp,
        bids=(BookLevel(price=100, quantity=3),),
        asks=(BookLevel(price=200, quantity=0.5),),
    )
    with (
        patch(
            "gui_calculator.snapshot_oscillator.load_snapshots",
            return_value=(replace(snapshot, order_book=book),),
        ),
        patch(
            "gui_calculator.snapshot_oscillator.load_price_history",
            return_value=(),
        ),
        patch(
            "gui_calculator.snapshot_oscillator.add_oscillator_trace"
        ) as trace,
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import EXAMPLE\n"
            "from snapshot_tunnel.options_model import parse_snapshots\n"
            "from gui_calculator.snapshot_oscillator import"
            " render_snapshot_oscillator\n"
            "render_snapshot_oscillator(parse_snapshots(EXAMPLE)[0])\n"
        ).run()
        _ = app.toggle[0].set_value(True).run()
    assert not app.exception
    trace.assert_called_once_with(ANY, [snapshot.timestamp], [75.0])
    assert len(app.get("iframe")) == 1
    assert all(
        "No recorded limit-order depth" not in item.value for item in app.info
    )
