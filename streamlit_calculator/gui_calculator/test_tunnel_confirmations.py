# Copyright 2026 anchored-vwam-backtest contributors
"""Check causal per-source timeline confirmations independently of entries."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
from shared.tunnel import TunnelSettings
from shared.validation import json_object, object_list, object_mapping
from snapshot_tunnel.tunnel_flow import OscillatorObservation, TunnelFlow

from gui_calculator.test_tunnel_strategy import price_frame
from gui_calculator.tunnel_confirmation_chart import add_tunnel_confirmations
from gui_calculator.tunnel_replay import replay_tunnel


def test_confirmation_timeline_without_plans() -> None:
    """Show independent votes even when missing GEX prevents every trade."""
    now = datetime(2026, 11, 1, 8, 15, tzinfo=UTC)
    flow = TunnelFlow(
        book=(OscillatorObservation(available=now, direction=1),),
        margin=(OscillatorObservation(available=now, direction=-1),),
        oi=(OscillatorObservation(available=now, direction=1),),
    )
    result = replay_tunnel(
        price_frame(),
        (),
        settings=TunnelSettings(use_margin=True),
        flow=flow,
    )
    assert result["options_direction"].eq(0).all()
    assert result["tunnel_confirmation_book"].tolist() == [0, 1, 1, 1]
    assert result["tunnel_confirmation_margin"].tolist() == [0, -1, -1, -1]
    assert "tunnel_confirmation_oi" not in result
    chart = go.Figure()
    add_tunnel_confirmations(chart, result, timezone=UTC)
    expected_traces = 6
    assert len(chart.data) == expected_traces
    traces = [
        object_mapping(item)
        for item in object_list(json_object(chart.to_json())["data"])
    ]
    assert traces[0]["name"] == "Limit-order confirms long"
    assert traces[0]["x"] == [
        "2026-11-01T08:15:00.000000",
        "2026-11-01T08:16:00.000000",
        "2026-11-01T08:17:00.000000",
    ]
    assert traces[3]["name"] == "Margin-loan confirms short"


def test_confirmation_freshness_and_warmup() -> None:
    """Never mark stale, future, neutral or uncalculatable evidence."""
    now = datetime(2026, 11, 1, tzinfo=UTC)
    flow = TunnelFlow(
        book=(OscillatorObservation(available=now, direction=1),),
        margin=(
            OscillatorObservation(
                available=now, direction=-1, calculatable=False
            ),
        ),
        oi=(OscillatorObservation(available=now, direction=0),),
    )
    settings = TunnelSettings(use_margin=True, use_oi=True)
    assert flow.confirmations(
        now - timedelta(seconds=1), settings=settings
    ) == {
        "tunnel_confirmation_book": 0,
        "tunnel_confirmation_margin": 0,
        "tunnel_confirmation_oi": 0,
    }
    assert flow.confirmations(now, settings=settings) == {
        "tunnel_confirmation_book": 1,
        "tunnel_confirmation_margin": 0,
        "tunnel_confirmation_oi": 0,
    }
    assert not any(
        flow.confirmations(
            now + settings.maximum_age + timedelta(seconds=1), settings=settings
        ).values()
    )
    chart = go.Figure()
    add_tunnel_confirmations(chart, pd.DataFrame(), timezone=UTC)
    assert not chart.data


def test_oi_confirmation_markers() -> None:
    """Render OI votes with the other confirmation sources switched off."""
    now = datetime(2026, 11, 1, 8, 15, tzinfo=UTC)
    result = replay_tunnel(
        price_frame(),
        (),
        settings=TunnelSettings(use_gex=False, use_book=False, use_oi=True),
        flow=TunnelFlow(
            oi=(
                OscillatorObservation(available=now, direction=-1),
                OscillatorObservation(
                    available=now + timedelta(minutes=1), direction=1
                ),
            )
        ),
    )
    assert result["tunnel_confirmation_oi"].tolist() == [0, -1, 1, 1]
    assert "tunnel_confirmation_book" not in result
    chart = go.Figure()
    add_tunnel_confirmations(chart, result, timezone=UTC)
    names = [
        object_mapping(item)["name"]
        for item in object_list(json_object(chart.to_json())["data"])
    ]
    assert names == [
        "OI divergence confirms long",
        "OI divergence confirms short",
    ]
