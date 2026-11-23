# Copyright 2026 anchored-vwam-backtest contributors
"""Verify options calculations, input boundaries and terminal interaction."""

from dataclasses import replace
from datetime import timedelta
from functools import partial
from io import BytesIO
from itertools import pairwise
from math import exp, pi, sqrt
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from shared.option_levels import DEFAULT_LEVEL_RANGE, OptionLevelRange
from shared.validation import (
    json_object,
    number,
    object_list,
    object_mapping,
    string,
)
from snapshot_tunnel.gamma_search import search_flips
from snapshot_tunnel.options_model import (
    Exposure,
    exposure,
    gamma_flips,
    max_pain,
    net_exposure,
    parse_candle_closes,
    parse_snapshots,
    positive_number,
    strike_exposures,
    timestamp,
    update_gex_once_per_candle,
    wall_tunnel,
)
from streamlit.testing.v1 import AppTest

from gui_calculator.options_gex import (
    EXAMPLE,
    exposure_chart,
    render_options_gex_strategy,
)
from gui_calculator.options_profile_chart import wall_levels_chart
from gui_calculator.options_store import load_snapshots, store_snapshot

if TYPE_CHECKING:
    from pathlib import Path

_SRGB_LINEAR_THRESHOLD = 0.04045
_WCAG_TEXT_CONTRAST = 4.5
_WCAG_GRAPHIC_CONTRAST = 3.0


@pytest.fixture
def isolated_options_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep terminal tests independent of the user's saved options database."""
    monkeypatch.setattr(
        "gui_calculator.snapshot_request_view.load_snapshots",
        partial(load_snapshots, path=tmp_path / "options_history.sqlite"),
    )

    monkeypatch.setattr(
        "gui_calculator.snapshot_request_view.store_snapshot",
        partial(store_snapshot, path=tmp_path / "options_history.sqlite"),
    )


def test_exposure_matches_analytic_at_money_gamma() -> None:
    """Verify dollar scaling against an independent one-year ATM formula."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    option = replace(
        snapshot.options[0],
        strike=snapshot.spot,
        iv=0.5,
        expiry=snapshot.timestamp + timedelta(days=365),
        open_interest=10,
        multiplier=2,
    )
    expected = (
        exp(-(0.25**2) / 2) / (0.5 * sqrt(2 * pi)) * snapshot.spot * 20 * 0.01
    )
    assert exposure(option, snapshot, spot=snapshot.spot) == pytest.approx(
        expected
    )
    empty = replace(option, open_interest=0)
    assert exposure(empty, snapshot, spot=snapshot.spot) == 0


def test_aggregation_and_flip_repricing() -> None:
    """Check exposure conservation and a sign-changing root."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    levels = strike_exposures(snapshot)
    assert sum(level.net for level in levels) == pytest.approx(
        net_exposure(snapshot, snapshot.spot)
    )
    assert all(level.absolute >= abs(level.net) for level in levels)
    roots = gamma_flips(snapshot, (60000, 80000, 100000))
    assert len(roots) == 1
    assert net_exposure(snapshot, roots[0]) == pytest.approx(0, abs=0.0001)
    assert net_exposure(snapshot, roots[0] - 1) < 0
    assert net_exposure(snapshot, roots[0] + 1) > 0
    calls = replace(
        snapshot, options=tuple(o for o in snapshot.options if o.side == "call")
    )
    assert gamma_flips(calls, (60000, 100000)) == ()


def test_gex_updates_once_for_each_candle_close() -> None:
    """Reprice the selected option chain at every completed candle close."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    candles = parse_candle_closes(
        "timestamp,close\n"
        "2026-09-21T08:01:00Z,82000\n"
        "2026-09-21T08:02:00Z,83000\n"
    )
    updates = update_gex_once_per_candle(snapshot, candles)

    assert [item.timestamp for item in updates] == [
        item.timestamp for item in candles
    ]
    assert [item.spot for item in updates] == [82000, 83000]
    assert updates[0].signed != updates[1].signed
    assert all(item.absolute >= abs(item.signed) for item in updates)


@pytest.mark.parametrize(
    "content",
    [
        "timestamp,close\n2026-09-21T08:00:00Z,1\n2026-09-21T08:00:00Z,2\n",
        "timestamp,close\n2026-09-21T08:00:00Z,0\n",
        "timestamp,close\n",
    ],
)
def test_candle_close_parser_rejects_invalid_data(content: str) -> None:
    """Reject duplicate, nonpositive, and empty candle inputs."""
    with pytest.raises(ValueError, match=r".+"):
        _ = parse_candle_closes(content)


def test_balanced_same_strike_has_no_flip() -> None:
    """A flat zero profile must not manufacture a flip point."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    option = snapshot.options[0]
    balanced = replace(snapshot, options=(option, replace(option, side="call")))
    assert gamma_flips(balanced, (60000, 80000, 100000)) == ()
    assert strike_exposures(balanced)[0].net == 0


