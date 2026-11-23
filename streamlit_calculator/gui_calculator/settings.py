# Copyright 2026 anchored-vwam-backtest contributors
"""Typed values shared by the sidebar and calculator views."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, time, tzinfo
from io import BytesIO, StringIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.child_assets import ChildSymbol
    from snapshot_tunnel.archive_model import LocalArchiveSource

from shared.gex_rules import GexHypothesis
from shared.tunnel import TunnelSettings

type CSVSource = str | BytesIO | StringIO


@dataclass
class CalculatorSettings:
    """Hold validated calculator and indicator settings from the sidebar."""

    local_archive: LocalArchiveSource | None = None
    data_source: str = "Bybit REST"
    ticker: str = "BTC_USDT"
    reverse_ticker: bool = False
    base_currency: str = "BTC"
    quote_currency: str = "USDT"
    interval: str = "1m"
    selected_timezone: tzinfo = UTC
    timezone_label: str = "UTC"
    vwam_file: CSVSource | None = None
    vwam_method: str = "Microprice"
    show_vwam_chart: bool = False
    start_day: date = date.min
    start_hour: int = 0
    end_day: date = date.min
    end_hour: int = 23
    strategy_mode: str = "GEX"
    simulate_trades: bool = True
    child_assets: tuple[ChildSymbol, ...] = ()
    gex_hypothesis: GexHypothesis = GexHypothesis.TUNNEL
    tunnel: TunnelSettings = field(default_factory=TunnelSettings)
    initial_capital: float = 10000.0
    minimum_order_size: float = 5.0
    fee_pct: float = 0.04
    funding_rate_pct: float = 0.0
    use_leverage: bool = False
    leverage: int = 1
    slippage_bps: float = 0.0
    stop_loss_pct: float = 5.0
    take_profit_pct: float = 0.0
    allow_reentry: bool = True
    use_weekday_schedule: bool = False
    selected_weekday_names: list[str] = field(default_factory=list)
    active_session_start: time = time.min
    active_session_end: time = time.max
    use_full_history_range: bool = True
    strategy_start_day: date = date.min
    strategy_start_hour: int = 0
    strategy_end_day: date = date.min
    strategy_end_hour: int = 23
