# Copyright 2026 anchored-vwam-backtest contributors
"""Compatibility exports from the canonical paper Snapshot tunnel package."""

from snapshot_tunnel.archive_export import (
    COLLECTION_QUERIES as COLLECTION_QUERIES,
)
from snapshot_tunnel.archive_export import Arguments as Arguments
from snapshot_tunnel.archive_export import (
    archive_collections as archive_collections,
)
from snapshot_tunnel.archive_export import (
    archived_snapshot as archived_snapshot,
)
from snapshot_tunnel.archive_export import (
    collection_windows as collection_windows,
)
from snapshot_tunnel.archive_export import export_options as export_options
from snapshot_tunnel.archive_export import main as main
from snapshot_tunnel.archive_export import write_options as write_options

if __name__ == "__main__":
    _ = main()