def test_max_pain_requires_one_expiry_and_nonzero_oi() -> None:
    """Verify intrinsic-payout minimization and unavailable cases."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    assert max_pain(snapshot) == pytest.approx(80000)
    assert max_pain(replace(snapshot, options=())) is None
    zero = tuple(
        replace(option, open_interest=0) for option in snapshot.options
    )
    assert max_pain(replace(snapshot, options=zero)) is None
    mixed = (
        *snapshot.options,
        replace(
            snapshot.options[0],
            expiry=snapshot.options[0].expiry + timedelta(days=1),
        ),
    )
    assert max_pain(replace(snapshot, options=mixed)) is None


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "0", "bad"])
def test_invalid_numbers(value: str) -> None:
    """Reject invalid numeric fields before calculations."""
    with pytest.raises(ValueError, match=r"finite|convert"):
        _ = positive_number(value)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("BTC", "SOL"),
        ("put", "unknown"),
        ("DERIBIT", " "),
        ("2026-09-25T08:00:00Z", "2026-09-20T08:00:00Z"),
        ("1500", "-1"),
        ("0.55", "nan"),
    ],
)
def test_invalid_contract_fields(old: str, new: str) -> None:
    """Reject malformed option contract fields."""
    with pytest.raises(ValueError, match=r"Supported|Options|expire|finite"):
        _ = parse_snapshots(EXAMPLE.replace(old, new))


def test_csv_consistency_and_shape() -> None:
    """Reject duplicate contracts, mixed spots and malformed CSV rows."""
    header, *rows = EXAMPLE.strip().splitlines()
    for text in (
        "",
        header,
        EXAMPLE + rows[0] + "\n",
        EXAMPLE.replace("81791", "90000", 1),
        header + "\n" + rows[0] + ",extra",
        header + "\n" + "BTC",
    ):
        with pytest.raises(
            ValueError, match=r"CSV|empty|Duplicate|single spot"
        ):
            _ = parse_snapshots(text)
    with pytest.raises(ValueError, match="timezone"):
        _ = timestamp("2026-01-01")


@pytest.mark.parametrize("side", ["call", "put", None])
def test_wall_tunnel_bounds_ranked_strikes(side: str | None) -> None:
    """Bound available ranked strikes even when one exposure side is absent."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    if side is not None:
        snapshot = replace(
            snapshot,
            options=tuple(
                option for option in snapshot.options if option.side == side
            ),
        )
    levels = strike_exposures(snapshot)
    traces = [
        object_mapping(trace)
        for trace in object_list(
            json_object(wall_levels_chart(snapshot).to_json())["data"]
        )
    ]
    by_name = {string(trace["name"]): trace for trace in traces}
    assert by_name["Snapshot spot"]["y"] == [snapshot.spot] * 2
    calls = sorted(
        (level for level in levels if level.call > 0),
        key=lambda level: (-level.call, level.strike),
    )[:2]
    puts = sorted(
        (level for level in levels if level.put < 0),
        key=lambda level: (level.put, level.strike),
    )[:2]
    if sum(level.net for level in levels) < 0:
        strikes = sorted({level.strike for level in (*calls, *puts)})
        for rank, strike in enumerate(strikes, start=1):
            trace = by_name[f"Option border {rank}"]
            assert trace["y"] == [strike] * 2
        assert not any(name.startswith(("Call", "Put")) for name in by_name)
        return
    for name, ranked in (("Call", calls), ("Put", puts)):
        for rank, level in enumerate(ranked, start=1):
            trace = by_name[f"{name} {rank}"]
            assert trace["y"] == [level.strike] * 2
            assert trace.get("fill") is None
        assert (f"{name} 1" in by_name) == bool(ranked)
    assert "Call wall" not in by_name
    assert "Put wall" not in by_name
    assert "Extremum" not in by_name


