# Copyright 2026 anchored-vwam-backtest contributors
"""Validated exchange observations for independent market oscillators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from shared.validation import (
    json_object,
    numeric_string,
    object_list,
    object_mapping,
)

if TYPE_CHECKING:
    import requests


_BOOK_LEVEL_WIDTH = 2


@dataclass(frozen=True, kw_only=True)
class BookObservation:
    """Top-50 linear-book depth with an exchange timestamp and midpoint."""

    timestamp: datetime
    price: float
    bid_quantity: float
    ask_quantity: float

    @property
    def oscillator(self) -> float:
        """Bid share of displayed base-asset quantity, on a 0-100 scale."""
        return 100 * self.bid_quantity / (self.bid_quantity + self.ask_quantity)


def _book_levels(value: object) -> tuple[tuple[float, float], ...]:
    """Validate positive prices and nonnegative quantities.

    Returns:
        Nonempty validated exchange levels.

    Raises:
        ValueError: If levels are empty or contain invalid values.

    """
    levels: list[tuple[float, float]] = []
    for raw in object_list(value):
        row = object_list(raw)
        if len(row) != _BOOK_LEVEL_WIDTH:
            msg = "Order-book levels must contain price and quantity."
            raise ValueError(msg)
        price, quantity = (numeric_string(cell) for cell in row)
        if price <= 0 or quantity < 0:
            msg = "Invalid order-book price or quantity."
            raise ValueError(msg)
        levels.append((price, quantity))
    if not levels:
        msg = "Order-book side is empty."
        raise ValueError(msg)
    return tuple(levels)


def parse_book(payload: str, *, symbol: str) -> BookObservation:
    """Validate a Bybit REST order-book snapshot.

    Returns:
        A noncrossed book with positive total depth.

    Raises:
        ValueError: If the exchange rejects the request or the book is invalid.

    """
    body = json_object(payload)
    if body.get("retCode") != 0:
        msg = f"Bybit book error: {body.get('retMsg', 'invalid response')}"
        raise ValueError(msg)
    result = object_mapping(body["result"])
    if result.get("s") != symbol:
        msg = "Order-book symbol does not match the request."
        raise ValueError(msg)
    bids = _book_levels(result["b"])
    asks = _book_levels(result["a"])
    best_bid = max(price for price, _ in bids)
    best_ask = min(price for price, _ in asks)
    bid_quantity = sum(quantity for _, quantity in bids)
    ask_quantity = sum(quantity for _, quantity in asks)
    if best_bid >= best_ask or bid_quantity + ask_quantity <= 0:
        msg = "Order book is crossed or has no depth."
        raise ValueError(msg)
    return BookObservation(
        timestamp=datetime.fromtimestamp(
            numeric_string(body["time"]) / 1000, tz=UTC
        ),
        price=(best_bid + best_ask) / 2,
        bid_quantity=bid_quantity,
        ask_quantity=ask_quantity,
    )


def fetch_book(session: requests.Session, *, asset: str) -> BookObservation:
    """Download current top-50 Bybit linear depth.

    Returns:
        The validated exchange observation.

    """
    symbol = f"{asset}USDT"
    response = session.get(
        "https://api.bybit.com/v5/market/orderbook",
        params={"category": "linear", "symbol": symbol, "limit": 50},
        timeout=15,
    )
    response.raise_for_status()
    return parse_book(response.text, symbol=symbol)
