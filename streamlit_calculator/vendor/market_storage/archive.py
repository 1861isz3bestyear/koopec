# Copyright 2026 avwap-workspace-tests contributors
"""Commit exact inputs before exposing them to calculation consumers."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import koopec_calculus
from market_storage.models import Observation, Source, Window, aware
from market_storage.receipts import cleanup
from market_storage.schema import prepare

DUE_QUERIES = {
    "tunnel_inputs": (
        "SELECT 1 FROM tunnel_inputs WHERE asset=? AND source=? "
        "AND error='' AND requested_at>=? AND available_at<=? LIMIT 1"
    ),
    "tunnel_observations": (
        "SELECT 1 FROM tunnel_observations WHERE asset=? AND source=? "
        "AND error='' AND requested_at>=? AND available_at<=? LIMIT 1"
    ),
}
DELETE_QUERIES = {
    "tunnel_inputs": "DELETE FROM tunnel_inputs WHERE available_at<?",
    "tunnel_observations": (
        "DELETE FROM tunnel_observations WHERE available_at<?"
    ),
}

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, kw_only=True)
class Archive:
    """Own the SQLite boundary and compressed content-addressed payloads."""

    path: Path
    mode: Literal["raw", "compact"] = "compact"

    def store(
        self,
        observation: Observation,
        *,
        collection_started: datetime | None = None,
    ) -> None:
        """Durably commit one response before a consumer can load it."""
        if collection_started is not None:
            aware(collection_started)
        koopec_calculus.save_market(
            self.path,
            (
                observation.asset,
                observation.source.value,
                observation.requested.isoformat(),
                observation.available.isoformat(),
                observation.payload,
                observation.collection,
                observation.error,
            ),
            collection_started.isoformat() if collection_started else None,
            self.mode == "compact",
        )

    def load(
        self, window: Window, *, sources: frozenset[Source] | None = None
    ) -> tuple[Observation, ...]:
        """Read only successful observations received by the cutoff.

        Returns:
            Validated chronological observations, including revised responses.

        """
        rows = koopec_calculus.load_market(
            self.path,
            (window.asset, window.start.isoformat(), window.end.isoformat()),
            [
                source.value
                for source in (Source if sources is None else sources)
            ],
        )
        return tuple(
            Observation(
                asset=window.asset,
                source=Source(source),
                requested=datetime.fromisoformat(requested),
                available=datetime.fromisoformat(available),
                payload=payload,
                collection=collection,
            )
            for source, requested, available, payload, collection in rows
        )

    def due(self, asset: str, source: Source, *, now: datetime) -> bool:
        """Persist cadence across restarts and retry failures within a bucket.

        Returns:
            Whether no successful request exists in the current UTC bucket.

        """
        aware(now)
        if not self.path.exists():
            return True
        bucket = int(now.timestamp()) // source.interval * source.interval
        start = datetime.fromtimestamp(bucket, UTC).isoformat()
        with closing(_read_connection(self.path)) as db:
            for table in _tables(db):
                result: list[tuple[object, ...]] = db.execute(
                    DUE_QUERIES[table],
                    (
                        asset,
                        source.value,
                        start,
                        now.astimezone(UTC).isoformat(),
                    ),
                ).fetchall()
                if result:
                    return False
        return True

    def prune(self, *, now: datetime, retention: timedelta) -> None:
        """Remove expired observations and unreferenced compressed payloads.

        Raises:
            ValueError: If retention is not positive.

        """
        aware(now)
        if retention <= timedelta(0):
            msg = "Retention must be positive."
            raise ValueError(msg)
        if not self.path.exists():
            return
        with closing(_read_connection(self.path)) as reader:
            managed = (
                reader.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='copy_receipts'"
                ).fetchone()
                is not None
            )
        if managed:
            _ = cleanup(self.path, now=now)
            return
        cutoff = (now - retention).astimezone(UTC).isoformat()
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            prepare(db)
            with db:
                for table in _tables(db):
                    _ = db.execute(
                        DELETE_QUERIES[table],
                        (cutoff,),
                    )
                _ = db.execute(
                    "DELETE FROM tunnel_payloads WHERE digest NOT IN "
                    "(SELECT digest FROM tunnel_observations)"
                )


def _read_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _tables(db: sqlite3.Connection) -> tuple[str, ...]:
    rows: list[tuple[str]] = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('tunnel_inputs','tunnel_observations')"
    ).fetchall()
    return tuple(row[0] for row in rows)
