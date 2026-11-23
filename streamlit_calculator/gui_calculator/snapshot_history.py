# Copyright 2026 anchored-vwam-backtest contributors
"""Snapshot-by-snapshot analytics for imported options archives."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st
from snapshot_tunnel.gamma_search import search_flips
from snapshot_tunnel.options_model import ranked_walls, strike_exposures

if TYPE_CHECKING:
    from snapshot_tunnel.options_model import Snapshot


@st.cache_data(show_spinner=False)
def snapshot_history(snapshots: tuple[Snapshot, ...]) -> pd.DataFrame:
    """Calculate each recorded chain at its own timestamp and spot.

    Returns:
        Chronological observations with unavailable levels left missing.

    """
    rows: list[dict[str, object]] = []
    for snapshot in sorted(snapshots, key=lambda item: item.timestamp):
        levels = strike_exposures(snapshot)
        walls = ranked_walls(levels, spot=snapshot.spot)
        rows.append({
            "Timestamp (UTC)": snapshot.timestamp,
            "Price": snapshot.spot,
            "Net GEX": sum(level.net for level in levels),
            "Gamma flip": search_flips(snapshot).nearest,
            **{
                f"{side} {rank + 1}": (
                    ranked[rank].strike if rank < len(ranked) else None
                )
                for side, ranked in (("Call", walls.calls), ("Put", walls.puts))
                for rank in range(2)
            },
        })
    return pd.DataFrame(rows)
