# Copyright 2026 anchored-vwam-backtest contributors

from collections.abc import Sequence
from pathlib import Path

def strike_exposures(
    observed_at: int,
    available_at: int,
    valued_at: int,
    spot: float,
    contracts: Sequence[tuple[str, str, float, int, float, float, float]],
) -> list[tuple[float, float, float]]: ...
def options_max_pain(
    contracts: Sequence[tuple[str, str, float, int, float, float, float]],
) -> float | None: ...
def market_request(
    source: str, asset: str
) -> tuple[str, list[tuple[str, str]]]: ...
def bitget_growth(
    payload: str, received_ms: int
) -> list[tuple[int, float]]: ...
def bitget_rate(payload: str) -> tuple[int, float, float]: ...
def margin_momentum(
    period: str, points: Sequence[tuple[int, float]]
) -> list[float | None]: ...
def ranked_walls(
    levels: Sequence[tuple[float, float, float]],
    spot: float,
    distance: float | None,
) -> tuple[
    list[tuple[float, float, float]], list[tuple[float, float, float]]
]: ...
def archive_index(path: Path) -> list[tuple[str, str, str]]: ...
