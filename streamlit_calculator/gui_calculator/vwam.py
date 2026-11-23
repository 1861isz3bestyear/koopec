# Copyright 2026 anchored-vwam-backtest contributors
"""Bid/ask indicators from recorded best quotes, independent of candle fills."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from shared.time_utils import chart_times

if TYPE_CHECKING:
    from datetime import datetime, tzinfo

    from gui_calculator.settings import CalculatorSettings, CSVSource
    from gui_calculator.view_types import IndicatorUI

MICROPRICE = "Microprice"
SAME_SIDE = "Same-side weighted price"
QUOTE_COLUMNS = ["bid", "ask", "bid_size", "ask_size"]
MILLISECOND_TIMESTAMP_THRESHOLD = 10_000_000_000


def parse_quotes(uploaded_file: CSVSource) -> pd.DataFrame:
    """Handle parse quotes.

    Returns:
        The resulting value.

    Raises:
        ValueError: If the operation cannot be completed.

    """
    quotes = pd.read_csv(uploaded_file)
    quotes.columns = quotes.columns.str.strip().str.lower()
    if quotes.columns.duplicated().any():
        msg = "Quote CSV has duplicate column names."
        raise ValueError(msg)
    if not {"time", *QUOTE_COLUMNS}.issubset(quotes.columns):
        msg = "Quote CSV requires time, bid, ask, bid_size, ask_size."
        raise ValueError(msg)
    quotes = quotes[["time", *QUOTE_COLUMNS]].copy()
    if quotes.empty:
        msg = "Quote CSV is empty."
        raise ValueError(msg)
    timestamps = quotes["time"]
    if pd.api.types.is_numeric_dtype(timestamps):
        unit = (
            "ms"
            if pd.to_numeric(timestamps).astype(float).median()
            > MILLISECOND_TIMESTAMP_THRESHOLD
            else "s"
        )
        quotes["time"] = pd.to_datetime(
            timestamps, unit=unit, utc=True, errors="coerce"
        )
    else:
        quotes["time"] = pd.to_datetime(
            timestamps, utc=True, errors="coerce", format="mixed"
        )
    quotes[QUOTE_COLUMNS] = quotes[QUOTE_COLUMNS].apply(
        pd.to_numeric, errors="coerce"
    )
    validate_quotes(quotes)
    # Equal timestamps may contain distinct quote updates; retain their order.
    return quotes.sort_values("time", kind="stable").reset_index(drop=True)


def validate_quotes(quotes: pd.DataFrame) -> None:
    """Handle validate quotes.

    Raises:
        ValueError: If the operation cannot be completed.

    """
    if not {"time", *QUOTE_COLUMNS}.issubset(quotes.columns):
        msg = "Quotes require time, bid, ask, bid_size, ask_size."
        raise ValueError(msg)
    if (
        quotes["time"].isna().any()
        or not np.isfinite(quotes[QUOTE_COLUMNS].to_numpy(dtype=float)).all()
    ):
        msg = (
            "Quote CSV contains missing or invalid timestamps, prices, or"
            " sizes."
        )
        raise ValueError(msg)
    if (quotes[["bid", "ask"]] <= 0).any().any():
        msg = "Bid and ask prices must be positive."
        raise ValueError(msg)
    if (quotes["bid"] > quotes["ask"]).any():
        msg = "Bid must not exceed ask."
        raise ValueError(msg)
    if (quotes[["bid_size", "ask_size"]] < 0).any().any() or (
        quotes["bid_size"] + quotes["ask_size"] <= 0
    ).any():
        msg = "Quote sizes must be nonnegative with a positive total."
        raise ValueError(msg)
    if not np.isfinite(quotes["bid_size"] + quotes["ask_size"]).all():
        msg = "Total quote size must be finite."
        raise ValueError(msg)


def calculate_vwam(
    quotes: pd.DataFrame, method: str = MICROPRICE
) -> pd.DataFrame:
    """Instantaneous top-of-book measure; no accumulation or traded-volume.

    weight.

    Returns:
        The computed result.

    Raises:
        ValueError: If the operation cannot be completed.

    """
    if method not in {MICROPRICE, SAME_SIDE}:
        msg = "Unknown VWAM method."
        raise ValueError(msg)
    result = quotes.copy()
    total = result["bid_size"].astype(float) + result["ask_size"].astype(float)
    bid_weight = result["bid_size"].astype(float) / total
    ask_weight = result["ask_size"].astype(float) / total
    if method == MICROPRICE:
        result["vwam"] = (
            result["ask"].astype(float) * bid_weight
            + result["bid"].astype(float) * ask_weight
        )
    else:
        result["vwam"] = (
            result["bid"].astype(float) * bid_weight
            + result["ask"].astype(float) * ask_weight
        )
    result["mid"] = (
        result["bid"].astype(float) / 2 + result["ask"].astype(float) / 2
    )
    result["spread"] = result["ask"].astype(float) - result["bid"].astype(float)
    result["imbalance"] = bid_weight - ask_weight
    return result


def build_vwam_chart(
    quotes: pd.DataFrame,
    method: str,
    *,
    selected_timezone: tzinfo,
    timezone_label: str,
    ticker: str,
) -> go.Figure:
    """Handle build vwam chart.

    Returns:
        The resulting value.

    """
    fig = go.Figure()
    times = chart_times(quotes["time"], selected_timezone)
    for column, label, color in [
        ("bid", "Best bid", "#0f9d58"),
        ("ask", "Best ask", "#d93025"),
        ("mid", "Mid-price", "#888888"),
        ("vwam", f"VWAM — {method}", "#1a73e8"),
    ]:
        _ = fig.add_trace(
            go.Scatter(
                x=times,
                y=quotes[column],
                name=label,
                line={"color": color},
                mode="lines",
            )
        )
    _ = fig.update_layout(
        title=f"{ticker} bid/ask VWAM",
        xaxis_title=f"Time ({timezone_label})",
        yaxis_title="Price",
        yaxis_tickformat=",.2f",
        hovermode="x unified",
    )
    return fig


def render_vwam(
    st: IndicatorUI,
    settings: CalculatorSettings,
    *,
    start_at: datetime,
    end_at: datetime,
) -> None:
    """Handle render vwam."""
    uploaded = settings.vwam_file
    if uploaded is None:
        return
    if settings.reverse_ticker:
        _ = st.warning(
            "Turn off Reverse ticker to view quotes in their original market"
            " units."
        )
        return
    try:
        quotes = parse_quotes(uploaded)
        quotes = quotes[
            (quotes["time"] >= start_at) & (quotes["time"] <= end_at)
        ]
        if quotes.empty:
            _ = st.warning("No bid/ask quotes in the selected history range.")
            return
        quotes = calculate_vwam(quotes, settings.vwam_method)
    except (ValueError, pd.errors.ParserError) as exc:
        _ = st.error(f"Could not load bid/ask VWAM: {exc}")
        return
    _ = st.caption(
        "Recorded best quotes for the selected ticker. VWAM uses displayed"
        " sizes; this chart does not change AVWAP strategy trades or"
        " performance."
    )
    _ = st.plotly_chart(
        build_vwam_chart(
            quotes,
            settings.vwam_method,
            selected_timezone=settings.selected_timezone,
            timezone_label=settings.timezone_label,
            ticker=settings.ticker,
        ),
        use_container_width=True,
    )
    _ = st.download_button(
        "Download bid/ask VWAM CSV",
        quotes.to_csv(index=False),
        file_name="bid_ask_vwam.csv",
        mime="text/csv",
    )
