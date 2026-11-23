# Copyright 2026 anchored-vwam-backtest contributors
"""Verify depth validation, atomic storage and causal oscillator history."""

from __future__ import annotations

import io
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import requests
from shared.order_book import parse_book_history
from snapshot_tunnel.options_depth import (
    MAXIMUM_CLOCK_LEAD,
    depth_csv,
    fetch_depth,
    parse_depth,
)
from snapshot_tunnel.options_model import parse_snapshots

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.options_store import (
    load_snapshots,
    snapshots_csv,
    store_snapshot,
)
from gui_calculator.snapshot_oscillator import (
    limit_order_oscillator_rate,
    saved_depth_history,
)

if TYPE_CHECKING:
    from pathlib import Path

STAMP = parse_snapshots(EXAMPLE)[0].timestamp + timedelta(minutes=1)


def payload() -> dict[str, object]:
    """Provide unequal bid/ask liquidity in a two-sided Bybit response.

    Returns:
        A complete top-of-book response with a known notional ratio.

    """
    return {
        "retCode": 0,
        "result": {
            "s": "BTCUSDT",
            "ts": int(STAMP.timestamp() * 1000),
            "b": [["100", "3"]],
            "a": [["200", "0.5"]],
        },
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"s": "ETHUSDT"},
        {"b": []},
        {"a": [["90", "1"]]},
        {"b": [["100", "0"]]},
        {"b": [["100", "nan"]]},
        {"b": [["100"]]},
        {"b": [["100", "1"]] * 51},
        {"ts": int((STAMP + timedelta(seconds=1)).timestamp() * 1000)},
        {"ts": int((STAMP - timedelta(seconds=11)).timestamp() * 1000)},
    ],
)
def test_invalid_depth_rejected(changes: dict[str, object]) -> None:
    """Reject wrong markets, bad levels, future timestamps and stale books."""
    content = payload()
    content["result"] = {
        "s": "BTCUSDT",
        "ts": int(STAMP.timestamp() * 1000),
        "b": [["100", "3"]],
        "a": [["200", "0.5"]],
        **changes,
    }
    with pytest.raises(ValueError, match=r".+"):
        _ = parse_depth(json.dumps(content), asset="BTC", received=STAMP)


def test_depth_round_trip_and_causal_history(tmp_path: Path) -> None:
    """Round-trip books and exclude future observations and other markets."""
    book = parse_depth(json.dumps(payload()), asset="BTC", received=STAMP)
    snapshot = replace(
        parse_snapshots(EXAMPLE)[0], timestamp=STAMP, order_book=book
    )
    path = tmp_path / "options.sqlite"
    store_snapshot(snapshot, observed_at=STAMP.isoformat(), path=path)
    assert load_snapshots(path) == (snapshot,)
    assert limit_order_oscillator_rate(book) == pytest.approx(75)
    assert parse_book_history(
        depth_csv(book), maximum_age=timedelta(seconds=10)
    ).snapshots == (book,)
    future = replace(
        snapshot,
        order_book=replace(book, available=STAMP + timedelta(seconds=1)),
    )
    foreign = replace(snapshot, asset="ETH")
    with patch(
        "gui_calculator.snapshot_oscillator.load_snapshots",
        return_value=(snapshot, future, foreign),
    ):
        assert saved_depth_history(snapshot, days=7) == (book,)
        assert not saved_depth_history(
            replace(
                snapshot,
                timestamp=STAMP - timedelta(seconds=1),
                order_book=None,
            ),
            days=7,
        )
    with pytest.raises(ValueError, match="availability"):
        store_snapshot(future, observed_at=STAMP.isoformat(), path=path)
    assert load_snapshots(path) == (snapshot,)


def test_legacy_database_migrates_without_rewriting_history(
    tmp_path: Path,
) -> None:
    """Old options-only archives load unchanged and accept new depth records."""
    original = parse_snapshots(EXAMPLE)[0]
    path = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        _ = db.execute(
            "CREATE TABLE options_snapshots (available_at TEXT, asset TEXT,"
            " observed_at TEXT, source TEXT, content TEXT, PRIMARY KEY"
            " (available_at, asset))"
        )
        _ = db.execute(
            "INSERT INTO options_snapshots VALUES (?, ?, ?, ?, ?)",
            (
                original.timestamp.isoformat(),
                original.asset,
                original.timestamp.isoformat(),
                "DERIBIT",
                snapshots_csv((original,)),
            ),
        )
    assert load_snapshots(path) == (original,)
    book = parse_depth(json.dumps(payload()), asset="BTC", received=STAMP)
    newer = replace(original, timestamp=STAMP, order_book=book)
    store_snapshot(newer, observed_at=STAMP.isoformat(), path=path)
    assert set(load_snapshots(path)) == {original, newer}


def test_exchange_depth_error() -> None:
    """Exchange rejection never becomes a snapshot observation."""
    content = payload()
    content["retCode"] = 10001
    with pytest.raises(ValueError, match="failed"):
        _ = parse_depth(json.dumps(content), asset="BTC", received=STAMP)


@pytest.mark.parametrize("lead_seconds", [0, 0.25, 6])
def test_download_waits_for_small_clock_lead(lead_seconds: float) -> None:
    """Wait for causal availability, rejecting clocks beyond the tolerance."""
    received = STAMP - timedelta(seconds=lead_seconds)
    response = requests.Response()
    response.status_code = 200
    response.raw = io.BytesIO(json.dumps(payload()).encode())
    with (
        requests.Session() as session,
        patch("snapshot_tunnel.options_depth.datetime") as clock,
        patch("snapshot_tunnel.options_depth.sleep") as sleep,
        patch.object(session, "get", return_value=response),
    ):
        clock.configure_mock(**{
            "now.side_effect": [received, STAMP],
            "fromtimestamp.return_value": STAMP,
        })
        if timedelta(seconds=lead_seconds) > MAXIMUM_CLOCK_LEAD:
            with pytest.raises(
                ValueError, match="Synchronize the system clock"
            ):
                _ = fetch_depth(session, asset="BTC")
            sleep.assert_not_called()
            return
        book = fetch_depth(session, asset="BTC")
        assert book.observed == STAMP
        assert book.available == STAMP
        if lead_seconds:
            sleep.assert_called_once_with(lead_seconds)
        else:
            sleep.assert_not_called()
