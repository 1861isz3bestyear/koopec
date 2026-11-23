# Copyright 2026 anchored-vwam-backtest contributors
"""Compare observed GEX structure without inferring dealer inventories."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Literal

import pandas as pd
from snapshot_tunnel.gamma_search import search_flips
from snapshot_tunnel.options_model import net_exposure, strike_exposures

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot


def exposure_breakdown(
    snapshot: Snapshot, *, scope: Literal["Strike", "Expiry"]
) -> pd.DataFrame:
    """Aggregate signed side exposures at the snapshot's own spot and time.

    Returns:
        Net, call and put exposure for each observed strike or expiry.

    """
    if scope == "Strike":
        return pd.DataFrame([
            {
                "Strike": level.strike,
                "Call GEX": level.call,
                "Put GEX": level.put,
                "Net GEX": level.net,
            }
            for level in strike_exposures(snapshot)
        ]).set_index("Strike")
    rows: list[dict[str, object]] = []
    for expiry in sorted({option.expiry for option in snapshot.options}):
        chain = replace(
            snapshot,
            options=tuple(
                option for option in snapshot.options if option.expiry == expiry
            ),
        )
        levels = strike_exposures(chain)
        rows.append({
            "Expiry": expiry.isoformat(),
            "Call GEX": sum(level.call for level in levels),
            "Put GEX": sum(level.put for level in levels),
            "Net GEX": sum(level.net for level in levels),
        })
    return pd.DataFrame(rows).set_index("Expiry")


def compare_breakdown(
    before: Snapshot, after: Snapshot, *, scope: Literal["Strike", "Expiry"]
) -> pd.DataFrame:
    """Align observations without treating absent contracts as known zero OI.

    Returns:
        Outer-joined exposure levels with changes only for shared groups.

    """
    previous = exposure_breakdown(before, scope=scope).add_prefix("Before ")
    current = exposure_breakdown(after, scope=scope).add_prefix("After ")
    result = previous.join(current, how="outer").sort_index()
    result["Net GEX change"] = (
        result["After Net GEX"] - result["Before Net GEX"]
    )
    if scope == "Strike":
        result["Distance from current spot (%)"] = (
            result.index.to_series() / after.spot - 1
        ) * 100
    else:
        result["Days to expiry (after snapshot)"] = (
            pd.to_datetime(result.index, utc=True) - after.timestamp
        ).total_seconds() / 86400
    return result


def comparison_summary(before: Snapshot, after: Snapshot) -> pd.DataFrame:
    """Summarize observed changes and distance to each snapshot's nearest flip.

    Returns:
        Numerical before/after values with unavailable flips left missing.

    """
    columns: dict[str, list[float | None]] = {}
    for label, snapshot in (("Before", before), ("After", after)):
        flip = search_flips(snapshot).nearest
        columns[label] = [
            snapshot.spot,
            net_exposure(snapshot, snapshot.spot),
            flip,
            (snapshot.spot / flip - 1) * 100 if flip is not None else None,
        ]
    result = pd.DataFrame(
        columns,
        index=[
            "Spot (USD)",
            "Net GEX (USD / 1% move)",
            "Nearest flip (USD)",
            "Spot vs flip (%)",
        ],
    )
    result["Change (after - before)"] = result["After"] - result["Before"]
    return result
