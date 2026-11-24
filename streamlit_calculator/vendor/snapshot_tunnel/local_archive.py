# Copyright 2026 anchored-vwam-backtest contributors
"""Load local tunnel replay inputs without CSV conversion or live backfill."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import koopec_calculus
from market_storage.archive import Archive
from market_storage.inputs import CalculationInputs
from market_storage.models import Source, Window
from snapshot_tunnel.archive_export import collection_windows
from snapshot_tunnel.archive_model import LocalArchiveSource, RecordedCollection
from snapshot_tunnel.archived_market import (
    ArchivedOscillators,
    calculate_oscillators,
)
from snapshot_tunnel.options_model import Option, Snapshot
from snapshot_tunnel.tunnel import OiConfirmationMode, oscillator_vote
from snapshot_tunnel.tunnel_flow import (
    OscillatorObservation,
    TunnelFlow,
    momentum_votes,
    oi_confirmation_series,
    oi_signal_direction,
)
from snapshot_tunnel.validation import unix_microseconds

if TYPE_CHECKING:
    from pathlib import Path

    from market_storage.models import Observation
    from snapshot_tunnel.oi_divergence import DivergenceSeries
    from snapshot_tunnel.tunnel import TunnelSettings


def inspect_archive(path: Path) -> LocalArchiveSource:
    """Inspect SQLite metadata before downloading prices or parsing chains.

    Returns:
        Versioned coverage suitable for cached loading and default dates.

    Raises:
        ValueError: If no complete successful BTC chains exist.

    """
    stat = path.stat()
    records = collection_windows(path, asset="BTC")
    if not records:
        msg = "The local archive has no complete successful BTC options chains."
        raise ValueError(msg)
    return LocalArchiveSource(
        path=path,
        modified_ns=stat.st_mtime_ns,
        size=stat.st_size,
        collections=records,
    )


def require_archive_version(source: LocalArchiveSource) -> None:
    """Reject changed files rather than combine data from different downloads.

    Raises:
        ValueError: If the source has been replaced since coverage inspection.

    """
    stat = source.path.stat()
    if (stat.st_mtime_ns, stat.st_size) != (source.modified_ns, source.size):
        msg = (
            "Local archive changed while loading; refresh to load its new"
            " window."
        )
        raise ValueError(msg)


def daily_collections(
    source: LocalArchiveSource,
) -> tuple[RecordedCollection, ...]:
    """Select nearest 08:15 UTC receipts before decompressing full chains.

    Returns:
        At most one complete collection per UTC day, with earlier ties first.

    """
    indices = koopec_calculus.daily_receipts([
        (index, unix_microseconds(record.window.end))
        for index, record in enumerate(source.collections)
    ])
    return tuple(source.collections[index] for index in indices)


def load_archive_snapshots(source: LocalArchiveSource) -> tuple[Snapshot, ...]:
    """Read only the daily chains used by Snapshot tunnel.

    Returns:
        Validated daily chains at their actual availability times.

    """
    return tuple(_snapshot(row) for row in _replay_snapshots(source))


def load_archive_snapshot_at(
    source: LocalArchiveSource, cutoff: datetime
) -> Snapshot | None:
    """Read the latest complete chain available at a chart's cutoff.

    Returns:
        The recorded profile without substituting a daily execution plan.

    """
    rows = _replay_snapshots(source, cutoff_us=unix_microseconds(cutoff))
    return _snapshot(rows[0]) if rows else None


def _replay_snapshots(
    source: LocalArchiveSource, *, cutoff_us: int | None = None
) -> list[koopec_calculus.ArchiveSnapshotRow]:
    return koopec_calculus.archive_replay_snapshots(
        source.path, (source.modified_ns, source.size), cutoff_us
    )


def _snapshot(row: koopec_calculus.ArchiveSnapshotRow) -> Snapshot:
    receipt_us, spot, contracts = row
    return Snapshot(
        asset="BTC",
        timestamp=datetime(1970, 1, 1, tzinfo=UTC)
        + timedelta(microseconds=receipt_us),
        spot=spot,
        options=tuple(
            Option(
                exchange="DERIBIT",
                expiry=datetime.fromtimestamp(expiry_ms / 1000, UTC),
                strike=strike,
                side=side,
                open_interest=interest,
                multiplier=multiplier,
                iv=iv,
            )
            for _, side, strike, expiry_ms, iv, interest, multiplier in (
                contracts
            )
        ),
    )


def load_archive_oscillators(source: LocalArchiveSource) -> ArchivedOscillators:
    """Read bounded hourly batches and retain only independent flow evidence.

    Returns:
        Recorded book, margin and OI streams; missing history stays missing.

    """
    require_archive_version(source)
    observations: list[Observation] = []
    start = source.collections[0].window.start
    archive = Archive(path=source.path)
    while start <= source.end:
        end = min(start + timedelta(hours=1), source.end)
        observations.extend(
            archive.load(
                Window(asset="BTC", start=start, end=end),
                sources=frozenset((
                    Source.DEPTH,
                    Source.GROWTH_HOURLY,
                    Source.OI,
                    Source.TICKER,
                )),
            )
        )
        start = end + timedelta(microseconds=1)
    require_archive_version(source)
    return calculate_oscillators(
        CalculationInputs(gex=(), observations=tuple(observations))
    )


def divergence_votes(
    series: DivergenceSeries,
    *,
    mode: OiConfirmationMode = OiConfirmationMode.DIVERGENCE,
) -> tuple[OscillatorObservation, ...]:
    """Convert recorded five-minute OI signals without assuming receipt times.

    Returns:
        Causal directional votes, with warmup and gaps explicitly unavailable.

    """
    if mode == OiConfirmationMode.CONVERGENCE:
        series = oi_confirmation_series(
            tuple(point.sample for point in series.points),
            mode=mode,
            interval=timedelta(minutes=5),
        )
    signals = {signal.detected: signal for signal in series.signals}
    direction = 0
    votes: list[OscillatorObservation] = []
    for index, point in enumerate(series.points):
        if series.states[index] is None:
            direction = 0
        signal = signals.get(point.available)
        if signal is not None:
            direction = oi_signal_direction(signal, mode=mode)
        votes.append(
            OscillatorObservation(
                available=point.available,
                direction=direction,
                calculatable=series.states[index] is not None,
            )
        )
    return tuple(votes)


def archive_tunnel_flow(
    streams: ArchivedOscillators, settings: TunnelSettings
) -> TunnelFlow:
    """Apply the chosen voting thresholds to independent archive streams.

    Returns:
        Book, margin and OI confirmations with recorded availability times.

    """
    return TunnelFlow(
        book=tuple(
            OscillatorObservation(
                available=point.available,
                direction=oscillator_vote(point.value, settings),
            )
            for point in streams.order_book
            if point.value is not None
        ),
        margin=tuple(
            OscillatorObservation(
                available=point.available,
                direction=oscillator_vote(point.value, settings),
            )
            for point in streams.margin
            if point.value is not None
        ),
        oi_momentum=momentum_votes(streams.oi),
        oi=divergence_votes(streams.oi, mode=OiConfirmationMode.DIVERGENCE),
        oi_convergence=divergence_votes(
            streams.oi, mode=OiConfirmationMode.CONVERGENCE
        ),
    )
