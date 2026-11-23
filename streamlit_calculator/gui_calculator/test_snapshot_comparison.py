# Copyright 2026 anchored-vwam-backtest contributors
"""Verify snapshot comparisons conserve exposure and preserve unknown groups."""

from dataclasses import replace
from datetime import timedelta
from typing import Literal

import pandas as pd
import pytest
from shared.validation import json_object, object_list, object_mapping
from snapshot_tunnel.options_model import net_exposure, parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.comparison_view import (
    compare_breakdown,
    comparison_summary,
    exposure_breakdown,
    regime_chart,
)
from gui_calculator.options_gex import EXAMPLE


@pytest.mark.parametrize("scope", ["Strike", "Expiry"])
def test_breakdowns_conserve_gex_and_leave_missing_groups_blank(
    scope: Literal["Strike", "Expiry"],
) -> None:
    """Both aggregations reconcile to total GEX; absence is not zero OI."""
    before = parse_snapshots(EXAMPLE)[0]
    after = replace(
        before,
        timestamp=before.timestamp + timedelta(hours=1),
        options=(replace(before.options[0], open_interest=0),),
    )
    table = exposure_breakdown(before, scope=scope)
    assert table["Net GEX"].sum() == pytest.approx(
        net_exposure(before, before.spot)
    )
    compared = compare_breakdown(before, after, scope=scope)
    remaining = (
        after.options[0].strike
        if scope == "Strike"
        else after.options[0].expiry.isoformat()
    )
    assert (
        compared.loc[compared.index == remaining, "After Net GEX"].eq(0).all()
    )
    missing = compared.drop(index=remaining)
    assert missing["After Net GEX"].isna().all()
    assert missing["Net GEX change"].isna().all()


def test_summary_and_regime_use_actual_sign_and_missing_flip() -> None:
    """An all-call chain has positive exposure without an invented crossing."""
    before = parse_snapshots(EXAMPLE)[0]
    after = replace(
        before,
        spot=before.spot * 1.1,
        options=tuple(
            option for option in before.options if option.side == "call"
        ),
    )
    summary = comparison_summary(before, after)
    assert summary.loc[
        "Spot (USD)", "Change (after - before)"
    ] == pytest.approx(before.spot * 0.1)
    assert pd.isna(summary.loc["Nearest flip (USD)", "After"])
    chart = json_object(regime_chart(after).to_json())
    traces = [object_mapping(item) for item in object_list(chart["data"])]
    assert all(value == 0 for value in object_list(traces[1]["y"]))
    assert object_list(traces[-1]["y"]) == pytest.approx(
        [net_exposure(after, after.spot)]
    )


def test_comparison_controls_keep_chronology_and_render_both_scopes() -> None:
    """Browse both scopes without downloading data."""
    app = AppTest.from_string(
        "from dataclasses import replace\nfrom datetime import timedelta\nfrom"
        " gui_calculator.options_gex import EXAMPLE\nfrom"
        " snapshot_tunnel.options_model import parse_snapshots\nfrom"
        " gui_calculator.comparison_view import"
        " render_snapshot_comparison\nfirst ="
        " parse_snapshots(EXAMPLE)[0]\nitems = tuple(replace(first,"
        " timestamp=first.timestamp + timedelta(days=offset)) for offset in (2,"
        " 0, 1))\nrender_snapshot_comparison(items)\n"
    ).run()
    assert not app.get("plotly_chart")
    _ = app.toggle[0].set_value(True).run()
    assert not app.exception
    expected_charts = 3
    assert len(app.get("plotly_chart")) == expected_charts
    assert len(app.dataframe) == expected_charts
    _ = app.selectbox[0].select_index(1).run()
    assert not app.exception
    assert len(app.selectbox[1].options) == 1


def test_comparison_requires_two_observations() -> None:
    """A single observation cannot imply a before/after change."""
    app = AppTest.from_string(
        "from gui_calculator.options_gex import EXAMPLE\n"
        "from snapshot_tunnel.options_model import parse_snapshots\n"
        "from gui_calculator.comparison_view import"
        " render_snapshot_comparison\n"
        "render_snapshot_comparison(parse_snapshots(EXAMPLE)[:1])\n"
    ).run()
    _ = app.toggle[0].set_value(True).run()
    assert not app.exception
    assert app.info
    assert not app.get("plotly_chart")
