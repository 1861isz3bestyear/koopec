# Copyright 2026 anchored-vwam-backtest contributors
"""Test vwam."""

from datetime import UTC
from io import StringIO
from unittest.mock import MagicMock

import pandas as pd
import pytest
from shared.validation import string

from gui_calculator.settings import CalculatorSettings
from gui_calculator.vwam import (
    MICROPRICE,
    SAME_SIDE,
    build_vwam_chart,
    calculate_vwam,
    parse_quotes,
    render_vwam,
)
from tests.support import call_args, mock_child, scatter


def csv(rows: str = "2026-01-01T00:00:00Z,100,102,90,10") -> StringIO:
    """Provide the csv test fixture.

    Returns:
        The constructed test value.

    """
    return StringIO("time,bid,ask,bid_size,ask_size\n" + rows)


def test_imbalance_direction_and_spread() -> None:
    """Verify imbalance direction and spread."""
    quotes = parse_quotes(csv())
    micro = calculate_vwam(quotes)
    same = calculate_vwam(quotes, SAME_SIDE)
    assert micro.vwam.iloc[0] == pytest.approx(101.8)
    assert same.vwam.iloc[0] == pytest.approx(100.2)
    expected_value = 101
    assert micro.mid.iloc[0] == expected_value
    expected_value = 2
    assert micro.spread.iloc[0] == expected_value
    assert micro.imbalance.iloc[0] == pytest.approx(0.8)
    assert "vwam" not in quotes
    fig = build_vwam_chart(
        micro,
        MICROPRICE,
        selected_timezone=UTC,
        timezone_label="UTC",
        ticker="BTC_USDT",
    )
    expected_count = 4
    assert len(fig.data) == expected_count
    assert list(scatter(fig.data[-1]).y) == list(micro.vwam)


@pytest.mark.parametrize(
    ("sizes", "expected"), [("50,50", 101), ("0,10", 100), ("10,0", 102)]
)
def test_balanced_and_one_sided_quotes(sizes: str, expected: int) -> None:
    """Verify balanced and one sided quotes."""
    assert (
        calculate_vwam(
            parse_quotes(csv("2026-01-01,100,102," + sizes))
        ).vwam.iloc[0]
        == expected
    )


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ("bad,100,102,90,10", "invalid"),
        ("2026-01-01,inf,102,90,10", "invalid"),
        ("2026-01-01,0,102,90,10", "positive"),
        ("2026-01-01,103,102,90,10", "exceed"),
        ("2026-01-01,100,102,-1,10", "nonnegative"),
        ("2026-01-01,100,102,0,0", "positive total"),
        ("2026-01-01,100,102,,10", "invalid"),
    ],
)
def test_reject_invalid_quotes(row: str, match: str) -> None:
    """Verify reject invalid quotes."""
    with pytest.raises(ValueError, match=match):
        _ = parse_quotes(csv(row))


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("time,bid\n2026-01-01,100", "requires"),
        ("time,bid,ask,bid_size,ask_size,BID\n1,1,2,1,1,1", "duplicate"),
        ("time,bid,ask,bid_size,ask_size\n", "empty"),
    ],
)
def test_reject_invalid_schema(content: str, match: str) -> None:
    """Verify reject invalid schema."""
    with pytest.raises(ValueError, match=match):
        _ = parse_quotes(StringIO(content))


@pytest.mark.parametrize("stamp", [1767225600, 1767225600000])
def test_epoch_timestamps(stamp: int) -> None:
    """Verify epoch timestamps."""
    quotes = parse_quotes(csv(f"{stamp},100,102,90,10"))
    assert pd.to_datetime(quotes["time"], utc=True).iloc[0] == pd.Timestamp(
        "2026-01-01", tz="UTC"
    )


def test_stable_time_order_and_unknown_method() -> None:
    """Verify stable time order and unknown method."""
    quotes = parse_quotes(
        csv(
            "2026-01-02,100,102,90,10\n2026-01-01,99,101,1,1\n2026-01-01,98,100,1,1"
        )
    )
    assert list(quotes.bid) == [99, 98, 100]
    with pytest.raises(ValueError, match="Unknown"):
        _ = calculate_vwam(quotes, "bad")


@pytest.mark.parametrize(
    "case", ["ok", "absent", "reversed", "empty_range", "bad"]
)
def test_render_quotes(case: str) -> None:
    """Verify render quotes."""
    st = MagicMock()
    settings = CalculatorSettings(
        vwam_file=csv(),
        vwam_method=MICROPRICE,
        reverse_ticker=False,
        selected_timezone=UTC,
        timezone_label="UTC",
        ticker="BTC_USDT",
    )
    if case == "absent":
        settings.vwam_file = None
    if case == "reversed":
        settings.reverse_ticker = True
    if case == "bad":
        settings.vwam_file = csv("bad,100,102,1,1")
    start = pd.Timestamp(
        "2026-01-02" if case == "empty_range" else "2026-01-01", tz="UTC"
    )
    render_vwam(
        st,
        settings,
        start_at=start,
        end_at=pd.Timestamp("2026-01-03", tz="UTC"),
    )
    assert mock_child(st, "plotly_chart").call_count == (case == "ok")
    assert mock_child(st, "error").call_count == (case == "bad")
    assert mock_child(st, "warning").call_count == (
        case in {"reversed", "empty_range"}
    )
    if case == "ok":
        exported = pd.read_csv(
            StringIO(string(call_args(mock_child(st, "download_button"))[1]))
        )
        assert exported.vwam.iloc[0] == pytest.approx(101.8)
