# Copyright 2026 anchored-vwam-backtest contributors
"""Persist option observations without rewriting their availability."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from shared.order_book import parse_book_history
from shared.validation import database_rows, string
from snapshot_tunnel.options_csv import snapshots_csv as snapshots_csv
from snapshot_tunnel.options_depth import depth_csv
from snapshot_tunnel.options_model import Snapshot, parse_snapshots

DEFAULT_OPTIONS_DB = (
    Path(__file__).resolve().parents[1] / "options_history.sqlite"
)


def _snapshot_depth_content(snapshot: Snapshot) -> str | None:
    """Validate attached depth and its availability at the options snapshot.

    Returns:
        Full validated depth CSV, or none for an older snapshot without depth.

    Raises:
        ValueError: If the depth is stale or received after the snapshot.

    """
    book_content = None
    if snapshot.order_book is not None:
        book_content = depth_csv(snapshot.order_book)
        book = parse_book_history(
            book_content, maximum_age=timedelta(seconds=10)
        ).snapshots[0]
        if book.available > snapshot.timestamp or not book.fresh(
            timedelta(seconds=10)
        ):
            msg = (
                "Snapshot depth must be fresh and received by snapshot"
                " availability."
            )
            raise ValueError(msg)
    return book_content


def store_snapshot(
    snapshot: Snapshot, *, observed_at: str, path: Path = DEFAULT_OPTIONS_DB
) -> None:
    """Atomically store a complete chain, depth and source observation time."""
    content = snapshots_csv((snapshot,))
    _ = parse_snapshots(content)
    book_content = _snapshot_depth_content(snapshot)
    with closing(sqlite3.connect(path)) as db, db:
        _ = db.execute(
            "CREATE TABLE IF NOT EXISTS options_snapshots ("
            "available_at TEXT NOT NULL, asset TEXT NOT NULL, "
            "observed_at TEXT NOT NULL, source TEXT NOT NULL, "
            "content TEXT NOT NULL, PRIMARY KEY (available_at, asset))"
        )
        columns = database_rows(
            db.execute("PRAGMA table_info(options_snapshots)").fetchall()
        )
        if not any(string(column[1]) == "depth_content" for column in columns):
            _ = db.execute(
                "ALTER TABLE options_snapshots ADD COLUMN depth_content TEXT"
            )
        _ = db.execute(
            "INSERT INTO options_snapshots (available_at, asset, observed_at,"
            " source, content, depth_content) VALUES (?, ?, ?, ?, ?, ?)",
            (
                snapshot.timestamp.isoformat(),
                snapshot.asset,
                observed_at,
                (
                    "DERIBIT: OI normalized from underlying units; fixed-IV USD"
                    " model"
                ),
                content,
                book_content,
            ),
        )


def load_snapshots(path: Path = DEFAULT_OPTIONS_DB) -> tuple[Snapshot, ...]:
    """Read validated history; an absent database is an empty history.

    Returns:
        Observations ordered by availability time.

    """
    if not path.exists():
        return ()
    with closing(sqlite3.connect(path)) as db, db:
        columns = database_rows(
            db.execute("PRAGMA table_info(options_snapshots)").fetchall()
        )
        query = (
            "SELECT content, depth_content FROM options_snapshots ORDER BY"
            " available_at, asset"
            if any(string(column[1]) == "depth_content" for column in columns)
            else (
                "SELECT content, NULL FROM options_snapshots ORDER BY"
                " available_at, asset"
            )
        )
        rows = database_rows(db.execute(query).fetchall())
    snapshots = tuple(_restore_snapshot(row) for row in rows)
    return tuple(
        sorted(snapshots, key=lambda item: (item.timestamp, item.asset))
    )


def _restore_snapshot(row: tuple[object, ...]) -> Snapshot:
    """Restore and validate the saved options/depth association.

    Returns:
        The original timestamped snapshot and any attached depth.

    """
    snapshot = replace(
        parse_snapshots(string(row[0]))[0],
        order_book=(
            parse_book_history(
                string(row[1]), maximum_age=timedelta(seconds=10)
            ).snapshots[0]
            if row[1] is not None
            else None
        ),
    )
    _ = _snapshot_depth_content(snapshot)
    return snapshot
