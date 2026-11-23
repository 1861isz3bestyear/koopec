# Copyright 2026 anchored-vwam-backtest contributors
"""Verify archive exports round trip through the production CSV parser."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from market_storage.archive import Archive
from market_storage.models import Source, Window
from snapshot_tunnel import archive_export
from snapshot_tunnel.archive_export import export_options
from snapshot_tunnel.options_model import parse_snapshots

from gui_calculator.test_archived_market import STAMP
from gui_calculator.test_archived_market import archive as archive

if TYPE_CHECKING:
    from pathlib import Path


EXPECTED_OI = 20


def test_export_round_trip(archive: Archive, tmp_path: Path) -> None:
    """Preserve receipt time and OI without overwriting existing exports."""
    output = tmp_path / "options.csv"
    assert export_options(archive.path, output) == 1
    snapshots = parse_snapshots(output.read_text(encoding="utf-8"))
    assert len(snapshots) == 1
    assert snapshots[0].options[0].open_interest == EXPECTED_OI
    assert snapshots[0].timestamp > STAMP
    original = output.read_bytes()
    with pytest.raises(ValueError, match="new file"):
        _ = export_options(archive.path, output)
    assert output.read_bytes() == original


@pytest.mark.parametrize("asset", ["ETH", "invalid"])
def test_unavailable_asset(
    archive: Archive, tmp_path: Path, asset: str
) -> None:
    """Reject missing and unsupported assets without publishing output."""
    output = tmp_path / "options.csv"
    with pytest.raises(ValueError, match=r"Asset must|No complete"):
        _ = export_options(archive.path, output, asset=asset)
    assert not output.exists()


def test_export_command(
    archive: Archive, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise command success and safe repeated-export failure."""
    output = tmp_path / "command.csv"
    monkeypatch.setattr(
        "sys.argv", ["export", str(archive.path), "--output", str(output)]
    )
    assert archive_export.main() == 0
    assert archive_export.main() == 1


@pytest.mark.parametrize("payload", ['{"result": {"index_price": -1}}', "{}"])
def test_invalid_complete_chain(
    archive: Archive, tmp_path: Path, payload: str
) -> None:
    """Malformed complete chains fail before publication."""
    bad = Archive(path=tmp_path / "bad.sqlite")
    window = Window(asset="BTC", start=STAMP, end=STAMP + timedelta(days=1))
    for observation in archive.load(window):
        bad.store(
            replace(observation, payload=payload)
            if observation.source == Source.SPOT
            else observation
        )
    output = tmp_path / "bad.csv"
    with pytest.raises((ValueError, KeyError)):
        _ = export_options(bad.path, output)
    assert not output.exists()


def test_expired_contracts(archive: Archive, tmp_path: Path) -> None:
    """Do not publish a snapshot whose only contract expired before receipt."""
    expired = Archive(path=tmp_path / "expired.sqlite")
    window = Window(asset="BTC", start=STAMP, end=STAMP + timedelta(days=1))
    payload = json.dumps({
        "result": [{
            "instrument_name": "BTC-C",
            "kind": "option",
            "is_active": True,
            "base_currency": "BTC",
            "option_type": "call",
            "contract_size": 1,
            "expiration_timestamp": int(STAMP.timestamp() * 1000),
            "strike": 100000,
        }]
    })
    for observation in archive.load(window):
        expired.store(
            replace(observation, payload=payload)
            if observation.source == Source.INSTRUMENTS
            else observation
        )
    output = tmp_path / "expired.csv"
    with pytest.raises(ValueError, match="unique receipt times"):
        _ = export_options(expired.path, output)
    assert not output.exists()
