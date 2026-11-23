# Copyright 2026 anchored-vwam-backtest contributors

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

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
def archive_index(
    path: Path, asset: str | None = None
) -> list[tuple[str, str, str]]: ...
def deribit_chain(
    instruments: str, quotes: str, asset: str
) -> list[
    tuple[str, Literal["call", "put"], float, int, float, float, float]
]: ...
def deribit_spot(payload: str) -> float: ...
def save_options(
    path: Path, row: tuple[str, str, str, str, str, str | None]
) -> None: ...
def load_options(path: Path) -> list[tuple[str, str | None]]: ...
def save_market(
    path: Path,
    row: tuple[str, str, str, str, str, str, str],
    collection_start: str | None,
    compact: bool,
) -> None: ...
def load_market(
    path: Path, bounds: tuple[str, str, str], sources: Sequence[str]
) -> list[tuple[str, str, str, str, str]]: ...

type _CandleKey = tuple[str, str, str]
type _CandleRow = tuple[int, float, float, float, float, float, float, int]

def initialize_candles(path: Path) -> None: ...
def upsert_candles(
    path: Path, market: _CandleKey, rows: Sequence[_CandleRow]
) -> None: ...
def mark_candle_download(
    path: Path, market: _CandleKey, bounds: tuple[int, int]
) -> None: ...
def missing_candle_ranges(
    path: Path, market: _CandleKey, bounds: tuple[int, int]
) -> list[tuple[int, int]]: ...
def load_candles(
    path: Path, market: _CandleKey, bounds: tuple[int, int]
) -> list[_CandleRow]: ...
def bybit_interest_page(
    payload: str,
) -> tuple[list[tuple[int, float]], str]: ...
def oi_momentum(
    interval_seconds: int, samples: Sequence[tuple[int, int, float, float]]
) -> list[float | None]: ...
def daily_receipts(receipts: Sequence[tuple[int, int]]) -> list[int]: ...
def replay_plan_indices(
    windows: Sequence[tuple[int, int]], quotes: Sequence[int]
) -> list[int | None]: ...
def validate_archive(path: Path) -> None: ...
def backup_archive(source: Path, destination: Path) -> None: ...