def test_tunnel_characteristics_have_visible_prices() -> None:
    """Label every characteristic, including coincident spot and flip."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    figure = json_object(
        wall_levels_chart(snapshot, gamma_flip=snapshot.spot).to_json()
    )
    layout = object_mapping(figure["layout"])
    annotations = [
        object_mapping(annotation)
        for annotation in object_list(layout["annotations"])
    ]
    labels = [string(annotation["text"]) for annotation in annotations]
    for trace in object_list(figure["data"]):
        characteristic = object_mapping(trace)
        name = string(characteristic["name"]).split(" $")[0]
        price = number(object_list(characteristic["y"])[0])
        assert any(
            name in label and f"${price:,.2f}" in label for label in labels
        )
    assert any("Snapshot spot / Gamma flip" in label for label in labels)


@pytest.mark.parametrize("offset", [-0.01, 0.0, 0.01])
def test_tunnel_badges_stay_separate_for_nearby_prices(offset: float) -> None:
    """Close price levels use separate badges outside the plotting domain."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    figure = json_object(
        wall_levels_chart(snapshot, gamma_flip=snapshot.spot + offset).to_json()
    )
    layout = object_mapping(figure["layout"])
    domain = object_list(object_mapping(layout["xaxis"])["domain"])
    annotations = [
        object_mapping(item) for item in object_list(layout["annotations"])
    ]
    positions = sorted(number(item["y"]) for item in annotations)
    margin = object_mapping(layout["margin"])
    plot_height = (
        number(layout["height"]) - number(margin["t"]) - number(margin["b"])
    )
    for badge in annotations:
        assert badge["xref"] == badge["yref"] == "paper"
        assert number(badge["x"]) > number(domain[1])
        assert "<b>$" in string(badge["text"])
    minimum_badge_spacing = 50
    for lower, upper in pairwise(positions):
        assert (upper - lower) * plot_height >= minimum_badge_spacing
    spot_badges = [
        item for item in annotations if "Snapshot spot" in string(item["text"])
    ]
    assert len(spot_badges) == 1
    assert ("Gamma flip" in string(spot_badges[0]["text"])) == (offset == 0)


@pytest.mark.parametrize("spot", [79_000, 80_000, 83_000])
def test_extremum_distance_metrics(spot: float) -> None:
    """Show separate signed USD and percentage distances for every extremum."""
    app = AppTest.from_string(
        "from dataclasses import replace\n"
        "from gui_calculator.options_gex import "
        "EXAMPLE, _render_extremum_distances\n"
        "from snapshot_tunnel.options_model import parse_snapshots\n"
        "snapshot = parse_snapshots(EXAMPLE)[0]\n"
        "options = tuple(replace(snapshot.options[0], strike=strike, "
        "side=side) for strike in (80000, 82000) "
        "for side in ('call', 'put'))\n"
        f"snapshot = replace(snapshot, spot={spot!r}, options=options)\n"
        "_render_extremum_distances(snapshot)\n"
    ).run()
    assert not app.exception
    assert len(app.metric) == len((80_000, 82_000))
    for metric, price in zip(app.metric, (80_000, 82_000), strict=True):
        assert metric.label == f"Extremum ${price:,.2f} · distance from spot"
        assert metric.value == f"{(price / spot - 1) * 100:+.2f}%"
        assert metric.delta == f"${price - spot:+,.2f}"


@pytest.mark.parametrize("empty", [False, True])
def test_extremum_distances_absent_without_shared_ranks(*, empty: bool) -> None:
    """Omit distance readouts when no extremum exists."""
    app = AppTest.from_string(
        "from dataclasses import replace\n"
        "from gui_calculator.options_gex import "
        "EXAMPLE, _render_extremum_distances\n"
        "from snapshot_tunnel.options_model import parse_snapshots\n"
        "snapshot = parse_snapshots(EXAMPLE)[0]\n"
        + ("snapshot = replace(snapshot, options=())\n" if empty else "")
        + "_render_extremum_distances(snapshot)\n"
    ).run()
    assert not app.exception
    assert not app.metric
    assert not app.caption


