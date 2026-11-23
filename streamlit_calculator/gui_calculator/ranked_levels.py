# Copyright 2026 anchored-vwam-backtest contributors
"""Convert independent GEX ranks into explicit chart price columns."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import RankedWalls


def ranked_price_columns(walls: RankedWalls) -> dict[str, float]:
    """Keep missing ranks blank without substituting another side's strike.

    Returns:
        Call 1/2 and Put 1/2 strike prices in exposure-rank order.

    """
    return {
        f"options_{side}_{index + 1}": (
            ranked[index].strike if index < len(ranked) else math.nan
        )
        for side, ranked in (("call", walls.calls), ("put", walls.puts))
        for index in range(2)
    }
