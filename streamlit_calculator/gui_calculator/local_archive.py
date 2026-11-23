# Copyright 2026 anchored-vwam-backtest contributors
"""Compatibility exports from the canonical paper Snapshot tunnel package."""

from datetime import datetime
from typing import TYPE_CHECKING

import koopec_calculus
from market_storage.models import Window
from snapshot_tunnel.archive_model import LocalArchiveSource, RecordedCollection
from snapshot_tunnel.local_archive import (
    archive_tunnel_flow as archive_tunnel_flow,
)
from snapshot_tunnel.local_archive import daily_collections as daily_collections
from snapshot_tunnel.local_archive import divergence_votes as divergence_votes
from snapshot_tunnel.local_archive import (
    load_archive_oscillators as load_archive_oscillators,
)
from snapshot_tunnel.local_archive import (
    load_archive_snapshot_at as load_archive_snapshot_at,
)
from snapshot_tunnel.local_archive import (
    load_archive_snapshots as load_archive_snapshots,
)
from snapshot_tunnel.local_archive import (
    require_archive_version as require_archive_version,
)

if TYPE_CHECKING:
    from pathlib import Path


def inspect_archive(path: Path) -> LocalArchiveSource:
    """Read versioned archive coverage through the Rust collection index.

    Returns:
        Complete BTC collection bounds for the calculator's cached loaders.

    """
    stat = path.stat()
    collections = tuple(
        RecordedCollection(
            identity=identity,
            window=Window(
                asset="BTC",
                start=datetime.fromisoformat(start),
                end=datetime.fromisoformat(end),
            ),
        )
        for identity, start, end in koopec_calculus.archive_index(path)
    )
    source = LocalArchiveSource(
        path=path,
        modified_ns=stat.st_mtime_ns,
        size=stat.st_size,
        collections=collections,
    )
    require_archive_version(source)
    return source