def test_chart_contains_exposure_and_spot() -> None:
    """Verify the figure includes side exposures and reference lines."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    figure = exposure_chart(snapshot)
    assert len(figure.data) == len(("call", "put", "absolute"))
    layout = object_mapping(json_object(figure.to_json())["layout"])
    assert object_mapping(layout["yaxis2"])["matches"] == "y"
    shapes = object_list(layout["shapes"])
    assert object_mapping(shapes[0])["x0"] == snapshot.spot
    annotations = object_list(layout["annotations"])
    assert any(
        string(object_mapping(annotation)["text"]).startswith("BTCUSDT $")
        for annotation in annotations
    )
    assert object_mapping(layout["xaxis2"])["tickfont"] == {"color": "#111827"}
    assert object_mapping(layout["yaxis"])["title"] == {
        "font": {"color": "#111827"},
        "text": "USD / 1% move",
    }

    combined = exposure_chart(snapshot, flip_search=search_flips(snapshot))
    combined_payload = json_object(combined.to_json())
    combined_layout = object_mapping(combined_payload["layout"])
    assert any(
        object_mapping(trace).get("name") == "Repriced net GEX"
        for trace in object_list(combined_payload["data"])
    )
    assert object_mapping(combined_layout["xaxis"])["matches"] == "x3"
    assert object_mapping(combined_layout["xaxis2"])["matches"] == "x3"
    assert combined_layout["hovermode"] == "x unified"
    for axis_name in ("xaxis", "xaxis2", "xaxis3"):
        axis = object_mapping(combined_layout[axis_name])
        assert axis["showspikes"] is True
        assert axis["spikemode"] == "across"
        assert axis["spikesnap"] == "cursor"
    assert object_mapping(combined_layout["xaxis3"])["range"] == [
        78000.0,
        83000.0,
    ]


@pytest.mark.parametrize("has_crossing", [True, False])
def test_chart_explains_gamma_flip(*, has_crossing: bool) -> None:
    """Display a measured crossing or explicitly bounded missing result."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    result = search_flips(snapshot)
    if not has_crossing:
        result = replace(result, roots=())
    payload = json_object(
        exposure_chart(snapshot, flip_search=result).to_json()
    )
    layout = object_mapping(payload["layout"])
    labels = [
        string(object_mapping(annotation)["text"])
        for annotation in object_list(layout["annotations"])
    ]
    assert any("Net GEX at spot:" in label for label in labels)
    assert any(
        "fixed snapshot IV and open interest" in label for label in labels
    )
    assert any("Max pain $" in label for label in labels)
    flip_levels = [
        shape
        for item in object_list(layout["shapes"])
        if (shape := object_mapping(item))["xref"] == "x"
        and object_mapping(shape["line"])["color"] == "#000000"
    ]
    if result.nearest is None:
        assert not flip_levels
        assert any(
            "no crossing found in search range" in label for label in labels
        )
    else:
        assert len(flip_levels) == 1
        assert flip_levels[0]["x0"] == result.nearest
        assert flip_levels[0]["x1"] == result.nearest
        assert any(
            f"Nearest gamma flip: ${result.nearest:,.2f}" in label
            and "spot vs flip:" in label
            for label in labels
        )
        assert any(
            label == f"Gamma flip ${result.nearest:,.2f}" for label in labels
        )


