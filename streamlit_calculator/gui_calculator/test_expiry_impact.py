# Copyright 2026 anchored-vwam-backtest contributors
"""Verify expiry removal, cancellation and interactive scenarios."""

from dataclasses import replace
from datetime import timedelta

import pytest
from snapshot_tunnel.options_model import net_exposure, parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.expiry_view import (
    analyze_expiry,
    expiry_outlook,
    expiry_price_chart,
)
from gui_calculator.options_gex import EXAMPLE


def test_removal_conserves_signed_exposure_and_preserves_inputs() -> None:
    """Expiring and surviving partitions sum to the unchanged full chain."""
    original = parse_snapshots(EXAMPLE)[0]
    option = original.options[0]
    later = replace(option, expiry=option.expiry + timedelta(days=7))
    snapshot = replace(original, options=(*original.options, later))
    impact = analyze_expiry(snapshot, expiry=option.expiry)
    assert impact.remaining.options == (later,)
    assert impact.remaining.timestamp == snapshot.timestamp
    assert impact.remaining.spot == snapshot.spot
    assert 0 < impact.absolute_share < 1
    assert net_exposure(snapshot, snapshot.spot) == pytest.approx(
        net_exposure(impact.remaining, snapshot.spot)
        + net_exposure(impact.expiring, snapshot.spot)
    )
    chart = expiry_price_chart(impact)
    expected_scenarios = 2
    assert len(chart.data) == expected_scenarios
    assert snapshot.options == (*original.options, later)


def test_all_expiring_and_zero_oi() -> None:
    """An empty surviving chain has zero GEX; zero OI gives zero share."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    expiry = snapshot.options[0].expiry
    snapshot = replace(
        snapshot,
        options=tuple(o for o in snapshot.options if o.expiry == expiry),
    )
    impact = analyze_expiry(snapshot, expiry=expiry)
    assert impact.absolute_share == pytest.approx(1)
    assert not impact.remaining.options
    assert net_exposure(impact.remaining, snapshot.spot) == 0
    empty_oi = replace(
        snapshot,
        options=tuple(replace(o, open_interest=0) for o in snapshot.options),
    )
    assert analyze_expiry(empty_oi, expiry=expiry).absolute_share == 0
    for invalid in (snapshot.timestamp, expiry + timedelta(days=100)):
        with pytest.raises(ValueError, match="upcoming expiry"):
            _ = analyze_expiry(snapshot, expiry=invalid)


def test_expiry_controls_and_no_surviving_walls() -> None:
    """Changing expiry rerenders the scenario and reports missing walls."""
    app = AppTest.from_string(
        "from dataclasses import replace\n"
        "from datetime import timedelta\n"
        "import streamlit as st\n"
        "from gui_calculator.options_gex import EXAMPLE\n"
        "from snapshot_tunnel.options_model import parse_snapshots\n"
        "from gui_calculator.expiry_view import render_expiry_impact\n"
        "snapshot = parse_snapshots(EXAMPLE)[0]\n"
        "option = snapshot.options[0]\n"
        "snapshot = replace(snapshot, options=(option, replace(option, "
        "expiry=option.expiry + timedelta(days=7))))\n"
        "render_expiry_impact(snapshot, st)\n"
    ).run()
    assert not app.exception
    expected_charts = 2
    assert len(app.get("plotly_chart")) == expected_charts
    assert "nearest first" in app.selectbox[0].label
    _ = app.selectbox[0].select_index(1).run()
    assert not app.exception
    assert any("hours from snapshot" in item.value for item in app.caption)


def test_expiry_without_survivors_and_empty_chain_ui() -> None:
    """Report unavailable walls and an explicit empty-expiry message."""
    app = AppTest.from_string(
        "from dataclasses import replace\n"
        "import streamlit as st\n"
        "from gui_calculator.options_gex import EXAMPLE\n"
        "from snapshot_tunnel.options_model import parse_snapshots\n"
        "from gui_calculator.expiry_view import render_expiry_impact\n"
        "snapshot = parse_snapshots(EXAMPLE)[0]\n"
        "snapshot = replace(snapshot, options=(snapshot.options[0],))\n"
        "render_expiry_impact(snapshot, st)\n"
        "render_expiry_impact(replace(snapshot, options=()), st)\n"
    ).run()
    assert not app.exception
    table = app.dataframe[0].value
    assert table.iloc[1]["Call wall"] == "Unavailable"
    assert table.iloc[1]["Put wall"] == "Unavailable"
    assert table.iloc[1]["Net GEX (USD / 1%)"] == 0
    assert any("No upcoming expiries" in item.value for item in app.info)


def test_outlook_reports_removed_walls_and_gex() -> None:
    """Removing the only contract leaves no walls, GEX or flip."""
    original = parse_snapshots(EXAMPLE)[0]
    option = original.options[0]
    snapshot = replace(original, options=(option,))
    outlook = expiry_outlook(analyze_expiry(snapshot, expiry=option.expiry))
    assert "→ Unavailable" in outlook
    assert "→ $+0 / 1% move" in outlook
    assert "Nearest gamma flip: No crossing → No crossing" in outlook
    assert "spot ±20%" in outlook


def test_outlook_reports_surviving_wall() -> None:
    """The remaining call wall moves to the surviving contract's strike."""
    original = parse_snapshots(EXAMPLE)[0]
    option = replace(original.options[0], side="call", open_interest=1000)
    later = replace(
        option,
        strike=option.strike * 1.05,
        open_interest=1,
        expiry=option.expiry + timedelta(days=7),
    )
    snapshot = replace(original, options=(option, later))
    outlook = expiry_outlook(analyze_expiry(snapshot, expiry=option.expiry))
    assert f"Put wall: ${option.strike:,.2f} → ${later.strike:,.2f}" in outlook
    assert f"Call wall: ${later.strike:,.2f} → ${later.strike:,.2f}" in outlook
