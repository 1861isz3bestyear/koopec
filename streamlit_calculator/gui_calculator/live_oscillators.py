# Copyright 2026 anchored-vwam-backtest contributors
"""Independent live order-book and Bitget loan-growth charts for Options GEX."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import plotly.graph_objects as go
import requests
import streamlit as st

from gui_calculator.live_oscillator_data import (
    BookObservation,
    fetch_book,
)
from gui_calculator.oscillator_charts import (
    add_oscillator_trace as add_oscillator_trace,
)
from gui_calculator.oscillator_charts import (
    oscillator_chart as oscillator_chart,
)

if TYPE_CHECKING:
    from gui_calculator.view_types import IndicatorUI


def render_live_oscillators() -> None:
    """Show both independent charts before any options snapshot is fetched."""
    _ = st.subheader("Live market oscillators")
    _ = st.caption(
        "Two independent charts for market context. No strategy confirmation "
        "or orders are applied. Arrows mark threshold entries only. "
        "Formulas are labeled alternatives "
        "inspired by the reference pictures, not verified reproductions."
    )
    asset = st.radio("Oscillator market", ("BTC", "ETH"), horizontal=True)
    with st.container(border=True):
        _ = st.subheader("Order-book imbalance oscillator")
        if st.toggle("Live order-book oscillator", key="live_book_enabled"):
            _render_book(asset)
        else:
            _render_empty_oscillator(
                st, title="Order-book depth share", asset=asset
            )
            _ = st.info(
                "Enable live order-book updates to start collecting depth"
                " samples."
            )
    with st.container(border=True):
        _ = st.subheader("Margin-loan oscillator")
        if st.toggle("Live margin-loan oscillator", key="live_margin_enabled"):
            from gui_calculator.bitget_view import render_live_bitget

            render_live_bitget(asset)
        else:
            _render_empty_oscillator(
                st, title="Bitget margin loan growth momentum(14)", asset=asset
            )
            _ = st.info(
                "Enable public Bitget margin-loan updates. No API key required."
            )


def _render_empty_oscillator(
    chart_ui: IndicatorUI, *, title: str, asset: str
) -> None:
    """Keep each indicator chart visible while its live feed is stopped."""
    chart = oscillator_chart(title=title, price_label=f"{asset}USDT price")
    _ = chart_ui.plotly_chart(chart, use_container_width=True)


@st.fragment(run_every="1m")
def _render_book(asset: str) -> None:
    """Collect one book observation per minute without fabricated history."""
    try:
        _book_content(asset, st)
    except (
        requests.RequestException,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        OSError,
    ):
        _render_empty_oscillator(
            st, title="Order-book depth share", asset=asset
        )
        _ = st.error(
            "Order-book feed unavailable. Check connectivity and exchange"
            " access."
        )


def _book_content(asset: str, chart_ui: IndicatorUI) -> None:
    """Collect validated observations and render the market indicator."""
    with requests.Session() as session:
        observation = fetch_book(session, asset=asset)
    key = f"live_book_history_{asset}"
    saved = cast("object", st.session_state.get(key, ()))
    history = (
        tuple(
            item
            for item in cast("tuple[object, ...]", saved)
            if isinstance(item, BookObservation)
            and item.timestamp < observation.timestamp
        )
        if isinstance(saved, tuple)
        else ()
    )
    history = (*history[-1439:], observation)
    st.session_state[key] = history
    chart = oscillator_chart(
        title=f"{asset} order-book depth share · Bybit linear top 50",
        price_label=f"{asset}USDT midpoint",
    )
    times = [item.timestamp for item in history]
    _ = chart.add_trace(
        go.Scatter(
            x=times,
            y=[item.price for item in history],
            name="Midpoint",
            mode="lines+markers" if len(history) == 1 else "lines",
            line={"color": "#f59e0b"},
        ),
        row=1,
        col=1,
    )
    add_oscillator_trace(chart, times, [item.oscillator for item in history])
    _ = chart_ui.plotly_chart(chart, use_container_width=True)
    _ = st.caption(
        "100 * bid quantity / (bid + ask quantity), top 50 levels per "
        "side. 50 = balanced depth; 0 = ask-only; 100 = bid-only. "
        f"Last exchange observation: {observation.timestamp.isoformat()}. "
        "Samples accumulate in this session, up to 1,440 points; "
        "refreshes every minute. Resting orders can be cancelled."
    )