def _relative_luminance(color: str) -> float:
    """Calculate the WCAG relative luminance for a six-digit hex color.

    Returns:
        The relative luminance from zero to one.

    """
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        (
            channel / 12.92
            if channel <= _SRGB_LINEAR_THRESHOLD
            else ((channel + 0.055) / 1.055) ** 2.4
        )
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    """Calculate the WCAG contrast ratio for two hex colors.

    Returns:
        The contrast ratio, where one is no contrast and 21 is maximum.

    """
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def test_options_chart_colors_meet_wcag_contrast() -> None:
    """Keep chart text and visible series at readable contrast levels."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    payload = json_object(exposure_chart(snapshot).to_json())
    layout = object_mapping(payload["layout"])
    plot_background = string(layout["plot_bgcolor"])
    assert (
        _contrast_ratio(
            string(object_mapping(layout["font"])["color"]), plot_background
        )
        >= _WCAG_TEXT_CONTRAST
    )

    title = object_mapping(layout["title"])
    assert (
        _contrast_ratio(
            string(object_mapping(title["font"])["color"]), plot_background
        )
        >= _WCAG_TEXT_CONTRAST
    )
    legend = object_mapping(layout["legend"])
    assert (
        _contrast_ratio(
            string(object_mapping(legend["font"])["color"]), plot_background
        )
        >= _WCAG_TEXT_CONTRAST
    )

    hover = object_mapping(layout["hoverlabel"])
    assert (
        _contrast_ratio(
            string(object_mapping(hover["font"])["color"]),
            string(hover["bgcolor"]),
        )
        >= _WCAG_TEXT_CONTRAST
    )

    axis_colors: list[str] = []
    for name in ("xaxis", "xaxis2", "yaxis", "yaxis2"):
        axis = object_mapping(layout[name])
        axis_colors.extend([
            string(object_mapping(axis["tickfont"])["color"]),
            string(
                object_mapping(object_mapping(axis["title"])["font"])["color"]
            ),
        ])
    assert all(
        _contrast_ratio(color, plot_background) >= _WCAG_TEXT_CONTRAST
        for color in axis_colors
    )

    for trace in object_list(payload["data"]):
        trace_mapping = object_mapping(trace)
        marker = trace_mapping.get("marker")
        line = trace_mapping.get("line")
        colors: list[str] = []
        if marker is not None:
            colors.append(string(object_mapping(marker)["color"]))
        if line is not None:
            colors.append(string(object_mapping(line)["color"]))
        assert all(
            _contrast_ratio(color, plot_background) >= _WCAG_GRAPHIC_CONTRAST
            for color in colors
        )


def test_strategy_profile_uses_latest_causal_btc_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the latest snapshot available in the strategy candle window."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    data = pd.DataFrame({
        "time": [
            snapshot.timestamp.isoformat(),
            (snapshot.timestamp + timedelta(days=1)).isoformat(),
        ]
    })
    selected: list[object] = []

    def render_profile(
        selected_snapshot: object,
        _chart_ui: object,
        *,
        level_range: OptionLevelRange,
    ) -> None:
        assert level_range == DEFAULT_LEVEL_RANGE
        selected.append(selected_snapshot)

    monkeypatch.setattr(
        "gui_calculator.options_gex._render_profile", render_profile
    )
    newer = replace(snapshot, timestamp=snapshot.timestamp + timedelta(hours=1))
    future = replace(snapshot, timestamp=snapshot.timestamp + timedelta(days=2))
    render_options_gex_strategy(
        MagicMock(), data, content=(newer, future, snapshot)
    )

    assert selected == [newer]


@pytest.mark.usefixtures("isolated_options_history")
def test_terminal_demo_and_empty_selection() -> None:
    """Calculate only on request and report missing observations."""
    app = AppTest.from_string(
        "from gui_calculator.options_gex import render_options_gex\n"
        "render_options_gex()"
    ).run()
    assert not app.exception
    assert not app.metric
    _ = app.selectbox[1].select("Saved history / Deribit API").run()
    assert any("No archived BTC snapshots" in item.value for item in app.info)
    assert not app.button
    _ = app.selectbox[1].select("Synthetic demo").run()
    snapshot = parse_snapshots(EXAMPLE)[0]
    _ = app.date_input[0].set_value(snapshot.timestamp.date())
    _ = app.time_input[0].set_value(snapshot.timestamp.time())
    _ = app.button[0].click().run()
    assert not app.exception
    assert len(app.metric) == len(
        ("flip", "net", "absolute", "pain", "call1", "call2", "put1", "put2")
    )
    assert "SYNTHETIC" in app.warning[0].value


@pytest.mark.parametrize("content", [b"invalid", b"\xff"])
@pytest.mark.usefixtures("isolated_options_history")
def test_upload_errors_are_visible(content: bytes) -> None:
    """Malformed and non-UTF8 uploads produce actionable errors."""
    with patch(
        "gui_calculator.snapshot_request_view.st.file_uploader",
        return_value=BytesIO(content),
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import render_options_gex\n"
            "render_options_gex()"
        ).run()
        _ = app.selectbox[1].select("CSV").run()
    assert not app.exception
    assert "Snapshot analytics unavailable" in app.error[0].value


@pytest.mark.usefixtures("isolated_options_history")
def test_uploaded_history_selects_asset_and_time() -> None:
    """Reject absent sides and avoid falling back to a different minute."""
    from gui_calculator.snapshot_request_view import select_observation

    snapshot = parse_snapshots(EXAMPLE)[0]
    assert (
        select_observation(
            (snapshot,), asset="BTC", requested=snapshot.timestamp
        )
        == snapshot
    )
    with pytest.raises(ValueError, match="no saved snapshot"):
        _ = select_observation(
            (snapshot,), asset="ETH", requested=snapshot.timestamp
        )
    with pytest.raises(ValueError, match="no saved snapshot"):
        _ = select_observation(
            (snapshot,),
            asset="BTC",
            requested=snapshot.timestamp + timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="Missing BTC"):
        _ = select_observation(
            (replace(snapshot, options=()),),
            asset="BTC",
            requested=snapshot.timestamp,
        )


def test_exposure_numeric_overflow_is_rejected() -> None:
    """Do not return infinite exposure from finite but excessive inputs."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    option = replace(snapshot.options[0], open_interest=1e308)
    with pytest.raises(ValueError, match="numeric range"):
        _ = exposure(option, snapshot, spot=snapshot.spot)


