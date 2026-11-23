# Copyright 2026 anchored-vwam-backtest contributors
"""Exercise collection validation and atomic historical persistence."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, nullcontext
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import requests
from shared.validation import database_rows, string
from snapshot_tunnel.options_data import fetch_snapshot, normalize_chain

from gui_calculator.options_collector import collect_once, main
from gui_calculator.options_store import load_snapshots

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def instrument() -> dict[str, object]:
    """Provide an active coin-settled contract specification.

    Returns:
        A realistic specification with a non-unit contract multiplier.

    """
    return {
        "instrument_name": "BTC-TEST-80000-C",
        "base_currency": "BTC",
        "kind": "option",
        "option_type": "call",
        "is_active": True,
        "contract_size": 0.1,
        "strike": 80000,
        "expiration_timestamp": int(
            (datetime.now(UTC) + timedelta(days=7)).timestamp() * 1000
        ),
    }


@pytest.fixture
def quote() -> dict[str, object]:
    """Provide underlying-denominated OI and percentage IV.

    Returns:
        One quoted contract.

    """
    return {
        "instrument_name": "BTC-TEST-80000-C",
        "open_interest": 2,
        "mark_iv": 55,
    }


def response(result: object) -> requests.Response:
    """Build a real response object with a current server timestamp.

    Returns:
        An HTTP success containing JSON-RPC data.

    """
    item = requests.Response()
    item.status_code = 200
    item.raw = BytesIO(
        json.dumps({
            "result": result,
            "usOut": int(datetime.now(UTC).timestamp() * 1_000_000),
        }).encode()
    )
    return item


def depth_response() -> requests.Response:
    """Provide a fresh full Bybit book for successful combined collections.

    Returns:
        An exchange response with validated two-sided resting liquidity.

    """
    item = requests.Response()
    item.status_code = 200
    item.raw = BytesIO(
        json.dumps({
            "retCode": 0,
            "result": {
                "s": "BTCUSDT",
                "ts": int(datetime.now(UTC).timestamp() * 1000),
                "b": [["80000", "3"]],
                "a": [["80001", "1"]],
            },
        }).encode()
    )
    return item


def test_collect_normalizes_and_preserves_availability(
    tmp_path: Path, instrument: dict[str, object], quote: dict[str, object]
) -> None:
    """OI, IV and multiplier normalization survives a real SQLite round trip."""
    replies = [
        response([instrument]),
        response([quote]),
        response({"index_price": 81000}),
        depth_response(),
    ]
    path = tmp_path / "options.sqlite"
    assert load_snapshots(path) == ()
    before = datetime.now(UTC)
    with patch("requests.Session.get", side_effect=replies) as get:
        assert collect_once(asset="BTC", path=path) == 1
    snapshots = load_snapshots(path)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert before <= snapshot.timestamp <= datetime.now(UTC)
    assert snapshot.order_book is not None
    assert snapshot.order_book.available <= snapshot.timestamp
    assert snapshot.order_book.bids[0].quantity == pytest.approx(3)
    assert snapshot.spot == pytest.approx(81000)
    assert snapshot.options[0].open_interest == pytest.approx(20)
    assert snapshot.options[0].multiplier == pytest.approx(0.1)
    assert snapshot.options[0].iv == pytest.approx(0.55)
    assert get.call_count == len(replies)
    with closing(sqlite3.connect(path)) as db, db:
        saved = database_rows(
            db.execute("SELECT source FROM options_snapshots").fetchall()
        )
        assert string(saved[0][0]).startswith("DERIBIT")
    with (
        patch("requests.Session.get", side_effect=requests.Timeout),
        pytest.raises(requests.Timeout),
    ):
        _ = collect_once(asset="BTC", path=path)
    assert load_snapshots(path) == snapshots


@pytest.mark.parametrize("field", ["open_interest", "mark_iv"])
@pytest.mark.parametrize("value", [-1, float("nan"), "55", True])
def test_invalid_quote_rejected(
    instrument: dict[str, object],
    quote: dict[str, object],
    *,
    field: str,
    value: object,
) -> None:
    """Invalid exchange numbers never become typed observations."""
    quote[field] = value
    with pytest.raises((ValueError, TypeError)):
        _ = normalize_chain([instrument], [quote], asset="BTC")


def test_missing_duplicate_and_empty_chains(
    instrument: dict[str, object], quote: dict[str, object]
) -> None:
    """Reject incomplete or ambiguous chains."""
    for instruments, quotes in (
        ([instrument], []),
        ([instrument, instrument], [quote]),
        ([], []),
    ):
        with pytest.raises(ValueError, match=r"Incomplete|Duplicate|empty"):
            _ = normalize_chain(instruments, quotes, asset="BTC")
    instrument["is_active"] = False
    with pytest.raises(ValueError, match="empty"):
        _ = normalize_chain([instrument], [quote], asset="BTC")
    instrument["is_active"] = True
    with pytest.raises(ValueError, match="currency"):
        _ = normalize_chain([instrument], [quote], asset="ETH")
    instrument["option_type"] = "future"
    with pytest.raises(ValueError, match="Unsupported"):
        _ = normalize_chain([instrument], [quote], asset="BTC")


def test_fetch_rejects_exchange_errors() -> None:
    """HTTP and JSON-RPC failures must propagate without usable observations."""
    session = requests.Session()
    error = requests.Response()
    error.status_code = 200
    error.raw = BytesIO(b'{"error":{"code":10028}}')
    with (
        patch.object(session, "get", return_value=error),
        pytest.raises(ValueError, match="error"),
    ):
        _ = fetch_snapshot(session)
    error.status_code = 429
    with (
        patch.object(session, "get", return_value=error),
        pytest.raises(requests.HTTPError),
    ):
        _ = fetch_snapshot(session)
    session.close()


def test_fetch_rejects_old_server_time_and_expired_chain(
    instrument: dict[str, object], quote: dict[str, object]
) -> None:
    """Receipt-time labeling must not conceal stale source observations."""
    stale = response([quote])
    stale.raw = BytesIO(json.dumps({"result": [quote], "usOut": 0}).encode())
    with requests.Session() as session:
        with (
            patch.object(
                session,
                "get",
                side_effect=[
                    response([instrument]),
                    stale,
                    response({"index_price": 81000}),
                    depth_response(),
                ],
            ),
            pytest.raises(ValueError, match="stale"),
        ):
            _ = fetch_snapshot(session)
        instrument["expiration_timestamp"] = 1
        with (
            patch.object(
                session,
                "get",
                side_effect=[
                    response([instrument]),
                    response([quote]),
                    response({"index_price": 81000}),
                    depth_response(),
                ],
            ),
            pytest.raises(ValueError, match="expired"),
        ):
            _ = fetch_snapshot(session)


def test_collector_cli_once_and_failures(tmp_path: Path) -> None:
    """One-shot mode reports failures; continuous mode retries on schedule."""
    arguments = [
        "collector",
        "--asset",
        "ETH",
        "--database",
        str(tmp_path / "history.sqlite"),
        "--once",
    ]
    with (
        patch("sys.argv", arguments),
        patch(
            "gui_calculator.options_collector.collect_once", return_value=1
        ) as collect,
    ):
        main()
        collect.assert_called_once_with(
            asset="ETH", path=tmp_path / "history.sqlite"
        )
    with (
        patch("sys.argv", arguments),
        patch(
            "gui_calculator.options_collector.collect_once",
            side_effect=requests.Timeout,
        ),
        pytest.raises(requests.Timeout),
    ):
        main()
    with (
        patch("sys.argv", ["collector", "--interval", "1"]),
        pytest.raises(SystemExit),
    ):
        main()
    sleep = MagicMock(side_effect=KeyboardInterrupt)
    with (
        patch("sys.argv", ["collector"]),
        patch(
            "gui_calculator.options_collector.collect_once",
            side_effect=requests.Timeout,
        ),
        patch("gui_calculator.options_collector.sleep", sleep),
        pytest.raises(KeyboardInterrupt),
    ):
        main()
    sleep.assert_called_once_with(300)


@pytest.mark.parametrize(
    "failure", [requests.ConnectionError, requests.Timeout]
)
def test_collection_recovers_from_transport_failure(
    tmp_path: Path,
    instrument: dict[str, object],
    quote: dict[str, object],
    *,
    failure: type[requests.RequestException],
) -> None:
    """A transient outage retries the failed read and saves a complete chain."""
    replies = [
        failure("Connection reset by peer"),
        response([instrument]),
        response([quote]),
        response({"index_price": 81000}),
        depth_response(),
    ]
    path = tmp_path / "retry.sqlite"
    with (
        patch("requests.Session.get", side_effect=replies) as get,
        patch("snapshot_tunnel.options_data.sleep") as sleep,
    ):
        assert collect_once(asset="BTC", path=path) == 1
    assert get.call_count == len(replies)
    sleep.assert_called_once_with(1)
    assert len(load_snapshots(path)) == 1


@pytest.mark.parametrize(
    ("failure", "attempts"),
    [
        (requests.ConnectionError, 2),
        (requests.Timeout, 2),
        (requests.exceptions.SSLError, 1),
        (requests.HTTPError, 1),
    ],
)
def test_transport_retry_limit(
    tmp_path: Path,
    *,
    failure: type[requests.RequestException],
    attempts: int,
) -> None:
    """Persistent outages are bounded; TLS and HTTP errors are not retried."""
    path = tmp_path / "failed.sqlite"
    with (
        patch("requests.Session.get", side_effect=failure) as get,
        patch("snapshot_tunnel.options_data.sleep") as sleep,
        pytest.raises(failure),
    ):
        _ = collect_once(asset="BTC", path=path)
    assert get.call_count == attempts
    assert all(call.kwargs["timeout"] == (3, 5) for call in get.call_args_list)
    assert sleep.call_count == attempts - 1
    assert not path.exists()


def test_missing_certificate_bundle(tmp_path: Path) -> None:
    """A broken local CA bundle fails without retries or persisted data."""
    path = tmp_path / "missing-ca.sqlite"
    failure = OSError("invalid path: /missing/certifi/cacert.pem")
    with (
        patch("requests.Session.get", side_effect=failure) as get,
        patch("snapshot_tunnel.options_data.sleep") as sleep,
        pytest.raises(requests.RequestException, match=r"cacert\.pem") as error,
    ):
        _ = collect_once(asset="BTC", path=path)
    assert error.value.__cause__ is failure
    get.assert_called_once()
    sleep.assert_not_called()
    assert not path.exists()


def test_depth_failure_does_not_save_partial_snapshot(
    tmp_path: Path, instrument: dict[str, object], quote: dict[str, object]
) -> None:
    """A failed depth download leaves no options-only snapshot behind."""
    from gui_calculator.options_collector import collect_once

    path = tmp_path / "failed.sqlite"
    with (
        patch(
            "requests.Session.get",
            side_effect=[
                response([instrument]),
                response([quote]),
                response({"index_price": 81000}),
                requests.Timeout("Bybit depth offline"),
            ],
        ),
        pytest.raises(requests.Timeout, match="depth offline"),
    ):
        _ = collect_once(asset="BTC", path=path)
    assert not path.exists()


@pytest.mark.parametrize("valid_schema", [True, False])
def test_loading_history_closes_database(
    tmp_path: Path, *, valid_schema: bool
) -> None:
    """Close history connections after successful reads and SQL failures."""
    path = tmp_path / "history.sqlite"
    connection = sqlite3.connect(path)
    try:
        if valid_schema:
            _ = connection.execute(
                "CREATE TABLE options_snapshots (available_at TEXT, "
                "asset TEXT, content TEXT)"
            )
        expected = (
            nullcontext()
            if valid_schema
            else pytest.raises(sqlite3.OperationalError, match="no such table")
        )
        with (
            patch(
                "gui_calculator.options_store.sqlite3.connect",
                return_value=connection,
            ),
            expected,
        ):
            assert load_snapshots(path) == ()
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            _ = connection.execute("SELECT 1")
    finally:
        connection.close()
