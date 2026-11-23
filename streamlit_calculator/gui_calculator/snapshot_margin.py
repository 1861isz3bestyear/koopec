# Copyright 2026 anchored-vwam-backtest contributors
"""Recorded margin borrowing composition at an options snapshot."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import TYPE_CHECKING

import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
from shared.validation import json_object, numeric_string, object_list

from gui_calculator.bitget_view import (
    render_bitget_margin,
    render_latest_bitget,
)
from gui_calculator.oscillator_charts import (
    add_oscillator_trace,
    oscillator_chart,
)
from gui_calculator.oscillator_dashboard import oscillator_dashboard_html
from gui_calculator.snapshot_oscillator import load_price_history

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot


@dataclass(frozen=True, kw_only=True)
class LoanObservation:
    """Validated loan composition available at a recorded receipt time."""

    available: datetime
    rate: float


def margin_loan_oscillator_rate(quote: float, base: float) -> float:
    """Return quote borrowing share from two quote-currency notionals.

    Returns:
        A rate from zero to 100, with empty balances neutral at 50.

    Raises:
        ValueError: If balances are negative or nonfinite.

    """
    if any(not math.isfinite(value) or value < 0 for value in (quote, base)):
        msg = "Margin loan balances must be finite and nonnegative."
        raise ValueError(msg)
    scale = max(quote, base)
    if scale == 0:
        return 50
    return 100 * (quote / scale) / (quote / scale + base / scale)


def load_margin_history(
    content: str, snapshot: Snapshot, *, days: int
) -> tuple[LoanObservation, ...]:
    """Validate recorded balances and retain causal observations in the window.

    Returns:
        Borrowing composition sorted by receipt time.

    Raises:
        ValueError: If CSV columns, timestamps or balances are invalid.

    """
    reader = csv.DictReader(StringIO(content))
    columns = {"time", "available_at", "quote_loans", "base_loans"}
    if reader.fieldnames is None or not columns.issubset(reader.fieldnames):
        msg = "Required columns: time,available_at,quote_loans,base_loans."
        raise ValueError(msg)
    observations: dict[datetime, LoanObservation] = {}
    start = snapshot.timestamp - timedelta(days=days)
    for row in reader:
        if any(row.get(column) is None for column in columns):
            msg = "Each loan observation must contain all required values."
            raise ValueError(msg)
        observed = datetime.fromisoformat(row["time"])
        available = datetime.fromisoformat(row["available_at"])
        if observed.utcoffset() is None or available.utcoffset() is None:
            msg = "Loan timestamps must include a UTC offset."
            raise ValueError(msg)
        if available < observed:
            msg = "Loan receipt time cannot precede observation time."
            raise ValueError(msg)
        rate = margin_loan_oscillator_rate(
            float(row["quote_loans"]), float(row["base_loans"])
        )
        if start <= observed <= available <= snapshot.timestamp:
            observations[available] = LoanObservation(
                available=available, rate=rate
            )
    return tuple(observations[time] for time in sorted(observations))


def parse_margin_ratios(
    payload: str, snapshot: Snapshot, *, days: int
) -> tuple[LoanObservation, ...]:
    """Validate public OKX quote/base borrowing ratios for the snapshot window.

    Returns:
        Chronological borrowing shares, excluding observations after snapshot.

    Raises:
        ValueError: If the exchange rejects the request or returns invalid data.

    """
    body = json_object(payload)
    if body.get("code") != "0":
        msg = "OKX margin loan history request failed."
        raise ValueError(msg)
    start = snapshot.timestamp - timedelta(days=days)
    observations: dict[datetime, LoanObservation] = {}
    for item in object_list(body["data"]):
        row = object_list(item)
        expected_columns = 2
        if len(row) != expected_columns:
            msg = "Margin history must contain a timestamp and loan ratio."
            raise ValueError(msg)
        stamp = datetime.fromtimestamp(numeric_string(row[0]) / 1000, tz=UTC)
        ratio = numeric_string(row[1])
        rate = margin_loan_oscillator_rate(ratio, 1)
        if start <= stamp <= snapshot.timestamp:
            observation = LoanObservation(available=stamp, rate=rate)
            if stamp in observations and observations[stamp] != observation:
                msg = "Conflicting margin loan ratios at the same timestamp."
                raise ValueError(msg)
            observations[stamp] = observation
    return tuple(observations[stamp] for stamp in sorted(observations))


@st.cache_data(ttl=300, show_spinner=False)
def load_public_margin_history(
    snapshot: Snapshot, *, days: int
) -> tuple[LoanObservation, ...]:
    """Fetch public historical borrowing composition without API credentials.

    Returns:
        Available OKX observations within the selected snapshot window.

    """
    response = requests.get(
        "https://www.okx.com/api/v5/rubik/stat/margin/loan-ratio",
        params={
            "ccy": snapshot.asset,
            "period": "1H" if days <= timedelta(weeks=1).days else "1D",
            "begin": int(
                (snapshot.timestamp - timedelta(days=days)).timestamp() * 1000
            ),
            "end": int(snapshot.timestamp.timestamp() * 1000),
        },
        timeout=15,
    )
    response.raise_for_status()
    return parse_margin_ratios(response.text, snapshot, days=days)


def render_snapshot_margin(snapshot: Snapshot) -> None:
    """Show the standalone balance oscillator with snapshot-aligned prices."""
    if not st.toggle(
        "Show margin loan oscillator", key="snapshot_margin_loan_rate"
    ):
        return
    period = st.selectbox(
        "Margin oscillator history", ("24 hours", "Week", "Month")
    )
    days = {"24 hours": 1, "Week": 7, "Month": 30}[period]
    source = st.selectbox(
        "Margin loan source",
        ("Bitget public loan growth", "OKX ratio / recorded balances"),
        key="snapshot_margin_source",
    )
    if source == "Bitget public loan growth":
        timing = st.selectbox(
            "Margin data time",
            ("Latest available", "Selected options snapshot"),
            help="Latest refreshes independently of the options snapshot.",
        )
        if timing == "Latest available":
            render_latest_bitget(snapshot, days=days)
        else:
            render_bitget_margin(snapshot, days=days)
        return
    uploaded = st.file_uploader(
        f"{snapshot.asset}USDT recorded margin loan balances CSV",
        type=["csv"],
        key=f"snapshot_margin_loans_{snapshot.asset}",
        help=(
            "Columns: time,available_at,quote_loans,base_loans. Use"
            " offset-aware timestamps and USDT notionals for both balances;"
            " convert base loans to USDT at observation time."
        ),
    )
    try:
        loans = (
            load_margin_history(
                uploaded.getvalue().decode("utf-8-sig"), snapshot, days=days
            )
            if uploaded is not None
            else load_public_margin_history(snapshot, days=days)
        )
    except (
        requests.RequestException,
        ValueError,
        OverflowError,
        TypeError,
        KeyError,
    ) as exc:
        _ = st.warning(f"Margin loan oscillator unavailable: {exc}")
        loans = ()
    try:
        with st.spinner("Loading completed Bybit hourly candles…"):
            candles = load_price_history(snapshot, days=days)
    except (
        requests.RequestException,
        ValueError,
        OverflowError,
        TypeError,
        KeyError,
    ) as exc:
        _ = st.warning(f"Margin price history unavailable: {exc}")
        candles = ()
    chart = oscillator_chart(
        title=(
            f"{snapshot.asset} margin_loan_oscillator_rate · {period.lower()}"
        ),
        price_label=f"{snapshot.asset}USDT · Bybit linear",
        thresholds=(38, 62),
    )
    _ = chart.add_trace(
        go.Scatter(
            x=[candle.timestamp for candle in candles],
            y=[candle.close for candle in candles],
            name="Price",
            line={"color": "#f59e0b"},
        ),
        row=1,
        col=1,
    )
    add_oscillator_trace(
        chart,
        [loan.available for loan in loans],
        [loan.rate for loan in loans],
        thresholds=(38, 62),
    )
    _ = chart.update_yaxes(
        title_text="margin_loan_oscillator_rate", row=2, col=1
    )
    _ = chart.update_traces(
        name="margin_loan_oscillator_rate", selector={"name": "Oscillator"}
    )
    _ = chart.update_xaxes(
        range=[snapshot.timestamp - timedelta(days=days), snapshot.timestamp]
    )
    _ = components.html(
        oscillator_dashboard_html(chart), height=1000, scrolling=True
    )
    _ = st.caption(
        (
            "Source: uploaded recorded balances. "
            if uploaded is not None
            else (
                "Source: OKX public margin loan ratio; prices: Bybit linear."
                " Public history reflects exchange timestamps and may be"
                " revised. "
            )
        )
        + "margin_loan_oscillator_rate = 100 * quote loans / (quote loans +"
        " base loans in USDT). Empty balances = 50; extremes at 38 and 62."
        " This measures borrowing composition, not interest rates. Uploaded"
        " receipt times determine CSV availability; the window ends at the"
        " selected options snapshot. The reference provider's exact formula"
        " is unspecified."
    )
    if not loans:
        _ = st.info(
            "No margin loan observations returned in this snapshot window."
            " Upload historical balances for the selected market; price candles"
            " and borrow interest rates cannot reconstruct loan balances."
        )
    if not candles:
        _ = st.info("No completed price candles in this snapshot window.")
