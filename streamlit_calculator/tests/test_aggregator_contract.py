# Copyright 2026 anchored-vwam-backtest contributors
"""Validate the real sibling producer at the calculator's CSV boundary."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest
from snapshot_tunnel.options_model import net_exposure, parse_snapshots

from gui_calculator.data_sources import parse_uploaded_csv

MINUTES_PER_DAY = 1440
pytestmark = pytest.mark.contract
AGGREGATOR = os.environ.get("KOOPEC_AGGREGATOR_ROOT")
RAW = (
    "date,currency,instrument,expiry,strike,type,open_interest,mark_iv,"
    "underlying_usd\n"
    "2026-08-06,BTC,BTC-6AUG26-70000-C,6AUG26,70000,call,2,50,60000\n"
    "2026-08-06,BTC,BTC-28AUG26-70000-P,28AUG26,70000,put,3,60,80000\n"
)


def _write_archive(root: Path) -> None:
    """Build a deterministic source archive without network or user data."""
    source = root / "external" / "bykaranteli_options_history"
    source.mkdir(parents=True)
    _ = (source / "day.csv").write_text(RAW)
    _ = (source / "manifest.json").write_text(
        json.dumps({
            "snapshots": [{
                "file": "day.csv",
                "sha256": hashlib.sha256(RAW.encode()).hexdigest(),
            }],
        })
    )
    candles = root / "candles"
    candles.mkdir()
    start = datetime(2026, 8, 7, tzinfo=UTC)
    with (candles / "2026-08-07.csv").open("w") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "open", "high", "low", "close", "volume"])
        for minute in range(1440):
            writer.writerow([
                (start + timedelta(minutes=minute)).isoformat(),
                70000,
                70001,
                69999,
                70000,
                1,
            ])


async def _prepare(root: Path, aggregator: Path) -> None:
    """Execute the producer CLI in its own Python environment."""
    interpreter = aggregator / ".venv" / "bin" / "python"
    assert interpreter.exists(), "Run uv sync --locked in options_aggregator"
    process = await asyncio.create_subprocess_exec(
        str(interpreter),
        "-c",
        "from options_aggregator.cli import main; raise SystemExit(main())",
        "--data-dir",
        str(root),
        "prepare-bykaranteli",
        "--accept-research-assumptions",
        cwd=aggregator,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == 0, stdout.decode() + stderr.decode()


@pytest.fixture
def exported(tmp_path: Path) -> Path:
    """Generate calculator inputs using the installed sibling CLI.

    Returns:
        The generated bundle directory.

    """
    if AGGREGATOR is None:
        pytest.skip("Set KOOPEC_AGGREGATOR_ROOT for aggregator contract tests")
    _write_archive(tmp_path)
    asyncio.run(_prepare(tmp_path, Path(AGGREGATOR)))
    return tmp_path / "gui" / "bykaranteli_research"


def test_actual_aggregator_options_preserve_units(exported: Path) -> None:
    """Verify timestamps, IV, OI and research provenance survive parsing."""
    snapshots = parse_snapshots((exported / "options_research.csv").read_text())
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.timestamp == datetime(2026, 8, 7, tzinfo=UTC)
    assert snapshot.asset == "BTC"
    assert snapshot.spot == pytest.approx(70000)
    assert len(snapshot.options) == 1
    option = snapshot.options[0]
    assert option.exchange == "DERIBIT_RESEARCH_APPROXIMATE"
    assert option.side == "put"
    assert option.strike == pytest.approx(70000)
    assert option.open_interest == pytest.approx(3)
    assert option.multiplier == 1
    assert option.iv == pytest.approx(0.6)
    assert option.expiry == datetime(2026, 8, 28, 8, tzinfo=UTC)
    assert net_exposure(snapshot, snapshot.spot) < 0


def test_actual_aggregator_candles_preserve_open_times(exported: Path) -> None:
    """Accept OHLCV without shifting opening timestamps to closing times."""
    candles = parse_uploaded_csv(str(exported / "candles.csv"))
    assert len(candles) == MINUTES_PER_DAY
    pd.testing.assert_series_equal(
        candles["time"],
        pd.Series(
            pd.date_range(
                "2026-08-07", periods=MINUTES_PER_DAY, freq="min", tz="UTC"
            ),
            name="time",
        ),
    )
    assert list(candles["close"]) == [70000] * 1440
    assert list(candles["volume"]) == [1] * 1440


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("+00:00", "", "timezone"),
        (",0.6", ",nan", "finite"),
        ("2026-08-28T08:00:00", "2026-08-06T08:00:00", "expire"),
        ("multiplier", "contract_size", "CSV columns"),
    ],
)
def test_incompatible_options_are_rejected(
    *, exported: Path, old: str, new: str, message: str
) -> None:
    """Refuse schema drift and invalid financial inputs at upload."""
    text = (exported / "options_research.csv").read_text().replace(old, new)
    with pytest.raises(ValueError, match=message):
        _ = parse_snapshots(text)


def test_options_csv_cannot_be_used_as_candles(exported: Path) -> None:
    """The two upload formats must not silently substitute for each other."""
    text = (exported / "options_research.csv").read_text()
    with pytest.raises(ValueError, match="CSV must include"):
        _ = parse_uploaded_csv(StringIO(text))