def test_daily_history_preserves_repricing_and_expiry_gaps() -> None:
    """Keep each decision bar and hide stale plans at their exact expiry."""
    app = AppTest.from_string(
        "import pandas as pd\n"
        "import streamlit as st\n"
        "from gui_calculator.options_gex import render_strategy_history\n"
        "times = pd.date_range('2026-10-20T18:00Z', periods=3, freq='5min')\n"
        "data = pd.DataFrame({\n"
        " 'options_decision_at': times,\n"
        " 'options_gex_time': [times[0]] * 3,\n"
        " 'options_valid_until': [times[2]] * 3,\n"
        " 'open': [82000., 82010., 82020.],\n"
        " 'options_gex': [100.] * 3,\n"
        " 'options_monitored_gex': [101., 102., 103.],\n"
        " 'options_call_gex': [200.] * 3,\n"
        " 'options_put_gex': [-100.] * 3,\n"
        " 'options_absolute_gex': [300.] * 3,\n"
        " 'options_gamma_flip': [81000.] * 3,\n"
        " 'options_call_wall': [90000.] * 3,\n"
        " 'options_put_wall': [80000.] * 3,\n"
        "})\n"
        "render_strategy_history(st, data)\n"
        "assert data['options_gex'].notna().all()\n"
    ).run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    history = app.dataframe[0].value
    assert history["options_monitored_gex"].iloc[:2].tolist() == [101.0, 102.0]
    assert history["options_gex"].isna().tolist() == [False, False, True]
    assert history["options_price"].tolist() == [82000.0, 82010.0, 82020.0]


@pytest.mark.usefixtures("isolated_options_history")
def test_latest_snapshot_download_and_persistence(tmp_path: Path) -> None:
    """Download only on Calculate and preserve the actual observation time."""
    from snapshot_tunnel.options_data import ChainObservation

    from gui_calculator.options_store import load_snapshots

    snapshot = replace(parse_snapshots(EXAMPLE)[0], asset="ETH")
    observation = ChainObservation(
        snapshot=snapshot, observed_at=snapshot.timestamp
    )
    with patch(
        "gui_calculator.snapshot_request_view.fetch_snapshot",
        return_value=observation,
    ) as download:
        app = AppTest.from_string(
            "from gui_calculator.options_gex import render_options_gex\n"
            "render_options_gex()"
        ).run()
        download.assert_not_called()
        _ = app.selectbox[0].select("ETH").run()
        _ = app.button[0].click().run()
        assert not app.exception
        assert not app.error
        assert len(app.metric) == len((
            "flip",
            "net",
            "absolute",
            "pain",
            "call1",
            "call2",
            "put1",
            "put2",
        ))
        assert download.call_args.kwargs["asset"] == "ETH"
    assert load_snapshots(tmp_path / "options_history.sqlite") == (snapshot,)


