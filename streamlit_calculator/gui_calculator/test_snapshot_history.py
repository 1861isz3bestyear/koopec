# Copyright 2026 anchored-vwam-backtest contributors
"""Verify independent archive valuations and optional timeline controls."""

from dataclasses import replace
from datetime import timedelta

import pandas as pd
import pytest
from snapshot_tunnel.options_model import net_exposure, parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.snapshot_history_view import snapshot_history


def test_history_uses_each_chain_and_preserves_missing_levels() -> None:
    """Changed spot and OI affect history without carrying earlier levels."""
    first = parse_snapshots(EXAMPLE)[0]
    later = replace(
        first,
        timestamp=first.timestamp + timedelta(hours=1),
        spot=first.spot * 1.1,
        options=tuple(
            replace(option, open_interest=option.open_interest * 2)
            for option in first.options
            if option.side == "call"
        ),
    )
    history = snapshot_history((later, first))
    assert list(history["Price"]) == [first.spot, later.spot]
    assert list(history["Net GEX"]) == pytest.approx([
        net_exposure(first, first.spot),
        net_exposure(later, later.spot),
    ])
    assert pd.isna(history.loc[1, "Put 1"])
    assert pd.isna(history.loc[1, "Put 2"])
    assert pd.isna(history.loc[1, "Gamma flip"])
    assert not pd.isna(history.loc[0, "Put 1"])
    assert not pd.isna(history.loc[1, "Call 1"])


def test_archive_chart_selection() -> None:
    """The chart is opt-in and supports multiple, single and no selections."""
    app = AppTest.from_string(
        "from dataclasses import replace\nfrom datetime import timedelta\nfrom"
        " gui_calculator.options_gex import EXAMPLE\nfrom"
        " snapshot_tunnel.options_model import parse_snapshots\nfrom"
        " gui_calculator.snapshot_history_view import"
        " render_snapshot_history\nfirst = parse_snapshots(EXAMPLE)[0]\nlater ="
        " replace(first, timestamp=first.timestamp +"
        " timedelta(hours=1))\nrender_snapshot_history((first, later))\n"
    ).run()
    assert not app.exception
    assert not app.get("plotly_chart")
    _ = app.toggle[0].set_value(True).run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == len(app.selectbox)
    assert app.selectbox[0].label == "Archive day (UTC)"
    assert len(app.dataframe[0].value) == len(app.multiselect[0].options)
    _ = app.multiselect[0].set_value([1]).run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 1
    _ = app.multiselect[0].set_value([]).run()
    assert not app.exception
    assert not app.get("plotly_chart")
    assert app.info


def test_daily_scope_filters_utc_day_and_keeps_archive() -> None:
    """Switch days without changing the overview, including a singleton day."""
    app = AppTest.from_string(
        "from dataclasses import replace\nfrom datetime import timedelta\nfrom"
        " gui_calculator.options_gex import EXAMPLE\nfrom"
        " snapshot_tunnel.options_model import parse_snapshots\nfrom"
        " gui_calculator.snapshot_history_view import"
        " render_snapshot_history\nfirst = parse_snapshots(EXAMPLE)[0]\nfirst ="
        " replace(first, timestamp=first.timestamp.replace(hour=0))\nsecond ="
        " replace(first, timestamp=first.timestamp + timedelta(hours=1))\nthird"
        " = replace(first, timestamp=first.timestamp +"
        " timedelta(days=1))\nrender_snapshot_history((first, second, third))\n"
    ).run()
    _ = app.toggle[0].set_value(True).run()
    assert not app.exception
    assert len(app.dataframe[0].value) == len(app.multiselect[0].options)
    assert len(app.selectbox[1].options) == 1
    _ = app.selectbox[0].select_index(0).run()
    assert not app.exception
    assert len(app.selectbox[1].options) == len(app.multiselect[0].options) - 1
    assert len(app.dataframe[0].value) == len(app.multiselect[0].options)
    _ = app.multiselect[0].set_value([2]).run()
    assert not app.exception
    assert len(app.selectbox[0].options) == 1
    assert len(app.selectbox[1].options) == 1
