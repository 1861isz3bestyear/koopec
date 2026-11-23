# Copyright 2026 avwap-workspace-tests contributors
"""Commit exact inputs before exposing them to calculation consumers."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

import koopec_calculus
from market_storage.models import Observation, Source, Window, aware
from market_storage.receipts import cleanup

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
        return koopec_calculus.market_due(
            self.path, (asset, source.value), now.isoformat(), source.interval
        )

    def prune(self, *, now: datetime, retention: timedelta) -> None:
        """Remove expired observations and unreferenced compressed payloads.

        Raises:
            ValueError: If retention is not positive.

        """
        aware(now)
        if retention <= timedelta(0):
            msg = "Retention must be positive."
            raise ValueError(msg)
        if koopec_calculus.prune_unmanaged_archive(
            self.path, (now - retention).isoformat()
        ):
            _ = cleanup(self.path, now=now)
