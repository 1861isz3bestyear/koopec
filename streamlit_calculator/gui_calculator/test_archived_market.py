# Copyright 2026 anchored-vwam-backtest contributors
"""Verify archive-first calculations and causal five-minute OI consumption."""

import asyncio
import json
import math
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from market_storage.archive import Archive
from market_storage.models import Observation, Source, Window
from market_storage.transfer import Remote, pull
from snapshot_tunnel.archived_market import calculate_archive
from snapshot_tunnel.oi_divergence import (
    DivergenceSettings,
    InterestSample,
    MarketSample,
)

STAMP = datetime(2026, 11, 9, 12, tzinfo=UTC)


def record(source: Source, payload: object, *, index: int = 0) -> Observation:
    """Serialize external fixture data with separate source and receipt times.

    Returns:
        A deterministic archived input.

    """
    observed = STAMP + timedelta(minutes=5 * index)
    return Observation(
        asset="BTC",
        source=source,
        requested=observed,
        available=observed + timedelta(seconds=2),
        payload=json.dumps(payload),
        collection=f"poll-{index}",
    )


@pytest.fixture
def archive(tmp_path: Path) -> Archive:
    """Create one complete persisted GEX chain without a live data fallback.

    Returns:
        Archive containing validated-compatible Deribit input envelopes.

    """
    archive = Archive(path=tmp_path / "archive.sqlite")
    archive.store(
        record(
            Source.INSTRUMENTS,
            {
                "result": [{
                    "instrument_name": "BTC-C",
                    "kind": "option",
                    "is_active": True,
                    "base_currency": "BTC",
                    "option_type": "call",
                    "contract_size": 1,
                    "expiration_timestamp": int(
                        (STAMP + timedelta(days=10)).timestamp() * 1000
                    ),
                    "strike": 100000,
                }]
            },
        )
    )
    archive.store(
        record(
            Source.OPTIONS,
            {
                "result": [{
                    "instrument_name": "BTC-C",
                    "open_interest": 20,
                    "mark_iv": 50,
                }]
            },
        )
    )
    archive.store(record(Source.SPOT, {"result": {"index_price": 100000}}))
    return archive


def test_calculations_use_persisted_data_and_receipt_cutoffs(
    archive: Archive,
) -> None:
    """Compute actual GEX from durable evidence and never look past a cutoff."""
    window = Window(asset="BTC", start=STAMP, end=STAMP + timedelta(seconds=2))
    results = calculate_archive(archive.path, window)
    assert len(results.gex) == 1
    assert results.gex[0].snapshot.options[0].iv == pytest.approx(0.5)
    assert results.gex[0].exposures[0].call > 0
    assert calculate_archive(archive.path, replace(window, end=STAMP)).gex == ()
    assert results.oi.points == ()
    assert results.margin == results.order_book == ()


def test_five_minute_oi_uses_saved_tickers_and_preserves_twelve_hour_lookback(
    archive: Archive,
) -> None:
    """Warm up from real five-minute OI and ticker pairs."""
    observations = 150
    for index in range(observations):
        stamp = STAMP + timedelta(minutes=5 * index)
        archive.store(
            record(
                Source.OI,
                {
                    "result": {
                        "symbol": "BTCUSDT",
                        "list": [{
                            "timestamp": str(int(stamp.timestamp() * 1000)),
                            "openInterest": str(1000 + index),
                        }],
                    }
                },
                index=index,
            )
        )
        archive.store(
            record(
                Source.TICKER,
                {
                    "result": {
                        "list": [{
                            "symbol": "BTCUSDT",
                            "lastPrice": str(100000 + index),
                        }]
                    }
                },
                index=index,
            )
        )
    result = calculate_archive(
        archive.path,
        Window(asset="BTC", start=STAMP, end=STAMP + timedelta(days=1)),
    )
    assert len(result.oi.points) == observations
    assert result.oi.points[0].rate is None
    assert result.oi.points[-1].rate is not None
    assert math.isfinite(result.oi.points[-1].rate)
    received = result.oi.points[-1].sample.received
    assert received is not None
    assert result.oi.points[-1].available >= received


def test_order_book_and_margin_calculations_use_archived_responses(
    archive: Archive,
) -> None:
    """Compute book notional and loan-growth momentum after loading SQLite."""
    archive.store(
        record(
            Source.DEPTH,
            {
                "retCode": 0,
                "result": {
                    "s": "BTCUSDT",
                    "ts": int(STAMP.timestamp() * 1000),
                    "b": [["99999", "2"]],
                    "a": [["100001", "1"]],
                },
            },
        )
    )
    archive.store(
        record(
            Source.GROWTH_HOURLY,
            {
                "code": "00000",
                "data": [
                    {
                        "ts": str(
                            int(
                                (
                                    STAMP - timedelta(hours=14 - index)
                                ).timestamp()
                                * 1000
                            )
                        ),
                        "growthRate": "0.2",
                    }
                    for index in range(15)
                ],
            },
        )
    )
    result = calculate_archive(
        archive.path,
        Window(asset="BTC", start=STAMP, end=STAMP + timedelta(minutes=1)),
    )
    assert result.order_book[0].value == pytest.approx(100 * 199998 / 299999)
    assert result.margin[0].value is None
    assert result.margin[-1].value == pytest.approx(100)
    assert result.margin[0].available == STAMP + timedelta(seconds=2)


