# Copyright 2026 anchored-vwam-backtest contributors
"""Test data and metrics."""

from datetime import UTC
from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pandas as pd
import plotly.graph_objects as go
import pytest
import requests
from plotly.subplots import make_subplots
from shared.models import Trade
from shared.validation import json_object, object_list, object_mapping

from gui_calculator import data_sources as ds
from gui_calculator.charts import ChartDisplay, add_hover_crosshair, build_chart
from gui_calculator.metrics import format_metric, summarize
from gui_calculator.observed_history import RecordedCharts
from tests.support import (
    attribute,
    call_kwargs,
    mock_child,
    mock_result,
    trace_name,
    uncached,
)

if TYPE_CHECKING:
    from gui_calculator.candle_cache import KlineFetcher


def test_chart_hover_crosshair_spans_traces() -> None:
    """Verify expected behavior."""
    figure = add_hover_crosshair(go.Figure())

    assert figure.layout.hovermode == "x unified"
    assert figure.layout.hoversubplots == "axis"
    xaxis = attribute(figure.layout, "xaxis")
    assert attribute(xaxis, "showspikes") is True
    assert attribute(xaxis, "spikemode") == "across"
    assert attribute(xaxis, "spikesnap") == "cursor"


@pytest.mark.parametrize("panels", [2, 3, 4])
def test_crosshair_links_stacked_panels(panels: int) -> None:
    """Share a cursor axis while preserving each panel's vertical scale."""
    figure = make_subplots(rows=panels, cols=1, shared_xaxes=True)
    for row in range(1, panels + 1):
        _ = figure.add_trace(
            go.Scatter(x=[1, 2], y=[row, row * 2]), row=row, col=1
        )
    _ = figure.update_xaxes(range=[0, 3], row=panels, col=1)

    _ = add_hover_crosshair(figure)

    payload = json_object(figure.to_json())
    traces = [object_mapping(item) for item in object_list(payload["data"])]
    assert {trace["xaxis"] for trace in traces} == {f"x{panels}"}
    assert [trace["yaxis"] for trace in traces] == [
        "y",
        *(f"y{row}" for row in range(2, panels + 1)),
    ]
    layout = object_mapping(payload["layout"])
    assert layout["hoversubplots"] == "axis"
    assert object_mapping(layout[f"xaxis{panels}"])["range"] == [0, 3]


def test_crosshair_preserves_independent_axes() -> None:
    """Keep panels with unrelated horizontal scales independent."""
    figure = make_subplots(rows=2, cols=1)
    for row in (1, 2):
        _ = figure.add_trace(go.Scatter(x=[1, 2], y=[1, 2]), row=row, col=1)

    _ = add_hover_crosshair(figure)

    payload = json_object(figure.to_json())
    traces = [object_mapping(item) for item in object_list(payload["data"])]
    assert [trace["xaxis"] for trace in traces] == ["x", "x2"]


@pytest.mark.parametrize("tunnel", [False, True])
@pytest.mark.parametrize("recorded", [False, True])
def test_options_gex_chart_syncs_price_and_indicator_panels(
    *, tunnel: bool, recorded: bool
) -> None:
    """Keep options indicators on the price chart's shared cursor axis."""
    times = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    data = pd.DataFrame({
        "time": times,
        "open": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
        "close": [100, 101, 102],
        "volume": [10, 11, 12],
        "anchored_vwap": [100, 100.5, 101],
        "anchored_std": [1, 1, 1],
        "options_gex_time": times,
        "options_gex": [-10, 20, 30],
        "options_call_gex": [20, 30, 40],
        "options_put_gex": [-30, -10, -10],
        "options_absolute_gex": [50, 40, 50],
        "options_gamma_flip": [99, 100, 101],
        "options_call_wall": [105, 106, 107],
        "options_put_wall": [95, 96, 97],
        "options_max_pain": [100, 101, 102],
    })
    equity = pd.DataFrame({"time": times, "equity": [1000, 1001, 1002]})
    optional_traces = {
        "options_call_gex": "Call GEX",
        "options_put_gex": "Put GEX",
        "options_absolute_gex": "Absolute GEX",
        "options_max_pain": "Max pain",
    }
    if tunnel:
        data = data.drop(columns=list(optional_traces))

    observed = data.copy()
    observed["options_gamma_flip"] = 200.0
    figure = build_chart(
        data,
        equity,
        [],
        options_history=RecordedCharts(gex=observed) if recorded else None,
        display=ChartDisplay(
            strategy_start_at=times[0],
            strategy_end_at=times[-1],
            selected_timezone=UTC,
            timezone_label="UTC",
        ),
    )

    payload = json_object(figure.to_json())
    trace_payloads = [
        object_mapping(item) for item in object_list(payload["data"])
    ]
    traces = {
        name: trace
        for trace in trace_payloads
        if isinstance(name := trace.get("name"), str)
    }
    assert {
        "Net GEX",
        "Gamma flip",
        "Call wall",
        "Put wall",
    } <= traces.keys()
    for name in optional_traces.values():
        assert (name in traces) is not tunnel
    assert traces["Net GEX"]["yaxis"] == "y4"
    assert traces["Gamma flip"]["yaxis"] == "y"
    assert "Anchored VWAP" not in traces
    assert "+1.0\N{GREEK SMALL LETTER SIGMA}" not in traces
    assert "Close (levels)" not in traces
    assert traces["Call wall"]["yaxis"] == "y"
    assert traces["Put wall"]["yaxis"] == "y"
    layout = object_mapping(payload["layout"])
    assert "yaxis5" not in layout
    price_range = object_list(object_mapping(layout["yaxis"])["range"])
    assert float(str(price_range[0])) < data["options_put_wall"].min()
    assert float(str(price_range[1])) > data["options_call_wall"].max()
    if recorded:
        assert float(str(price_range[1])) > observed["options_gamma_flip"].max()
    assert object_mapping(layout["yaxis"])["domain"] == [0.30, 1.0]
    assert object_mapping(layout["xaxis"])["spikemode"] == "across"


