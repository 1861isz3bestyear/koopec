# Copyright 2026 anchored-vwam-backtest contributors
"""Pure order-book liquidity composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

import koopec_calculus

if TYPE_CHECKING:

    from snapshot_tunnel.order_book import BookSnapshot


def limit_order_oscillator_rate(book: BookSnapshot) -> float:
    """Calculate bid share of resting quote-currency notional.

    Returns:
        A 0-100 bid/ask liquidity rate, independent of price changes.

    """
    return koopec_calculus.depth_notional_rate(
        [(level.price, level.quantity) for level in book.bids],
        [(level.price, level.quantity) for level in book.asks],
    )
