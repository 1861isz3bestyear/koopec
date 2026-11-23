# Copyright 2026 avwap-workspace-tests contributors
"""Merge checked overlapping archives without erasing history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import koopec_calculus
from market_storage.backup import validate
from market_storage.models import Observation, Source, asset_value, aware

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@dataclass(frozen=True, kw_only=True)
class Timeline:
    """Successful source coverage within an observed asset time range."""

    asset: str
    source: Source
    first_requested_at: str
    last_requested_at: str
    successful_buckets: int
    missing_buckets: int


@dataclass(frozen=True, kw_only=True)
class MergeReport:
    """Counts and explicit gaps; a gap is never a fabricated observation."""

    observations: int
    duplicates: int
    timelines: tuple[Timeline, ...]


def _text(value: object) -> str:
    if not isinstance(value, str):
        msg = "Archive metadata must contain text."
        raise TypeError(msg)
    return value


def _time(value: object) -> datetime:
    stamp = datetime.fromisoformat(_text(value))
    aware(stamp)
    return stamp.astimezone(UTC)


def _payload(row: tuple[object, ...], *, compact: bool) -> str:
    if not compact:
        return _text(row[4])
    body = row[4]
    if not isinstance(body, bytes) or row[9] != "zlib":
        msg = "Invalid compressed payload or codec."
        raise ValueError(msg)
    try:
        decoded = zlib.decompress(body)
        result = decoded.decode("utf-8")
    except (zlib.error, UnicodeError) as exc:
        msg = "Corrupt compressed archive payload."
        raise ValueError(msg) from exc
    if hashlib.sha256(decoded).hexdigest() != row[8]:
        msg = "Archive payload digest mismatch."
        raise ValueError(msg)
    return result


def decode_record(row: tuple[object, ...], *, compact: bool) -> Observation:
    """Validate a database row before using it as a domain observation.

    Returns:
        A causal observation with verified payload content.

    """
    payload = _payload(row, compact=compact)
    if not _text(row[5]):
        json.loads(payload)
    return Observation(
        asset=asset_value(_text(row[0])),
        source=Source(_text(row[1])),
        requested=_time(row[2]),
        available=_time(row[3]),
        payload=payload,
        error=_text(row[5]),
        collection=_text(row[6]),
    )


def records(path: Path) -> Iterator[tuple[Observation, datetime]]:
    """Stream checked metadata and decoded payloads from both storage modes.

    Yields:
        Validated observations with their original collection minute.

    """
    validate(path)
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        tables: list[tuple[str]] = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {row[0] for row in tables}
        for table in ("tunnel_inputs", "tunnel_observations"):
            if table not in names:
                continue
            compact = table == "tunnel_observations"
            query = (
                "SELECT"
                " o.asset,o.source,o.requested_at,o.available_at,p.payload,"
                "o.error,o.collection_id,o.minute_at,p.digest,p.codec"
                " FROM tunnel_observations o LEFT JOIN tunnel_payloads p ON"
                " p.digest=o.digest"
                if compact
                else (
                    "SELECT"
                    " asset,source,requested_at,available_at,payload,error,"
                    "collection_id,minute_at"
                    " FROM tunnel_inputs"
                )
            )
            cursor = db.execute(query)
            for row in _rows(cursor):
                record = decode_record(row, compact=compact)
                yield record, _collection_minute(row[7], record)


def _report(
    result: tuple[int, int, list[tuple[str, str, str, str, int, int]]],
) -> MergeReport:
    """Adapt the native archive report to the CLI model.

    Returns:
        Totals and per-source coverage for the validated union.

    """
    observations, duplicates, timelines = result
    return MergeReport(
        observations=observations,
        duplicates=duplicates,
        timelines=tuple(
            Timeline(
                asset=asset,
                source=Source(source),
                first_requested_at=first,
                last_requested_at=last,
                successful_buckets=successful,
                missing_buckets=missing,
            )
            for asset, source, first, last, successful, missing in timelines
        ),
    )


def merge(source: Path, destination: Path) -> MergeReport:
    """Publish a checked union under a writer lock.

    Returns:
        Unique observation count, duplicates and per-source gaps.

    """
    return _report(koopec_calculus.merge_archive(source, destination))


def format_report(report: MergeReport) -> str:
    """Render machine-readable counts and per-source missing UTC buckets.

    Returns:
        One JSON report without fabricated data or inferred outside bounds.

    """
    return json.dumps({
        "observations": report.observations,
        "duplicates": report.duplicates,
        "timelines": [
            {
                "asset": item.asset,
                "source": item.source.value,
                "first_requested_at": item.first_requested_at,
                "last_requested_at": item.last_requested_at,
                "successful_buckets": item.successful_buckets,
                "missing_buckets": item.missing_buckets,
            }
            for item in report.timelines
        ],
    })


def _rows(cursor: sqlite3.Cursor) -> Iterator[tuple[object, ...]]:
    while True:
        batch: list[tuple[object, ...]] = cursor.fetchmany(256)
        if not batch:
            return
        yield from batch


def check(path: Path) -> MergeReport:
    """Audit an archive without mutating it, including conflicts and gaps.

    Returns:
        The same validation report used before cumulative publication.

    """
    return _report(koopec_calculus.merge_archive(path))


def _collection_minute(value: object, record: Observation) -> datetime:
    minute = _time(value)
    if minute > record.requested or minute.second or minute.microsecond:
        msg = "Invalid collection minute in archive."
        raise ValueError(msg)
    return minute