@pytest.mark.parametrize("interval", ["1d", "4h"])
def test_sample_is_reproducible_and_has_valid_ohlc(interval: str) -> None:
    """Verify expected behavior."""
    a = uncached(ds.generate_sample_klines)(interval)
    pd.testing.assert_frame_equal(
        a, uncached(ds.generate_sample_klines)(interval)
    )
    assert (a.high >= a[["open", "close"]].max(axis=1)).all()
    assert (a.low <= a[["open", "close"]].min(axis=1)).all()
    assert a.time.is_monotonic_increasing


@pytest.mark.parametrize(
    ("time_header", "value"),
    [
        ("time", "2026-01-01T00:00:00Z"),
        ("timestamp", "1767225600"),
        ("open_time", "1767225600000"),
    ],
)
def test_csv_time_formats(time_header: str, value: str) -> None:
    """Verify expected behavior."""
    df = ds.parse_uploaded_csv(
        StringIO(
            f"{time_header},open,high,low,close,volume\n{value},10,12,9,11,3\n"
        )
    )
    assert pd.to_datetime(df["time"], utc=True).iloc[0] == pd.Timestamp(
        "2026-01-01", tz="UTC"
    )
    expected_value = 33
    assert df["quote_asset_volume"].astype(float).iloc[0] == expected_value


def test_headerless_csv_and_missing_columns() -> None:
    """Verify expected behavior."""
    df = ds.parse_uploaded_csv(
        StringIO("1767225600000,10,12,9,11,3,1767225660000,33,1,0,0,0\n")
    )
    assert df["close"].astype(float).tolist() == [11]
    with pytest.raises(ValueError, match="CSV must include"):
        _ = ds.parse_uploaded_csv(StringIO("time,open\n2026-01-01,10\n"))


def test_reverse_rejects_nonpositive_prices() -> None:
    """Verify expected behavior."""
    df = pd.DataFrame({"open": [0], "high": [1], "low": [0], "close": [1]})
    with pytest.raises(ValueError, match="zero or negative"):
        _ = ds.reverse_candles(df)


@pytest.mark.parametrize(
    "fetch",
    [
        uncached(ds.fetch_bybit_klines),
        ds.fetch_bybit_linear_klines,
        uncached(ds.fetch_mexc_klines),
    ],
)
def test_unsupported_interval(fetch: KlineFetcher) -> None:
    """Verify expected behavior."""
    with pytest.raises(ValueError, match="does not support"):
        _ = fetch("XRPUSDT", "2m", start_ms=0, end_ms=100)


