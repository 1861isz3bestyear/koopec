# Copyright 2026 anchored-vwam-backtest contributors
"""Write realistic exchange envelopes into isolated market-storage archives."""

import json
from datetime import timedelta
from typing import TYPE_CHECKING

from market_storage.archive import Archive
from market_storage.models import Observation, Source

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from snapshot_tunnel.options_model import Snapshot


def store_response(
    archive: Archive, source: Source, payload: object, *, stamp: datetime
) -> None:
    """Persist a response with a distinct causal receipt time."""
    archive.store(
        Observation(
            asset="BTC",
            source=source,
            requested=stamp,
            available=stamp + timedelta(seconds=2),
            collection=stamp.isoformat(),
            payload=json.dumps(payload),
        )
    )


def store_chain(
    archive: Archive, snapshot: Snapshot, *, stamp: datetime
) -> None:
    """Persist complete Deribit definitions, summaries and spot responses."""
    definitions = [
        {
            "instrument_name": f"BTC-{index}",
            "kind": "option",
            "is_active": True,
            "base_currency": "BTC",
            "option_type": option.side,
            "contract_size": option.multiplier,
            "expiration_timestamp": int(option.expiry.timestamp() * 1000),
            "strike": option.strike,
        }
        for index, option in enumerate(snapshot.options)
    ]
    quotes = [
        {
            "instrument_name": f"BTC-{index}",
            "open_interest": option.open_interest * option.multiplier,
            "mark_iv": option.iv * 100,
        }
        for index, option in enumerate(snapshot.options)
    ]
    for source, payload in (
        (Source.INSTRUMENTS, {"result": definitions}),
        (Source.OPTIONS, {"result": quotes}),
        (Source.SPOT, {"result": {"index_price": snapshot.spot}}),
    ):
        store_response(archive, source, payload, stamp=stamp)


def store_flow(archive: Archive, stamp: datetime) -> None:
    """Persist a complete independent book and matched five-minute OI ticker."""
    timestamp = int(stamp.timestamp() * 1000)
    for source, payload in (
        (
            Source.DEPTH,
            {
                "retCode": 0,
                "result": {
                    "s": "BTCUSDT",
                    "ts": timestamp,
                    "b": [["79999", "3"]],
                    "a": [["80001", "1"]],
                },
            },
        ),
        (
            Source.OI,
            {
                "result": {
                    "symbol": "BTCUSDT",
                    "list": [{
                        "timestamp": str(timestamp),
                        "openInterest": str(timestamp / 100000000),
                    }],
                }
            },
        ),
        (
            Source.TICKER,
            {
                "result": {
                    "list": [{
                        "symbol": "BTCUSDT",
                        "lastPrice": "80000",
                    }]
                }
            },
        ),
    ):
        store_response(archive, source, payload, stamp=stamp)


def write_archive(path: Path, snapshot: Snapshot) -> None:
    """Build GEX plans with independent book, margin and OI feeds."""
    archive = Archive(path=path)
    start = snapshot.timestamp - timedelta(days=1)
    store_chain(archive, snapshot, stamp=start)
    for offset in (5, 10, 15):
        store_chain(archive, snapshot, stamp=start + timedelta(minutes=offset))
    store_chain(archive, snapshot, stamp=snapshot.timestamp)
    stamp = start
    while stamp <= snapshot.timestamp:
        store_flow(archive, stamp)
        stamp += timedelta(minutes=5)
    store_response(
        archive,
        Source.GROWTH_HOURLY,
        {
            "code": "00000",
            "data": [
                {
                    "ts": str(
                        int(
                            (start - timedelta(hours=13 - index)).timestamp()
                            * 1000
                        )
                    ),
                    "growthRate": "1",
                }
                for index in range(14)
            ],
        },
        stamp=start,
    )
