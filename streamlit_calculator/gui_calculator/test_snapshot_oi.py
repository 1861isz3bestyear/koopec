# Copyright 2026 anchored-vwam-backtest contributors
"""Verify snapshot-scoped OI downloads and the native binary-state GUI."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import requests
from shared.validation import json_object, object_list, object_mapping
from snapshot_tunnel.oi_divergence import divergence_series
from snapshot_tunnel.options_model import CandleClose, parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.snapshot_oi import oi_state_chart
from gui_calculator.snapshot_oi_data import (
    fetch_interest_history,
    load_snapshot_oi,
    parse_interest_page,
)
from gui_calculator.test_oi_divergence import market_samples

if TYPE_CHECKING:
    from datetime import datetime


_SCRIPT = (
    "from gui_calculator.options_gex import EXAMPLE\n"
    "from snapshot_tunnel.options_model import parse_snapshots\n"
    "from gui_calculator.snapshot_oi import render_snapshot_oi\n"
    "render_snapshot_oi(parse_snapshots(EXAMPLE)[0])\n"
)


def _page(times: tuple[datetime, ...], *, cursor: str = "") -> str:
    """Serialize a descending Bybit response fixture.

    Returns:
        JSON with hourly OI and cursor metadata.

    """
    return json.dumps({
        "retCode": 0,
        "result": {
            "list": [
                {
                    "timestamp": str(int(time.timestamp() * 1000)),
                    "openInterest": "100",
                }
                for time in times
            ],
            "nextPageCursor": cursor,
        },
    })


def test_paginated_asset_and_snapshot_bounds() -> None:
    """Keep all pages within the selected asset and availability window."""
    snapshot = replace(parse_snapshots(EXAMPLE)[0], asset="ETH")
    end = snapshot.timestamp.replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(hours=1)
    payload = _page((end, end - timedelta(hours=1)), cursor="next")
    first, cursor = parse_interest_page(payload)
    assert cursor == "next"
    assert len(first) == len((0, 1))
    with (
        requests.Session() as session,
        patch.object(
            session,
            "get",
            side_effect=[
                MagicMock(text=payload),
                MagicMock(text=_page((end - timedelta(hours=2),))),
            ],
        ) as get,
    ):
        samples = fetch_interest_history(session, snapshot, days=7)
        assert [sample.timestamp for sample in samples] == [
            end - timedelta(hours=value) for value in (2, 1, 0)
        ]
        get.assert_any_call(
            "https://api.bybit.com/v5/market/open-interest",
            params={
                "category": "linear",
                "symbol": "ETHUSDT",
                "intervalTime": "1h",
                "startTime": int(
                    (snapshot.timestamp - timedelta(days=7)).timestamp() * 1000
                ),
                "endTime": int(
                    (snapshot.timestamp - timedelta(minutes=1)).timestamp()
                    * 1000
                ),
                "limit": 200,
                "cursor": "next",
            },
            timeout=30,
        )


@pytest.mark.parametrize(
    "payload",
    [
        '{"retCode":10006,"retMsg":"rate limited"}',
        '{"retCode":0,"result":{"list":null}}',
        '{"retCode":0,"result":{"list":[{"timestamp":"1","openInterest":"2"}]}}',
        '{"retCode":0,"result":{"list":[{"timestamp":"3600000","openInterest":"0"}]}}',
        '{"retCode":0,"result":{"list":[{"timestamp":"3600000","openInterest":"nan"}]}}',
        '{"retCode":0,"result":{"list":[],"nextPageCursor":2}}',
    ],
)
def test_invalid_interest_payloads(payload: str) -> None:
    """Reject exchange errors, malformed lists, values, times and cursors."""
    with pytest.raises((ValueError, TypeError)):
        _ = parse_interest_page(payload)


def test_pagination_failures_and_empty_history() -> None:
    """Reject repeated pages, cursors and out-of-window samples."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    end = snapshot.timestamp.replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(hours=1)
    with pytest.raises(ValueError, match="reverse chronological"):
        _ = parse_interest_page(_page((end, end)))
    for pages, message in (
        ([_page((end,), cursor="a"), _page((end,), cursor="b")], "overlap"),
        (
            [
                _page((end,), cursor="a"),
                _page((end - timedelta(hours=1),), cursor="a"),
            ],
            "repeated",
        ),
        ([_page((end + timedelta(days=2),))], "outside"),
        ([_page((end - timedelta(days=8),))], "outside"),
    ):
        with (
            requests.Session() as session,
            patch.object(
                session,
                "get",
                side_effect=[MagicMock(text=page) for page in pages],
            ),
            pytest.raises(ValueError, match=message),
        ):
            _ = fetch_interest_history(session, snapshot, days=7)
    with (
        requests.Session() as session,
        patch.object(
            session,
            "get",
            return_value=MagicMock(text=_page(())),
        ),
    ):
        assert not fetch_interest_history(session, snapshot, days=7)
    with (
        requests.Session() as session,
        patch.object(
            session,
            "get",
            side_effect=requests.Timeout("offline"),
        ),
        pytest.raises(requests.Timeout),
    ):
        _ = fetch_interest_history(session, snapshot, days=7)


