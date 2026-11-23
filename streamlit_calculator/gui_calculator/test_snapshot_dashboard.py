# Copyright 2026 anchored-vwam-backtest contributors
"""Check shared snapshot cutoffs and independent source failures."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import plotly.graph_objects as go
import pytest
import requests
from shared.validation import json_object, object_list, object_mapping
from snapshot_tunnel.bitget import Growth
from snapshot_tunnel.options_model import CandleClose, parse_snapshots

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.snapshot_dashboard import (
    render_dashboard_window as render_snapshot_dashboard,
)
from gui_calculator.test_oi_divergence import market_samples


@pytest.mark.parametrize(
    "source", ["Bitget public loan growth", "OKX ratio / recorded balances"]
)
@pytest.mark.parametrize(
    "timing", ["Latest available", "Selected options snapshot"]
)
def test_dashboard_source_cutoff_and_shared_axes(
    source: str, timing: str
) -> None:
    """Keep future lending out and all four panels on the same window."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    cutoff = (
        datetime.now(UTC)
        if timing == "Latest available"
        else snapshot.timestamp
    )
    charts: list[go.Figure] = []

    def capture(chart: go.Figure, *, use_container_width: bool) -> None:
        assert use_container_width
        charts.append(chart)

    future = Growth(
        timestamp=snapshot.timestamp + timedelta(hours=1), growth=99
    )
    current = Growth(timestamp=snapshot.timestamp, growth=1)
    with (
        patch(
            "gui_calculator.snapshot_dashboard.datetime",
            new=SimpleNamespace(now=Mock(return_value=cutoff)),
        ),
        patch(
            "gui_calculator.snapshot_dashboard.st.plotly_chart",
            side_effect=capture,
        ),
        patch("gui_calculator.snapshot_dashboard.st.toggle", return_value=True),
        patch(
            "gui_calculator.snapshot_dashboard.st.selectbox",
            side_effect=["Week", timing, source],
        ),
        patch(
            "gui_calculator.snapshot_dashboard.st.file_uploader",
            return_value=None,
        ),
        patch(
            "gui_calculator.snapshot_dashboard.st.number_input",
            return_value=0.1,
        ),
        patch("gui_calculator.snapshot_dashboard.st.caption") as caption,
        patch("gui_calculator.snapshot_dashboard.st.info"),
        patch(
            "gui_calculator.snapshot_dashboard.saved_depth_history",
            return_value=(),
        ),
        patch(
            "gui_calculator.snapshot_dashboard.load_price_history",
            return_value=(
                CandleClose(timestamp=snapshot.timestamp, close=100),
            ),
        ),
        patch(
            "gui_calculator.snapshot_dashboard.load_bitget_growth",
            return_value=(current, future),
        ),
        patch(
            "gui_calculator.snapshot_dashboard.load_public_margin_history",
            return_value=(),
        ),
        patch(
            "gui_calculator.snapshot_dashboard.load_snapshot_oi",
            return_value=market_samples(),
        ),
    ):
        render_snapshot_dashboard(snapshot)
    assert len(charts) == 1
    if source == "Bitget public loan growth":
        captions = [
            str(cast("object", call.args[0])) for call in caption.call_args_list
        ]
        assert any("update daily" in text for text in captions)
        latest = future if timing == "Latest available" else current
        assert any(
            f"Latest margin observation: {latest.timestamp.isoformat()}" in text
            for text in captions
        )
    chart = charts[0]
    assert isinstance(chart, go.Figure)
    layout = object_mapping(json_object(chart.to_json())["layout"])
    for key in ("xaxis", "xaxis2", "xaxis3", "xaxis4"):
        axis = object_mapping(layout[key])
        assert axis["matches"] == "x"
        end = datetime.fromisoformat(str(object_list(axis["range"])[1]))
        assert end == cutoff
        assert datetime.fromisoformat(str(object_list(axis["range"])[0])) == (
            end - timedelta(days=7)
        )
    assert {
        trace.xaxis for trace in chart.data if isinstance(trace, go.Scatter)
    } == {"x"}
    assert layout["hoversubplots"] == "axis"
    marker = object_mapping(object_list(layout["shapes"])[0])
    assert marker["yref"] == "paper"
    assert marker["x0"] == snapshot.timestamp.isoformat()
    assert (
        timing == "Latest available" and source == "Bitget public loan growth"
    ) == any(
        future.timestamp in trace.x
        for trace in chart.data
        if isinstance(trace, go.Scatter)
    )
    assert {
        trace.yaxis for trace in chart.data if isinstance(trace, go.Scatter)
    } == {"y", "y2", "y3", "y4"}


def test_price_failure_preserves_other_panels() -> None:
    """A failed price source must not prevent the other loaders or chart."""
    charts: list[go.Figure] = []

    def capture(chart: go.Figure, *, use_container_width: bool) -> None:
        assert use_container_width
        charts.append(chart)

    with (
        patch(
            "gui_calculator.snapshot_dashboard.st.plotly_chart",
            side_effect=capture,
        ),
        patch("gui_calculator.snapshot_dashboard.st.toggle", return_value=True),
        patch(
            "gui_calculator.snapshot_dashboard.st.selectbox",
            return_value="Week",
        ),
        patch("gui_calculator.snapshot_dashboard.st.caption"),
        patch("gui_calculator.snapshot_dashboard.st.warning") as warning,
        patch(
            "gui_calculator.snapshot_dashboard._add_price",
            side_effect=requests.RequestException("offline"),
        ),
        patch("gui_calculator.snapshot_dashboard._add_limit_orders") as books,
        patch("gui_calculator.snapshot_dashboard._add_margin") as margin,
        patch("gui_calculator.snapshot_dashboard._add_oi") as oi,
    ):
        render_snapshot_dashboard(parse_snapshots(EXAMPLE)[0])
    warning.assert_called_once_with("Price unavailable: offline")
    books.assert_called_once()
    margin.assert_called_once()
    oi.assert_called_once()
    assert len(charts) == 1