def test_binance_pagination_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify expected behavior."""
    get = Mock()
    monkeypatch.setattr(requests, "get", get)
    row = [0, "10", "12", "9", "11", "3", 59999, "33", 2, "0", "0", "0"]
    mock_child(mock_result(get), "json").side_effect = [[row], []]
    df = uncached(ds.fetch_klines)("BTCUSDT", "1m", start_ms=0, end_ms=120000)
    assert df["close"].astype(float).tolist() == [11]
    assert object_mapping(call_kwargs(get)["params"])["startTime"] == 1
    mock_child(mock_result(get), "json").side_effect = [[]]
    assert (
        list(
            uncached(ds.fetch_klines)(
                "BTCUSDT", "1m", start_ms=0, end_ms=120000
            ).columns
        )
        == ds.CANDLE_COLUMNS
    )


@pytest.mark.parametrize(
    "fetch", [uncached(ds.fetch_bybit_klines), ds.fetch_bybit_linear_klines]
)
def test_bybit_uses_linear_and_stops_repeated_pages(
    monkeypatch: pytest.MonkeyPatch, fetch: KlineFetcher
) -> None:
    """Verify expected behavior."""
    get = Mock()
    monkeypatch.setattr(requests, "get", get)
    mock_child(mock_result(get), "json").return_value = {
        "retCode": 0,
        "result": {"list": [["60000", "10", "12", "9", "11", "3", "33"]]},
    }
    df = fetch("XRPUSDT", "1m", start_ms=0, end_ms=180000)
    assert object_mapping(call_kwargs(get)["params"])["category"] == "linear"
    expected_value = 2
    assert get.call_count == expected_value
    assert len(df) == 1


@pytest.mark.parametrize(
    "fetch", [uncached(ds.fetch_bybit_klines), ds.fetch_bybit_linear_klines]
)
def test_bybit_empty_and_api_error(
    monkeypatch: pytest.MonkeyPatch, fetch: KlineFetcher
) -> None:
    """Verify expected behavior."""
    get = Mock()
    monkeypatch.setattr(requests, "get", get)
    mock_child(mock_result(get), "json").return_value = {
        "retCode": 0,
        "result": {"list": []},
    }
    assert fetch("XRPUSDT", "1m", start_ms=0, end_ms=180000).empty
    mock_child(mock_result(get), "json").return_value = {
        "retCode": 1,
        "retMsg": "bad request",
    }
    with pytest.raises(ValueError, match="bad request"):
        _ = fetch("XRPUSDT", "1m", start_ms=0, end_ms=180000)


@pytest.mark.parametrize(
    "payload",
    [
        {"retCode": 1, "retMsg": "bad"},
        {"retCode": 0, "result": {"list": []}},
        {"retCode": 0, "result": {"list": [{"lastPrice": "0"}]}},
    ],
)
def test_bad_live_price(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]
) -> None:
    """Verify expected behavior."""
    get = Mock()
    mock_child(mock_result(get), "json").return_value = payload
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(ValueError, match=r"error|price"):
        _ = uncached(ds.fetch_bybit_live_price)("XRPUSDT")


def test_metrics_include_loss_before_first_equity_row_and_daily_sharpe() -> (
    None
):
    """Verify expected behavior."""
    times = pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC")
    equity = pd.DataFrame({"time": times, "equity": [90.0, 95.0, 85.0, 100.0]})
    result = summarize(equity, [], 100.0)
    assert result["Max drawdown"] == pytest.approx(-15.0)
    assert result["Net return"] == 0
    # Adding intraday observations with the same daily closes must not alter
    # Sharpe.
    intraday = pd.concat(
        [equity, equity.assign(time=times + pd.Timedelta(hours=12))]
    ).sort_values("time")
    assert summarize(intraday, [], 100)["Sharpe"] == pytest.approx(
        result["Sharpe"]
    )
    expected_value = 100
    assert summarize(equity.iloc[:0], [], 100)["Final equity"] == expected_value
    assert format_metric(100, "Final equity") == "100.00000000 USDT"
    assert format_metric(2, "Trades") == "2"
    assert format_metric(1.234, "Sharpe") == "1.23"
    assert format_metric(-2, "Net return") == "-2.00%"


def test_chart_contains_tunnel_trade_markers() -> None:
    """Verify expected behavior."""
    times = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    df = pd.DataFrame({
        "time": times,
        "open": 100,
        "high": 102,
        "low": 98,
        "close": 100,
        "volume": 10,
        "anchored_vwap": 100,
        "anchored_std": 1,
    })
    eq = pd.DataFrame({"time": times, "equity": [100, 101, 102]})
    trades = [
        Trade(100, s, times[0], times[1], 100, 101, 1, 1, 1, "test")
        for s in ["Long", "Short"]
    ]
    fig = build_chart(
        df,
        eq,
        trades,
        display=ChartDisplay(
            strategy_start_at=times[0],
            strategy_end_at=times[-1],
            selected_timezone=UTC,
            timezone_label="UTC",
        ),
    )
    names = {trace_name(t) for t in fig.data}
    assert {"Long entries", "Short entries", "Exits"} <= names
    assert "Anchored VWAP" not in names
    assert not any(
        "sigma" in name or "\N{GREEK SMALL LETTER SIGMA}" in name
        for name in names
    )
    expected_value = 100
    assert summarize(eq, trades, 100)["Win rate"] == expected_value