@pytest.mark.usefixtures("isolated_options_history")
def test_latest_download_failure_is_visible(tmp_path: Path) -> None:
    """Network failures show an error without persisting an observation."""
    from requests import ConnectionError as DownloadError

    from gui_calculator.options_store import load_snapshots

    with patch(
        "gui_calculator.snapshot_request_view.fetch_snapshot",
        side_effect=DownloadError("Deribit unavailable"),
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import render_options_gex\n"
            "render_options_gex()"
        ).run()
        _ = app.button[0].click().run()
        assert not app.exception
        assert "Deribit unavailable" in app.error[0].value
    assert not load_snapshots(tmp_path / "options_history.sqlite")


@pytest.mark.usefixtures("isolated_options_history")
def test_latest_missing_ca_bundle_is_visible(tmp_path: Path) -> None:
    """A missing local CA file displays an error without saving a snapshot."""
    with patch(
        "requests.Session.get",
        side_effect=OSError("invalid path: /missing/certifi/cacert.pem"),
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import render_options_gex\n"
            "render_options_gex()"
        ).run()
        _ = app.button[0].click().run()
        assert not app.exception
        assert "cacert.pem" in app.error[0].value
    assert not load_snapshots(tmp_path / "options_history.sqlite")


@pytest.mark.usefixtures("isolated_options_history")
def test_archive_dropdown_selects_uploaded_observation() -> None:
    """Browse uploaded days without entering dates and filter absent assets."""
    first = parse_snapshots(EXAMPLE)[0]
    later = first.timestamp + timedelta(days=1)
    content = (
        EXAMPLE
        + "\n"
        + "\n".join(
            later.isoformat() + "," + line.partition(",")[2]
            for line in EXAMPLE.splitlines()[1:]
            if line
        )
    )
    with patch(
        "gui_calculator.snapshot_request_view.st.file_uploader",
        return_value=BytesIO(content.encode()),
    ):
        app = AppTest.from_string(
            "from gui_calculator.snapshot_request_view import "
            "render_snapshot_request\n"
            "import streamlit as st\n"
            "snapshot = render_snapshot_request('')\n"
            "if snapshot is not None:\n"
            "    st.text(snapshot.timestamp.isoformat())\n"
        ).run()
        _ = app.selectbox[1].select("CSV").run()
        assert not app.exception
        assert len(app.selectbox[2].options) == len((first, later))
        _ = app.selectbox[2].select(1).run()
        _ = app.button[0].click().run()
        assert app.text[0].value == later.isoformat()
        _ = app.selectbox[0].select("ETH").run()
        assert "no ETH snapshots" in app.warning[0].value


@pytest.mark.parametrize("offset", [-100.0, 0.0, 100.0, None])
def test_gamma_flip_warning_uses_nearest_crossing(offset: float | None) -> None:
    """Warn only when the nearest gamma flip is above the snapshot price."""
    app = AppTest.from_string(
        "from gui_calculator.options_gex import EXAMPLE, _render_levels\n"
        "from snapshot_tunnel.options_model import parse_snapshots\n"
        "snapshot = parse_snapshots(EXAMPLE)[0]\n"
        f"offset = {offset!r}\n"
        "flips = () if offset is None else (snapshot.spot + offset, "
        "snapshot.spot + 1000)\n"
        "_render_levels(snapshot, flips)\n"
    ).run()
    assert not app.exception
    if offset is not None and offset > 0:
        snapshot = parse_snapshots(EXAMPLE)[0]
        assert len(app.warning) == 1
        assert (
            app.warning[0].value
            == f"Snapshot price ${snapshot.spot:,.2f} is below gamma flip "
            f"${snapshot.spot + offset:,.2f}."
        )
    else:
        assert not app.warning


