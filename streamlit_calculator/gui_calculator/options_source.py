# Copyright 2026 anchored-vwam-backtest contributors
"""Explicit options provenance and live collection controls."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, time, timedelta
from typing import Literal

import requests
import streamlit as st
from shared.daily_gex import DailySettings
from snapshot_tunnel.daily_plans import daily_boundary
from snapshot_tunnel.options_model import Snapshot, parse_snapshots

from gui_calculator.options_collector import collect_once
from gui_calculator.options_store import load_snapshots


def render_source(example: str) -> tuple[Snapshot, ...]:
    """Select imported, saved or explicitly synthetic observations.

    Returns:
        Validated available history, or an empty selection.

    """
    source = st.selectbox(
        "Options data source",
        ["Saved history / Deribit API", "CSV", "Synthetic demo"],
        key="options_data_source",
    )
    if source == "Synthetic demo":
        _ = st.warning(
            "SYNTHETIC DATA — not exchange history or evidence of returns."
        )
        return parse_snapshots(example)
    if source == "CSV":
        uploaded = st.file_uploader("Options snapshots CSV", type=["csv"])
        if uploaded is None:
            return ()
        _ = st.caption(
            "CSV timestamps must represent actual data availability."
        )
        snapshots = parse_snapshots(uploaded.getvalue().decode("utf-8-sig"))
        if any(
            option.exchange == "DERIBIT_RESEARCH_APPROXIMATE"
            for snapshot in snapshots
            for option in snapshot.options
        ):
            _ = st.warning(
                "APPROXIMATE RESEARCH DATA: next-day snapshot times, median "
                "spot and contract conventions are assumed. Chain coverage "
                "is unverified. Returns are not point-in-time evidence."
            )
        return snapshots
    asset = st.selectbox("Collect underlying", ["BTC", "ETH"])
    selected: Literal["BTC", "ETH"] = "ETH" if asset == "ETH" else "BTC"
    snapshots = load_snapshots()
    automatic = st.toggle("Auto-refresh Deribit every 5 minutes", value=False)
    daily = st.toggle("Daily Deribit refresh (UTC)", value=False)
    refresh = (
        st.time_input("Deribit daily time (UTC)", value=time(8, 15))
        if daily
        else time(8, 15)
    )
    manual = st.button("Fetch and save current Deribit chain")
    available = [item for item in snapshots if item.asset == selected]
    due = automatic and (
        not available
        or datetime.now(UTC) - available[-1].timestamp >= timedelta(minutes=5)
    )
    if daily:
        boundary = daily_boundary(
            datetime.now(UTC), DailySettings(refresh=refresh)
        )
        due = due or not available or available[-1].timestamp < boundary
    if manual or due:
        refresh_options(selected)
        snapshots = load_snapshots()
    _ = st.caption(
        "Daily collection: add --daily --daily-at "
        + refresh.isoformat(timespec="minutes")
        + ". Continuous collection: uv run python -m"
        " gui_calculator.options_collector --asset "
        + selected
        + " --interval 300. Runs independently of this page. Current API data"
        " cannot reconstruct past OI or IV. Deribit coin-settled options use"
        " a normalized USD Black-Scholes approximation."
    )
    if snapshots:
        latest = max(item.timestamp for item in snapshots)
        age = datetime.now(UTC) - latest
        _ = st.caption(f"Last receipt: {latest.isoformat()} · age: {age}")
    else:
        _ = st.info(
            "No saved options history. Fetch a chain or start the collector."
        )
    return snapshots


def refresh_options(asset: Literal["BTC", "ETH"]) -> None:
    """Show collection success or failure while retaining saved history."""
    try:
        count = collect_once(asset=asset)
        st.session_state[f"options_candles_ready_{asset}"] = True
        _ = st.success(f"Saved complete observation: {count} contracts.")
    except (requests.ConnectionError, requests.Timeout) as exc:
        _ = st.error(
            "Deribit update failed: connection could not be established. "
            "Check access to www.deribit.com and your VPN/proxy settings, "
            "then retry. Saved history is unchanged. "
            f"Details: {exc}"
        )
    except (
        requests.RequestException,
        ValueError,
        TypeError,
        KeyError,
        sqlite3.Error,
    ) as exc:
        _ = st.error(f"Deribit update failed: {exc}")
