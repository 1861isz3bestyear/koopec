# Copyright 2026 anchored-vwam-backtest contributors

from collections.abc import Sequence

def strike_exposures(
    observed_at: int,
    available_at: int,
    valued_at: int,
    spot: float,
    contracts: Sequence[tuple[str, str, float, int, float, float, float]],
) -> list[tuple[float, float, float]]: ...
