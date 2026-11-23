# Copyright 2026 anchored-vwam-backtest contributors
"""Explicit, minute-specific historical snapshot requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal

import requests
import streamlit as st
from snapshot_tunnel.options_data import fetch_snapshot
from snapshot_tunnel.options_model import Snapshot, parse_snapshots

from gui_calculator.options_store import load_snapshots, store_snapshot
from gui_calculator.snapshot_analytics import (
    select_observation as select_observation,
)
from gui_calculator.snapshot_history_view import render_snapshot_history


def render_snapshot_request(example: str) -> Snapshot | None:
    """Collect controls and preview available uploaded observations.

    Returns:
        The requested validated observation, or no pending calculation.

    Raises:
        ValueError: If an upload or the requested observation is missing.

    """
    today = datetime.now(UTC).date()
    assets: tuple[Literal["BTC", "ETH"], ...] = ("BTC", "ETH")
    asset = st.selectbox("Options asset", assets)
    with st.expander("Data settings"):
        source = st.selectbox(
            "Options data source",
            [
                "Deribit API (latest snapshot)",
                "Saved history / Deribit API",
                "CSV",
                "Synthetic demo",
            ],
            key="options_data_source",
        )
        uploaded = (
            st.file_uploader("Options snapshots CSV", type=["csv"])
            if source == "CSV"
            else None
        )
        _ = st.caption(
            "Latest downloads current data and saves it for future use; "
            "date and time apply only to saved history, CSV and demo. "
            "Historical sources use the selected UTC minute. "
            "Historical OI and IV must already be saved or imported."
        )
        _ = st.download_button(
            "Download example CSV", example, file_name="options_snapshot.csv"
        )
    if source == "Saved history / Deribit API":
        return _saved_snapshot(asset)
    latest = source == "Deribit API (latest snapshot)"
    day = st.date_input(
        "Snapshot date (UTC)",
        value=today if latest else today - timedelta(days=1),
        disabled=latest,
    )
    clock = st.time_input(
        "Snapshot time (UTC)",
        value=time(8, 15),
        step=60,
        disabled=latest,
    )
    if latest:
        _ = st.info(
            "Latest mode downloads the current chain, not the selected"
            " historical date."
        )
    if source == "Synthetic demo":
        _ = st.warning("SYNTHETIC DATA — not exchange history.")
    archive = (
        _select_archive_snapshot(uploaded.getvalue(), asset=asset)
        if source == "CSV" and uploaded is not None
        else None
    )
    requested = datetime.combine(day, clock, tzinfo=UTC)
    calculate = st.button("Calculate", type="primary")
    if source == "Deribit API (latest snapshot)":
        return _latest_snapshot(asset, calculate=calculate)
    if not calculate:
        return None
    if source == "CSV":
        if uploaded is None:
            msg = "Cannot pull options data: upload an options snapshots CSV."
            raise ValueError(msg)
        if archive is None:
            return None
        return select_observation(
            (archive,), asset=asset, requested=archive.timestamp
        )
    snapshots = parse_snapshots(example)
    return select_observation(snapshots, asset=asset, requested=requested)


def _select_archive_snapshot(content: bytes, *, asset: str) -> Snapshot | None:
    """List actual uploaded observations for the selected asset.

    Returns:
        The selected archived observation, or none when the asset is absent.

    """
    snapshots = tuple(
        sorted(
            (
                item
                for item in parse_snapshots(content.decode("utf-8-sig"))
                if item.asset == asset
            ),
            key=lambda item: item.timestamp,
        )
    )
    if not snapshots:
        _ = st.warning(f"The uploaded archive contains no {asset} snapshots.")
        return None
    _ = st.caption(
        f"{len(snapshots)} available {asset} snapshots · "
        f"{snapshots[0].timestamp:%Y-%m-%d} to "
        f"{snapshots[-1].timestamp:%Y-%m-%d}. "
        "The archive selection overrides the manual date and time above."
    )

    def snapshot_label(index: int) -> str:
        return snapshots[index].timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    index = st.selectbox(
        "Available archive snapshot (UTC)",
        range(len(snapshots)),
        format_func=snapshot_label,
    )
    render_snapshot_history(snapshots)
    return snapshots[index]


def _latest_snapshot(
    asset: Literal["BTC", "ETH"], *, calculate: bool
) -> Snapshot | None:
    """Retain the displayed observation across comparison button reruns.

    Returns:
        The last explicitly downloaded snapshot for the selected asset.

    """
    if calculate:
        st.session_state["options_latest_snapshot"] = None
        st.session_state["options_previous_day_request"] = None
        with st.spinner(
            "Downloading Deribit options and Bybit order-book depth…"
        ):
            with requests.Session() as session:
                observation = fetch_snapshot(session, asset=asset)
            store_snapshot(
                observation.snapshot,
                observed_at=observation.observed_at.isoformat(),
            )
        st.session_state["options_latest_snapshot"] = observation.snapshot
    saved = st.session_state.get("options_latest_snapshot")
    if isinstance(saved, Snapshot) and saved.asset == asset:
        return saved
    return None


@dataclass(frozen=True, kw_only=True)
class SavedSnapshotRequest:
    """Bind a displayed historical snapshot to its requested UTC minute."""

    requested: datetime
    snapshot: Snapshot


def _saved_snapshot(asset: str) -> Snapshot | None:
    """Keep a historical observation stable across comparison reruns.

    Returns:
        The observation only while the selected asset and time still match.

    """
    snapshots = load_snapshots()
    requested = _select_saved_time(snapshots, asset=asset)
    if requested is None:
        return None
    if st.button("Calculate", type="primary"):
        st.session_state["options_saved_request"] = None
        st.session_state["options_previous_day_request"] = None
        snapshot = select_observation(
            snapshots, asset=asset, requested=requested
        )
        st.session_state["options_saved_request"] = SavedSnapshotRequest(
            requested=requested, snapshot=snapshot
        )
    saved = st.session_state.get("options_saved_request")
    if (
        isinstance(saved, SavedSnapshotRequest)
        and saved.requested == requested
        and saved.snapshot.asset == asset
    ):
        return saved.snapshot
    return None


def _select_saved_time(
    snapshots: tuple[Snapshot, ...], *, asset: str
) -> datetime | None:
    """Preview saved dates and select an actual observation within the day.

    Returns:
        The selected timestamp, or none when the asset has no saved history.

    """
    available = sorted({
        snapshot.timestamp.astimezone(UTC)
        for snapshot in snapshots
        if snapshot.asset == asset
    })
    if not available:
        _ = st.info(
            f"No archived {asset} snapshots. Import a CSV or collect a latest "
            "snapshot."
        )
        return None
    days = sorted({observed.date() for observed in available})
    _ = st.caption(
        "Available dates (UTC): " + ", ".join(day.isoformat() for day in days)
    )
    day = st.selectbox(
        "Available saved snapshot dates (UTC)",
        days,
        index=len(days) - 1,
        key=f"saved_snapshot_date_{asset}",
    )
    times = [observed for observed in available if observed.date() == day]
    _ = st.caption(
        f"Available times on {day} (UTC): "
        + ", ".join(f"{observed:%H:%M:%S}" for observed in times)
    )

    def time_label(observed: datetime) -> str:
        return observed.strftime("%H:%M:%S UTC · available")

    return st.selectbox(
        "Available saved snapshot times (UTC)",
        times,
        index=len(times) - 1,
        format_func=time_label,
        key=f"saved_snapshot_time_{asset}_{day}",
    )
