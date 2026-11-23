# Copyright 2026 anchored-vwam-backtest contributors
"""Collect complete Deribit chains at their receipt-time availability."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import sleep
from typing import Literal

import koopec_calculus
import requests
from snapshot_tunnel.options_depth import fetch_depth
from snapshot_tunnel.options_model import Option, Snapshot
from snapshot_tunnel.validation import (
    integer,
    json_object,
)

API = "https://www.deribit.com/api/v2/public/"
MAX_TIMESTAMP_MS = 253402300799000  # Last second of year 9999.


@dataclass(frozen=True, kw_only=True)
class ChainObservation:
    """Keep exchange observation and local availability distinct."""

    snapshot: Snapshot
    observed_at: datetime


def _download(
    session: requests.Session,
    url: str,
    params: list[tuple[str, str]],
    *,
    attempts_left: int = 2,
) -> requests.Response:
    """Retry public reads after transient connection failures.

    Returns:
        The response from the first successful transport attempt.

    Raises:
        requests.ConnectionError: If retries fail or TLS verification fails.
        requests.Timeout: If all attempts time out.
        requests.RequestException: If local transport configuration is invalid.

    """
    try:
        return session.get(url, params=params, timeout=(3, 5))
    except (requests.ConnectionError, requests.Timeout) as exc:
        if attempts_left <= 1 or isinstance(exc, requests.exceptions.SSLError):
            raise
        sleep(1)
        return _download(session, url, params, attempts_left=attempts_left - 1)
    except requests.RequestException:
        raise
    except OSError as exc:
        msg = f"HTTPS transport configuration failed: {exc}"
        raise requests.RequestException(msg) from exc


def _request(
    session: requests.Session, method: str, asset: str
) -> dict[str, object]:
    """Fetch a public JSON-RPC result, rejecting exchange-level errors.

    Returns:
        Validated response envelope.

    Raises:
        ValueError: If the exchange returns an error or no result.

    """
    url, params = koopec_calculus.market_request(method, asset)
    response = _download(session, url, params)
    response.raise_for_status()
    payload = json_object(response.text)
    if "error" in payload or "result" not in payload:
        msg = "Deribit returned an error or missing result."
        raise ValueError(msg)
    return payload


def normalize_chain(
    instruments: object, quotes: object, *, asset: Literal["BTC", "ETH"]
) -> tuple[Option, ...]:
    """Convert normalized Rust contracts to the calculator's snapshot model.

    Returns:
        Complete normalized chain, including zero-OI contracts.

    """
    contracts = koopec_calculus.deribit_chain(
        json.dumps(instruments, allow_nan=False),
        json.dumps(quotes, allow_nan=False),
        asset,
    )
    return tuple(
        Option(
            exchange="DERIBIT",
            expiry=datetime.fromtimestamp(expiry_ms / 1000, UTC),
            strike=strike,
            side=side,
            open_interest=interest,
            multiplier=multiplier,
            iv=iv,
        )
        for _, side, strike, expiry_ms, iv, interest, multiplier in contracts
    )


def fetch_snapshot(
    session: requests.Session, *, asset: Literal["BTC", "ETH"] = "BTC"
) -> ChainObservation:
    """Collect a chain, rejecting slow, future-dated or expired observations.

    Returns:
        Snapshot available only after all requests finished.

    Raises:
        ValueError: If response timestamps or chain validity are unsuitable.

    """
    started = datetime.now(UTC)
    instruments = _request(session, "get_instruments", asset)
    summary = _request(session, "get_book_summary_by_currency", asset)
    index = _request(session, "get_index_price", asset)
    received = datetime.now(UTC)
    server_us = integer(summary["usOut"])
    if not 0 <= server_us <= MAX_TIMESTAMP_MS * 1000:
        msg = "Invalid Deribit observation timestamp."
        raise ValueError(msg)
    observed = datetime.fromtimestamp(server_us / 1_000_000, UTC)
    if received - started > timedelta(minutes=2) or not (
        started - timedelta(minutes=2)
        <= observed
        <= received + timedelta(seconds=5)
    ):
        msg = "Deribit observation is stale or clocks disagree."
        raise ValueError(msg)
    options = normalize_chain(
        instruments["result"], summary["result"], asset=asset
    )
    order_book = fetch_depth(session, asset=asset)
    received = datetime.now(UTC)
    if any(option.expiry <= received for option in options):
        msg = "Chain expired during collection; retry with a new chain."
        raise ValueError(msg)
    spot = koopec_calculus.deribit_spot(json.dumps(index, allow_nan=False))
    return ChainObservation(
        snapshot=Snapshot(
            timestamp=received,
            asset=asset,
            spot=spot,
            options=options,
            order_book=order_book,
        ),
        observed_at=observed,
    )