def test_exact_candle_join_and_extra_initialization() -> None:
    """Only exact completed closes match; missing prices are never filled."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    samples = market_samples()[:3]
    candles = tuple(
        CandleClose(timestamp=sample.interest.timestamp, close=sample.price)
        for sample in samples[:2]
    )
    load_snapshot_oi.clear()
    with (
        patch(
            "gui_calculator.snapshot_oi_data.fetch_interest_history",
            return_value=tuple(sample.interest for sample in samples),
        ) as fetch,
        patch(
            "gui_calculator.snapshot_oi_data.load_price_history",
            return_value=candles,
        ) as prices,
    ):
        assert load_snapshot_oi(snapshot, days=7) == samples[:2]
        fetch.assert_called_once()
        initialized_days = 9
        assert fetch.call_args.kwargs["days"] == initialized_days
        prices.assert_called_once_with(snapshot, days=9)
    load_snapshot_oi.clear()


def test_native_chart_state_and_gap_rendering() -> None:
    """Use binary steps at detection times with gaps and hover context."""
    samples = market_samples()
    second = replace(
        samples[0],
        interest=replace(
            samples[0].interest,
            timestamp=samples[-1].interest.timestamp + timedelta(hours=3),
        ),
    )
    series = divergence_series((*samples, second))
    snapshot = replace(
        parse_snapshots(EXAMPLE)[0],
        timestamp=second.interest.timestamp + timedelta(minutes=1),
    )
    payload = json_object(oi_state_chart(series, snapshot, days=7).to_json())
    data = [object_mapping(trace) for trace in object_list(payload["data"])]
    trace = data[2]
    assert object_mapping(trace["line"])["shape"] == "hv"
    assert trace["connectgaps"] is False
    states = object_list(trace["y"])
    assert states[:22] == [None] * 22
    assert states[22:26] == [0] * 4
    assert states[26] == 1
    assert states[-2:] == [None, None]
    layout = object_mapping(payload["layout"])
    assert object_mapping(layout["yaxis3"])["tickvals"] == [0, 1]
    markers = data[3]
    assert object_list(markers["x"]) == [
        series.signals[-1].detected.isoformat()
    ]
    assert "Price swing" in str(markers["text"])
    assert "Detected" in str(markers["text"])
    empty = oi_state_chart(divergence_series(()), snapshot, days=1)
    assert object_list(json_object(empty.to_json())["data"])


@pytest.mark.parametrize("mode", ["signals", "empty", "failure", "stale"])
def test_opt_in_gui_controls_and_unavailable_data(mode: str) -> None:
    """Render an opt-in native chart with binary status or clear errors."""
    samples = market_samples() if mode in {"signals", "stale"} else ()
    if mode == "signals" and samples:
        shift = (
            parse_snapshots(EXAMPLE)[0].timestamp
            - samples[-1].interest.timestamp
            - timedelta(minutes=1)
        )
        samples = tuple(
            replace(
                sample,
                interest=replace(
                    sample.interest, timestamp=sample.interest.timestamp + shift
                ),
            )
            for sample in samples
        )
    with patch(
        "gui_calculator.snapshot_oi.load_snapshot_oi",
        return_value=samples,
        side_effect=requests.Timeout("offline") if mode == "failure" else None,
    ) as load:
        app = AppTest.from_string(_SCRIPT).run()
        load.assert_not_called()
        _ = app.toggle[0].set_value(True).run()
        assert not app.exception
        load.assert_called_with(parse_snapshots(EXAMPLE)[0], days=7)
        if mode == "failure":
            assert "offline" in app.warning[0].value
            assert not app.get("plotly_chart")
            return
        assert len(app.get("plotly_chart")) == 1
        assert not app.get("iframe")
        expected = {
            "signals": "1",
            "empty": "No signal yet",
            "stale": "Unavailable (data gap)",
        }
        assert app.metric[0].value == expected[mode]
        if mode == "empty":
            assert "No qualifying" in app.info[0].value
        _ = app.selectbox[0].select("Month").run()
        load.assert_called_with(parse_snapshots(EXAMPLE)[0], days=30)
        _ = app.selectbox[0].select("24 hours").run()
        load.assert_called_with(parse_snapshots(EXAMPLE)[0], days=1)
        _ = app.number_input[1].set_value(100.0).run()
        assert app.metric[0].value == (
            "Unavailable (data gap)" if mode == "stale" else "No signal yet"
        )
        assert not app.exception