@pytest.mark.parametrize("offset", [-100.0, 0.0, 100.0])
def test_chart_separates_clustered_flip_labels(offset: float) -> None:
    """Keep one nearest-flip label clear of adjacent crossing markers."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    nearest = snapshot.spot + offset
    result = replace(
        search_flips(snapshot), roots=(nearest, snapshot.spot + 1000)
    )
    chart = exposure_chart(snapshot, flip_search=result)
    labels = [
        annotation
        for annotation in chart.layout.annotations
        if str(annotation.text).startswith("Gamma flip $")
    ]
    assert len(labels) == 1
    assert labels[0].text == f"Gamma flip ${nearest:,.2f}"
    assert labels[0].xref == "paper"
    assert labels[0].yref == "y3 domain"
    assert labels[0].bgcolor == "#ffffff"
    label = object_mapping(json_object(chart.to_json())["layout"])
    annotations = object_list(label["annotations"])
    nearest_label = next(
        object_mapping(annotation)
        for annotation in annotations
        if object_mapping(annotation)["text"] == labels[0].text
    )
    assert object_mapping(nearest_label["font"])["color"] == (
        "#dc2626" if offset > 0 else "#0369a1"
    )
    assert any(
        "Warning: gamma flip is above snapshot price." in str(annotation.text)
        for annotation in chart.layout.annotations
    ) == (offset > 0)


def test_profile_labels_ranked_call_and_put_walls() -> None:
    """Identify the strongest side exposures directly on the strike chart."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    chart = exposure_chart(snapshot)
    levels = strike_exposures(snapshot)
    calls = sorted(
        (level for level in levels if level.call > 0),
        key=lambda level: (-level.call, level.strike),
    )
    puts = sorted(
        (level for level in levels if level.put < 0),
        key=lambda level: (level.put, level.strike),
    )
    for prefix, side, ranked in (("P", "CALL", calls), ("N", "PUT", puts)):
        for rank, level in enumerate(ranked[:2], start=1):
            label = next(
                item
                for item in chart.layout.annotations
                if f"{prefix}{rank} · {side}" in str(item.text)
            )
            assert label.x == level.strike
            assert f"${level.strike:,.0f}" in str(label.text)
            assert label.showarrow is True
            if side == "PUT":
                assert label.y == max(level.call for level in levels)
                assert label.ay == -45 * rank
                assert label.yanchor == "bottom"
            else:
                assert label.y == min(level.put for level in levels)
                assert label.ay == 45 * rank
                assert label.yanchor == "top"


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        ((), None),
        ((Exposure(strike=100, call=0, put=0),), None),
        ((Exposure(strike=100, call=10, put=0),), (100, 100)),
        (
            (
                Exposure(strike=70, call=1, put=-1),
                Exposure(strike=80, call=30, put=-5),
                Exposure(strike=90, call=40, put=-10),
                Exposure(strike=100, call=5, put=-30),
                Exposure(strike=110, call=2, put=-20),
                Exposure(strike=120, call=1, put=-1),
            ),
            (80, 110),
        ),
        (
            (
                Exposure(strike=80, call=10, put=0),
                Exposure(strike=90, call=10, put=0),
                Exposure(strike=100, call=10, put=0),
            ),
            (80, 90),
        ),
        (
            (
                Exposure(strike=80, call=0, put=-10),
                Exposure(strike=90, call=0, put=-20),
            ),
            (80, 90),
        ),
    ],
)
def test_ranked_tunnel_extrema(
    levels: tuple[Exposure, ...], expected: tuple[float, float] | None
) -> None:
    """Use extrema of top-two ranks, excluding weaker outer strikes."""
    tunnel = wall_tunnel(levels, spot=100)
    if expected is None:
        assert tunnel is None
    else:
        assert tunnel is not None
        assert (tunnel.put, tunnel.call) == expected


@pytest.mark.parametrize(
    ("puts", "expected"),
    [
        ((-40, -30, -20, -10), (80, 90)),
        ((-10, -30, -40, -20), (90,)),
        ((-10, -20, -40, -30), ()),
        ((0, 0, 0, 0), ()),
        ((-30, -30, -30, -30), (80, 90)),
    ],
)
def test_tunnel_shared_ranked_strikes(
    puts: tuple[float, ...], expected: tuple[float, ...]
) -> None:
    """Find both, one or no shared ranks; weaker coincidences do not count."""
    levels = tuple(
        Exposure(strike=80 + index * 10, call=40 - index * 10, put=put)
        for index, put in enumerate(puts)
    )
    tunnel = wall_tunnel(levels, spot=100)
    assert tunnel is not None
    assert tunnel.extrema == expected
