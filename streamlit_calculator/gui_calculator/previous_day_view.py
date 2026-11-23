# Copyright 2026 anchored-vwam-backtest contributors
"""Compare a live observation with recorded data from the prior UTC day."""

from __future__ import annotations

import sqlite3
from datetime import UTC, timedelta
from typing import TYPE_CHECKING

import streamlit as st

from gui_calculator.comparison_view import render_comparison_pair
from gui_calculator.options_store import load_snapshots
from gui_calculator.previous_day_comparison import (
    previous_day_snapshot as previous_day_snapshot,
)

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot


def render_previous_day_comparison(snapshot: Snapshot) -> None:
    """Look up historical data after an explicit comparison request."""
    requested = (
        snapshot.timestamp.astimezone(UTC) - timedelta(days=1)
    ).replace(second=0, microsecond=0)
    _ = st.caption(
        f"Displayed snapshot: {snapshot.timestamp.isoformat()}. Request"
        f" previous day: {requested:%Y-%m-%d %H:%M} UTC · {snapshot.asset}."
    )
    identity = (snapshot.asset, snapshot.timestamp.isoformat())
    if st.button("Compare with previous day"):
        st.session_state["options_previous_day_request"] = identity
    if st.session_state.get("options_previous_day_request") != identity:
        return
    try:
        with st.spinner(
            "Looking for the previous day's recorded Deribit chain…"
        ):
            previous = previous_day_snapshot(snapshot, load_snapshots())
    except ValueError as exc:
        _ = st.info(str(exc))
        return
    except sqlite3.Error as exc:
        _ = st.error(f"Could not read saved options history: {exc}")
        return
    if not requested <= previous.timestamp < requested + timedelta(minutes=1):
        _ = st.info(
            "No snapshot in the requested minute. Using the closest saved"
            " snapshot on the previous UTC day:"
            f" {previous.timestamp.isoformat()}."
        )
    render_comparison_pair(previous, snapshot)