@pytest.mark.parametrize(
    "payload",
    [
        {"result": {"symbol": "ETHUSDT", "list": []}},
        {
            "result": {
                "symbol": "BTCUSDT",
                "list": [{"timestamp": "1", "openInterest": "1"}],
            }
        },
        {
            "result": {
                "symbol": "BTCUSDT",
                "list": [{
                    "timestamp": str(
                        int((STAMP + timedelta(minutes=5)).timestamp() * 1000)
                    ),
                    "openInterest": "1",
                }],
            }
        },
    ],
)
def test_archived_interest_rejects_invalid_external_data(
    archive: Archive, payload: object
) -> None:
    """A stored JSON response still requires field-level runtime validation."""
    archive.store(record(Source.OI, payload))
    with pytest.raises(ValueError, match=r"symbol|boundaries|receipt"):
        _ = calculate_archive(
            archive.path,
            Window(asset="BTC", start=STAMP, end=STAMP + timedelta(minutes=1)),
        )


def test_oi_interval_and_receipt_validation() -> None:
    """Reject unsupported cadence and noncausal receipt times."""
    with pytest.raises(ValueError, match="interval"):
        _ = DivergenceSettings(interval=timedelta(minutes=1))
    interest = InterestSample(timestamp=STAMP, value=1)
    with pytest.raises(ValueError, match="receipt"):
        _ = MarketSample(
            interest=interest, price=1, received=STAMP - timedelta(seconds=1)
        )


@pytest.mark.e2e
def test_downloaded_vps_snapshot_drives_real_gex_calculation(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute remote backup and local transfer before calculating saved GEX."""
    root = archive.path.parent
    storage = Path(__file__).resolve().parents[3] / "paper/server_bot/storage"
    (root / "storage").symlink_to(storage, target_is_directory=True)
    ssh = root / "ssh"
    _ = ssh.write_text(
        f"#!{sys.executable}\nimport os, sys\n"
        "os.execv('/bin/sh', ['sh', '-c', sys.argv[-1]])\n"
    )
    ssh.chmod(0o700)
    monkeypatch.setenv("PATH", str(root) + os.pathsep + os.environ["PATH"])
    local = root / "downloaded.sqlite"
    remote = Remote(
        host="fixture-vps", root=str(root), database=archive.path.name
    )
    report = asyncio.run(pull(remote, local))
    assert report.observations > 0
    result = calculate_archive(
        local,
        Window(asset="BTC", start=STAMP, end=STAMP + timedelta(minutes=1)),
    )
    assert result.gex[0].exposures[0].call > 0


@pytest.mark.parametrize("overlap", [False, True])
def test_overlapping_oi_recovers_gap_only_after_receipt(
    archive: Archive, *, overlap: bool
) -> None:
    """Recover a skipped bucket only after its overlapping response arrives."""
    missing_index = 147
    recovery_index = missing_index + 1
    for index in range(150):
        archive.store(
            record(
                Source.TICKER,
                {
                    "result": {
                        "list": [{
                            "symbol": "BTCUSDT",
                            "lastPrice": str(100000 + index),
                        }]
                    }
                },
                index=index,
            )
        )
        if index == missing_index:
            continue
        indices = range(max(0, index - 2), index + 1) if overlap else [index]
        archive.store(
            record(
                Source.OI,
                {
                    "result": {
                        "symbol": "BTCUSDT",
                        "list": [
                            {
                                "timestamp": str(
                                    int(
                                        (
                                            STAMP + timedelta(minutes=5 * item)
                                        ).timestamp()
                                        * 1000
                                    )
                                ),
                                "openInterest": str(1000 + item),
                            }
                            for item in indices
                        ],
                    }
                },
                index=index,
            )
        )
    cutoff = STAMP + timedelta(minutes=5 * recovery_index, seconds=2)
    before = calculate_archive(
        archive.path,
        Window(asset="BTC", start=STAMP, end=cutoff - timedelta(seconds=1)),
    ).oi.points
    assert len(before) == missing_index
    assert before[-1].rate is not None
    after = calculate_archive(
        archive.path, Window(asset="BTC", start=STAMP, end=cutoff)
    ).oi.points
    assert after[missing_index - 1].available == before[-1].available
    assert (after[-1].rate is not None) is overlap
    if overlap:
        assert len(after) == recovery_index + 1
        assert after[missing_index].available == cutoff
        assert after[recovery_index].available == cutoff
    else:
        assert len(after) == recovery_index
