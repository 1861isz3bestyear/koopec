# Copyright 2026 anchored-vwam-backtest contributors
"""Expose local SQLite coverage and cache immutable archive versions."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import koopec_calculus
import pandas as pd
import streamlit as st
from shared.option_levels import DEFAULT_LEVEL_RANGE, OptionLevelRange
from snapshot_tunnel.local_archive import (
    load_archive_oscillators,
    load_archive_snapshot_at,
    load_archive_snapshots,
)

from gui_calculator.local_archive import inspect_archive

if TYPE_CHECKING:
    from datetime import datetime

    from snapshot_tunnel.archive_model import LocalArchiveSource
    from snapshot_tunnel.archived_market import ArchivedOscillators
    from snapshot_tunnel.options_model import Snapshot


def default_archive_path() -> Path:
    """Locate the consolidated download, independently of shell directory.

    Returns:
        Configured archive path or the gex_downloads snapshot beside Koopec.

    """
    return Path(
        os.environ.get(
            "GUI_CALCULATOR_ARCHIVE",
            str(
                Path(__file__).resolve().parents[3]
                / "gex_downloads/tunnel_inputs.sqlite"
            ),
        )
    )


@st.cache_data(show_spinner=False)
def archive_snapshots(source: LocalArchiveSource) -> tuple[Snapshot, ...]:
    """Cache only daily chains, invalidating when the downloaded file changes.

    Returns:
        Complete daily BTC snapshots.

    """
    return load_archive_snapshots(source)


@st.cache_data(show_spinner=False)
def archive_snapshot_at(
    source: LocalArchiveSource, cutoff: datetime
) -> Snapshot | None:
    """Cache the latest recorded profile at the selected history cutoff.

    Returns:
        A complete chain available at or before the cutoff.

    """
    return load_archive_snapshot_at(source, cutoff)


@st.cache_data(show_spinner="Calculating archived GEX history")
def archive_gex_history(
    source: LocalArchiveSource,
    *,
    level_range: OptionLevelRange = DEFAULT_LEVEL_RANGE,
) -> pd.DataFrame:
    """Cache scalar analytics for every chain without retaining all raw chains.

    Returns:
        Full recorded history, independent of daily execution-plan selection.

    """
    rows = koopec_calculus.archive_gex_history(
        source.path,
        level_range.distance if level_range.enabled else None,
        version=(source.modified_ns, source.size),
    )
    history = pd.DataFrame(
        rows,
        columns=[
            "time",
            "options_price",
            "options_gex",
            "options_call_gex",
            "options_put_gex",
            "options_absolute_gex",
            "options_gamma_flip",
            "options_call_1",
            "options_call_2",
            "options_put_1",
            "options_put_2",
        ],
    )
    history["time"] = pd.to_datetime(history["time"], unit="us", utc=True)
    history["options_gex_time"] = history["time"]
    return history


@st.cache_data(show_spinner="Loading recorded archive oscillators")
def archive_oscillators(source: LocalArchiveSource) -> ArchivedOscillators:
    """Cache parsed independent streams by the source snapshot version.

    Returns:
        Recorded oscillator streams with explicit missing-data warmup.

    """
    return load_archive_oscillators(source)


def render_local_archive() -> LocalArchiveSource | None:
    """Choose a local archive by path and show coverage before loading.

    Returns:
        Selected local snapshot version, or none when the toggle is off.

    """
    if not st.toggle(
        "Load local GEX archive", value=True, key="load_local_gex_archive"
    ):
        return None
    path = Path(
        st.text_input(
            "Local GEX archive path",
            value=str(default_archive_path()),
            help="Enter the SQLite archive file path on the app's machine.",
        ).strip()
    ).expanduser()
    try:
        source = inspect_archive(path)
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        _ = st.error(f"Cannot read local archive {path}: {exc}")
        st.stop()
    _ = st.info(
        f"Archived BTC strategy window (UTC): {source.start:%Y-%m-%d %H:%M:%S}"
        f" to {source.end:%Y-%m-%d %H:%M:%S}. "
        f"Duration: {source.end - source.start}. "
        f"{len(source.collections):,} complete options collections."
    )
    _ = st.caption(
        "Snapshot tunnel reads GEX and independent book, margin and OI receipts"
        " directly from the selected archive. No CSV uploads are needed."
        " Completed price candles come from the selected candle source. Missing"
        " or stale oscillator evidence never votes."
    )
    return source
