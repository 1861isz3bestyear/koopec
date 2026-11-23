# Copyright 2026 anchored-vwam-backtest contributors
"""Collect and inspect reusable point-in-time options history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING

import streamlit as st

from gui_calculator.options_source import refresh_options
from gui_calculator.options_store import load_snapshots, snapshots_csv

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot

CADENCES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}


@st.fragment(run_every="1m")
def render_options_archive() -> None:
    """Collect complete BTC chains and expose honest archive coverage."""
    with st.expander("Reusable options history"):
        if not st.toggle("Load archive controls and coverage"):
            return
        cadence = st.selectbox(
            "Options collection cadence", list(CADENCES), key="archive_cadence"
        )
        seconds = CADENCES[cadence]
        enabled = st.toggle("Collect BTC chains while this page is open")
        manual = st.button("Save BTC chain now")
        now = datetime.now(UTC)
        history = tuple(
            item for item in load_snapshots() if item.asset == "BTC"
        )
        due = not history or now - history[-1].timestamp >= timedelta(
            seconds=seconds
        )
        if manual or (enabled and due):
            refresh_options("BTC")
            history = tuple(
                item for item in load_snapshots() if item.asset == "BTC"
            )
        _ = st.caption(
            "Full chains are saved in options_history.sqlite and reused by"
            " Saved history and Deribit API strategies. Collection runs while"
            " this page is open; failures leave gaps. No historical backfill."
            " Existing observations are retained without automatic deletion."
        )
        _ = st.code(
            "uv run python -m gui_calculator.options_collector --asset BTC"
            f" --interval {seconds}",
            language="bash",
        )
        _ = st.caption(
            "Run this command in a separate terminal for collection when the"
            " GUI is closed. Use one collector per asset to avoid duplicates."
            " A 1m archive supports 1m, 5m, 15m, 1h and 1d calculations."
            " Coarser archives carry OI/IV forward between observations;"
            " repricing does not recover unobserved positioning changes."
        )
        _render_coverage(history, now=now, cadence=timedelta(seconds=seconds))


def _render_coverage(
    history: tuple[Snapshot, ...], *, now: datetime, cadence: timedelta
) -> None:
    """Report the trailing year's observations without implying continuity."""
    start = now - timedelta(days=365)
    selected = tuple(item for item in history if start <= item.timestamp <= now)
    _ = st.caption(f"Trailing 365 days: {len(selected):,} BTC observations.")
    if not selected:
        _ = st.info(
            "No saved BTC chains in the last year. Start collecting now."
        )
        return
    times = (start, *(item.timestamp for item in selected), now)
    gaps = tuple(later - earlier for earlier, later in pairwise(times))
    missing = sum(gap > cadence * 2 for gap in gaps)
    _ = st.caption(
        f"First receipt: {selected[0].timestamp.isoformat()} · Last receipt:"
        f" {selected[-1].timestamp.isoformat()} · Largest interval including"
        f" range edges: {max(gaps)} · Intervals over twice the selected"
        f" cadence: {missing:,}. Counts do not guarantee complete coverage."
    )
    _render_gaps(times, cadence=cadence)
    _ = st.download_button(
        "Download last year of BTC chains CSV",
        snapshots_csv(selected),
        file_name="btc_options_history.csv",
        mime="text/csv",
    )


def _render_gaps(times: tuple[datetime, ...], *, cadence: timedelta) -> None:
    """Expose exact sparse intervals rather than implying continuous history."""
    gaps = tuple(
        (earlier, later)
        for earlier, later in pairwise(times)
        if later - earlier > cadence * 2
    )
    if not gaps:
        _ = st.caption("No observation intervals exceed twice this cadence.")
        return
    _ = st.warning(
        "Missing options observations: the intervals below exceed twice the"
        " selected collection cadence. Bounds are receipts or report edges;"
        " no intervening chains are saved. Carried chains can remain usable"
        " only until the strategy freshness or expiry limit. This report does"
        " not fill missing dates or imply continuous historical coverage."
    )
    _ = st.table({
        "Gap start UTC": [start.isoformat() for start, _ in gaps],
        "Gap end UTC": [end.isoformat() for _, end in gaps],
        "Time without a new observation": [
            str(end - start) for start, end in gaps
        ],
    })
