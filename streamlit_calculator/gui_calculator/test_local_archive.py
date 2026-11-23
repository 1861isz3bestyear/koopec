# Copyright 2026 anchored-vwam-backtest contributors
"""Exercise archive coverage, daily selection and independent receipts."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from market_storage.archive import Archive
from market_storage.models import Source, Window
from shared.tunnel import TunnelSettings
from snapshot_tunnel.local_archive import (
    archive_tunnel_flow,
    daily_collections,
    inspect_archive,
    load_archive_oscillators,
    load_archive_snapshots,
)
from snapshot_tunnel.options_model import parse_snapshots

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.test_archived_market import STAMP
from gui_calculator.test_archived_market import archive as archive
from tests.frontend.archive_fixture import write_archive

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_COLLECTIONS = 3
EARLIER_MINUTE = 10
STREAM_POSITION = 3
FULL_CONFIRMATION = 100


def test_local_archive_daily_selection(archive: Archive) -> None:
    """Choose earlier tied 08:15-nearest receipts using only cheap metadata."""
    original = archive.load(
        Window(asset="BTC", start=STAMP, end=STAMP + timedelta(minutes=1))
    )
    for minutes in (10, 20):
        for observation in original:
            archive.store(
                replace(
                    observation,
                    collection=f"next-{minutes}",
                    requested=observation.requested
                    + timedelta(hours=20, minutes=minutes),
                    available=observation.available
                    + timedelta(hours=20, minutes=minutes),
                )
            )
    source = inspect_archive(archive.path)
    assert len(source.collections) == EXPECTED_COLLECTIONS
    selected = daily_collections(source)
    assert selected[1].window.end.hour == STAMP.hour - 4
    assert selected[1].window.end.minute == EARLIER_MINUTE
    snapshots = load_archive_snapshots(source)
    assert len(snapshots) == len(selected)
    assert snapshots[-1].timestamp == selected[-1].window.end


def test_independent_book_receipts(archive: Archive) -> None:
    """Use independent book receipts between daily chains."""
    original = archive.load(
        Window(asset="BTC", start=STAMP, end=STAMP + timedelta(minutes=1))
    )
    for observation in original:
        archive.store(
            replace(
                observation,
                collection="later",
                requested=observation.requested + timedelta(minutes=5),
                available=observation.available + timedelta(minutes=5),
            )
        )
    receipt = STAMP + timedelta(minutes=1)
    archive.store(
        replace(
            original[0],
            source=Source.DEPTH,
            requested=receipt,
            available=receipt,
            collection="independent-depth",
            payload=json.dumps({
                "retCode": 0,
                "result": {
                    "s": "BTCUSDT",
                    "ts": int(receipt.timestamp() * 1000),
                    "b": [["100", "3"]],
                    "a": [["200", "0.5"]],
                },
            }),
        )
    )
    streams = load_archive_oscillators(inspect_archive(archive.path))
    settings = TunnelSettings()
    flow = archive_tunnel_flow(streams, settings)
    assert len(flow.book) == 1
    assert flow.book[0].available == receipt
    assert flow.count(1, receipt - timedelta(seconds=1), settings=settings) == 0
    assert flow.count(1, receipt, settings=settings) == 1
    assert (
        flow.count(1, receipt + timedelta(minutes=11), settings=settings) == 0
    )
    assert not flow.margin
    assert not flow.oi


def test_missing_chains_rejected(archive: Archive) -> None:
    """Missing archive files fail without creating an empty database."""
    with pytest.raises(FileNotFoundError):
        _ = inspect_archive(archive.path.with_name("missing.sqlite"))


def test_complete_archive_streams(tmp_path: Path) -> None:
    """Load GEX, independent book, margin warmup and five-minute OI together."""
    path = tmp_path / "tunnel_inputs.sqlite"
    snapshot = parse_snapshots(EXAMPLE)[0]
    write_archive(path, snapshot)
    source = inspect_archive(path)
    snapshots = load_archive_snapshots(source)
    assert len(snapshots) == len(daily_collections(source))
    streams = load_archive_oscillators(source)
    assert streams.margin[-1].value == FULL_CONFIRMATION
    assert streams.oi.points[0].rate is None
    assert streams.oi.points[-1].rate is not None
    assert streams.oi.points[-1].available <= source.end
    flow = archive_tunnel_flow(streams, TunnelSettings())
    assert len(flow.oi) == len(streams.oi.points)
    assert flow.margin[-1].direction == 1
    assert len(flow.book) == len(streams.order_book)


def test_empty_options_coverage(archive: Archive, tmp_path: Path) -> None:
    """Independent evidence cannot imply complete options-chain coverage."""
    row = archive.load(
        Window(asset="BTC", start=STAMP, end=STAMP + timedelta(minutes=1))
    )[0]
    empty = Archive(path=tmp_path / "only-depth.sqlite")
    empty.store(replace(row, source=Source.DEPTH, collection="only-depth"))
    with pytest.raises(ValueError, match="no complete"):
        _ = inspect_archive(empty.path)


def test_replaced_archive_requires_new_coverage(archive: Archive) -> None:
    """Refuse mixing an old cached window with a replacement download."""
    source = inspect_archive(archive.path)
    with archive.path.open("ab") as stream:
        _ = stream.write(b"\x00")
    with pytest.raises(ValueError, match="archive changed"):
        _ = load_archive_snapshots(source)
    with pytest.raises(ValueError, match="archive changed"):
        _ = load_archive_oscillators(source)
