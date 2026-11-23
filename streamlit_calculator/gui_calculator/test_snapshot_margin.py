# Copyright 2026 anchored-vwam-backtest contributors
"""Verify borrowing composition and snapshot receipt boundaries."""

import json
from datetime import timedelta
from io import BytesIO
from unittest.mock import ANY, MagicMock, patch

import pytest
from snapshot_tunnel.options_model import parse_snapshots
from streamlit.testing.v1 import AppTest

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.snapshot_margin import (
    load_margin_history,
    load_public_margin_history,
    margin_loan_oscillator_rate,
    parse_margin_ratios,
)


@pytest.mark.parametrize(
    ("quote", "base", "expected"),
    [(3, 1, 75), (1, 3, 25), (0, 0, 50), (1e308, 1e308, 50)],
)
def test_balance_share(quote: float, base: float, expected: float) -> None:
    """Match the standalone formula, including empty and large balances."""
    assert margin_loan_oscillator_rate(quote, base) == pytest.approx(expected)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_balances(value: float) -> None:
    """Reject invalid external balances on either side."""
    with pytest.raises(ValueError, match="finite"):
        _ = margin_loan_oscillator_rate(value, 1)
    with pytest.raises(ValueError, match="finite"):
        _ = margin_loan_oscillator_rate(1, value)


def test_causal_window() -> None:
    """Exclude old observations and future receipts."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    content = "time,available_at,quote_loans,base_loans\n"
    for days, delay in [(8, 0), (1, 0), (0, 1)]:
        observed = snapshot.timestamp - timedelta(days=days)
        available = observed + timedelta(seconds=delay)
        content += f"{observed.isoformat()},{available.isoformat()},3,1\n"
    loans = load_margin_history(content, snapshot, days=7)
    assert len(loans) == 1
    expected_rate = 75
    assert loans[0].rate == expected_rate
    expected_count = 2
    assert (
        len(load_margin_history(content, snapshot, days=30)) == expected_count
    )


@pytest.mark.parametrize(
    "content",
    [
        "bad",
        "time,available_at,quote_loans,base_loans\n2026-01-01,2026-01-01,1,1",
        "time,available_at,quote_loans,base_loans\n2026-01-02T00:00Z,2026-01-01T00:00Z,1,1",
        "time,available_at,quote_loans,base_loans\n2026-01-01T00:00Z",
    ],
)
def test_invalid_history(content: str) -> None:
    """Reject malformed columns, missing values and invalid timing."""
    with pytest.raises(ValueError, match=r"columns|offset|required|precede"):
        _ = load_margin_history(content, parse_snapshots(EXAMPLE)[0], days=7)


@pytest.mark.parametrize("uploaded", [False, True])
def test_snapshot_chart(*, uploaded: bool) -> None:
    """Render uploaded balances or explicit missing-data status after opt-in."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    stamp = snapshot.timestamp.isoformat()
    content = f"time,available_at,quote_loans,base_loans\n{stamp},{stamp},3,1"
    with (
        patch(
            "gui_calculator.snapshot_margin.load_public_margin_history",
            return_value=load_margin_history(content, snapshot, days=7),
        ) as public,
        patch(
            "streamlit.file_uploader",
            return_value=BytesIO(content.encode()) if uploaded else None,
        ),
        patch(
            "gui_calculator.snapshot_margin.load_price_history", return_value=()
        ) as prices,
        patch("gui_calculator.snapshot_margin.add_oscillator_trace") as trace,
    ):
        app = AppTest.from_string(
            "from gui_calculator.options_gex import EXAMPLE\n"
            "from snapshot_tunnel.options_model import parse_snapshots\n"
            "from gui_calculator.snapshot_margin import"
            " render_snapshot_margin\n"
            "render_snapshot_margin(parse_snapshots(EXAMPLE)[0])\n"
        ).run()
        prices.assert_not_called()
        with patch("gui_calculator.snapshot_margin.render_latest_bitget"):
            _ = app.toggle[0].set_value(True).run()
        _ = app.selectbox[1].select("OKX ratio / recorded balances").run()
        _ = app.selectbox[0].select("Week").run()
        assert not app.exception
        assert len(app.get("iframe")) == 1
        trace.assert_called_with(
            ANY,
            [snapshot.timestamp],
            [75.0],
            thresholds=(38, 62),
        )
        if uploaded:
            public.assert_not_called()
        else:
            public.assert_called_with(snapshot, days=7)
        _ = app.selectbox[0].select("Month").run()
        prices.assert_called_with(snapshot, days=30)


def test_public_margin_ratios() -> None:
    """Normalize ratios and filter both future and old observations."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    data = [
        [
            str(
                int(
                    (snapshot.timestamp + timedelta(days=days)).timestamp()
                    * 1000
                )
            ),
            "3",
        ]
        for days in (1, 0, -8)
    ]
    loans = parse_margin_ratios(
        json.dumps({"code": "0", "data": data}), snapshot, days=7
    )
    assert len(loans) == 1
    expected_rate = 75
    assert loans[0].rate == expected_rate
    assert loans[0].available == snapshot.timestamp


@pytest.mark.parametrize(
    "body",
    [
        {"code": "1"},
        {"code": "0", "data": [["0"]]},
        {"code": "0", "data": [["0", "-1"]]},
        {"code": "0", "data": [["0", "nan"]]},
    ],
)
def test_invalid_public_margin(body: object) -> None:
    """Reject exchange errors and malformed borrowing ratios."""
    with pytest.raises(ValueError, match=r"failed|contain|finite"):
        _ = parse_margin_ratios(
            json.dumps(body), parse_snapshots(EXAMPLE)[0], days=7
        )


def test_public_margin_request() -> None:
    """Load the default feed with asset and snapshot-aligned request bounds."""
    snapshot = parse_snapshots(EXAMPLE)[0]
    stamp = str(int(snapshot.timestamp.timestamp() * 1000))
    load_public_margin_history.clear()
    response = MagicMock(text=json.dumps({"code": "0", "data": [[stamp, "3"]]}))
    with patch(
        "gui_calculator.snapshot_margin.requests.get", return_value=response
    ) as get:
        loans = load_public_margin_history(snapshot, days=7)
        assert len(loans) == 1
        get.assert_called_once_with(
            "https://www.okx.com/api/v5/rubik/stat/margin/loan-ratio",
            params={
                "ccy": snapshot.asset,
                "period": "1H",
                "begin": int(
                    (snapshot.timestamp - timedelta(days=7)).timestamp() * 1000
                ),
                "end": int(snapshot.timestamp.timestamp() * 1000),
            },
            timeout=15,
        )
    load_public_margin_history.clear()
