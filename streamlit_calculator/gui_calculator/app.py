# Copyright 2026 anchored-vwam-backtest contributors
"""Provide app behavior."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import requests
import streamlit as st
from shared.candles import candle_rows
from shared.gex import OPTIONS_GEX_MODE
from shared.gex_rules import GexHypothesis
from shared.paper_config import (
    PAPER_BOT_CONFIG_FILE,
    PaperBotConfig,
)
from shared.strategy_data import BacktestWindow
from shared.time_utils import timeline_datetime
from shared.tunnel_config import TUNNEL_MODE
from snapshot_tunnel.local_archive import archive_tunnel_flow

from gui_calculator.candle_cache import (
    CandleMarket,
    KlineFetcher,
    load_cached_klines,
)
from gui_calculator.charts import ChartDisplay, build_chart
from gui_calculator.child_assets import render_child_assets
from gui_calculator.data_sources import (
    INTERVALS,
    fetch_bybit_klines,
)
from gui_calculator.local_archive_view import (
    archive_gex_history,
    archive_oscillators,
    archive_snapshot_at,
    archive_snapshots,
)
from gui_calculator.metrics import format_metric, summarize
from gui_calculator.observed_history import (
    RecordedCharts,
    visible_observations,
)
from gui_calculator.observed_oscillators import oscillator_lines
from gui_calculator.options_gex import (
    OptionsDisplay,
    render_options_gex_strategy,
)
from gui_calculator.tunnel_backtest import simulate_tunnel
from gui_calculator.tunnel_replay import replay_tunnel
from gui_calculator.ui_controls import WEEKDAYS, render_sidebar
from gui_calculator.vwam import render_vwam

if TYPE_CHECKING:
    from shared.models import Trade
    from snapshot_tunnel.options_model import Snapshot
    from snapshot_tunnel.tunnel_flow import TunnelFlow

    from gui_calculator.settings import CalculatorSettings


@dataclass(frozen=True, kw_only=True)
class RunWindow:
    """Validated history, strategy, and anchor timestamps."""

    start_at: pd.Timestamp
    end_at: pd.Timestamp
    strategy_start_at: pd.Timestamp
    strategy_end_at: pd.Timestamp
    anchor_at: pd.Timestamp


@dataclass(frozen=True, kw_only=True)
class LoadedCandles:
    """Candles and optional leverage contract metadata."""

    raw: pd.DataFrame
    display_ticker: str


@dataclass(frozen=True, kw_only=True)
class BacktestView:
    """Backtest inputs prepared for rendering."""

    data: pd.DataFrame
    equity: pd.DataFrame
    trades: list[Trade]
    settings: CalculatorSettings
    window: RunWindow
    display_ticker: str


def main() -> None:
    """Render and execute the Streamlit backtesting application."""
    configure_page()
    _render_backtester()


def _render_backtester() -> None:
    """Run only the local-archive Snapshot tunnel workflow."""
    settings = render_sidebar()
    _render_bot_config(settings)
    window = build_window(settings)
    if window is not None:
        render_strategy_backtest(settings, window)


def render_strategy_backtest(
    settings: CalculatorSettings, window: RunWindow
) -> None:
    """Load local tunnel evidence, simulate executions and render results."""
    if not _validate_strategy_settings(settings, window):
        return
    render_vwam(st, settings, start_at=window.start_at, end_at=window.end_at)
    loaded = _load_display_candles(settings, window)
    if loaded is None:
        return
    try:
        data = _prepare_options_strategy(loaded.raw, settings)
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        sqlite3.Error,
        requests.RequestException,
    ) as exc:
        _ = st.error(f"Cannot load local GEX strategy data: {exc}")
        return
    if not settings.simulate_trades:
        return
    result = _run_backtest(data, settings=settings, window=window)
    if result is not None:
        equity, trades = result
        _render_results(
            BacktestView(
                data=data,
                equity=equity,
                trades=trades,
                settings=settings,
                window=window,
                display_ticker=loaded.display_ticker,
            )
        )


def configure_page() -> None:
    """Configure the page title and theme-aware application styles."""
    st.set_page_config(page_title="Anchored VWAP Backtester", layout="wide")
    _ = st.html(
        Path(__file__).with_name("sidebar_accessibility.html"),
        unsafe_allow_javascript=True,
    )
    _ = st.title("Anchored VWAP Backtester")
    _ = st.markdown(
        """
        <style>
        [data-testid="stMetricLabel"],
        [data-testid="stCaptionContainer"] {
            color: inherit !important;
        }
        [data-testid="stCaptionContainer"] p,
        [data-testid="stMetricLabel"] p,
        [data-testid="stAlertContentInfo"] p {
            color: inherit !important;
        }
        [data-testid="stAlertContainer"],
        [data-testid="stAlertContentInfo"] {
            color: inherit !important;
        }
        [data-testid="stSelectbox"] [data-testid="stWidgetLabel"],
        [data-testid="stSelectbox"] [data-testid="stWidgetLabel"] span,
        [data-testid="stSelectbox"] [data-testid="stWidgetLabel"] p,
        [data-testid="stDateInput"] label,
        [data-testid="stDateInput"] > div,
        [data-testid="stDateInput"] span[aria-hidden="true"],
        [data-testid="stDateInput"] span[aria-hidden="true"] p {
            color: inherit !important;
            opacity: 1 !important;
        }
        [data-testid="stFileUploaderDropzoneInstructions"],
        [data-testid="stFileUploaderDropzoneInstructions"] span {
            color: inherit !important;
            opacity: 1 !important;
        }
        button[data-testid="stBaseButton-primary"] {
            background: #8f1230 !important;
            border-color: #8f1230 !important;
            color: #ffffff !important;
        }
        [data-testid="stMultiSelect"] [data-baseweb="select"] div {
            color: inherit !important;
            opacity: 1 !important;
        }
        [data-testid="stMultiSelect"] [data-baseweb="tag"] {
            background-color: #8f1230 !important;
        }
        [data-testid="stMultiSelect"] [data-baseweb="tag"],
        [data-testid="stMultiSelect"] [data-baseweb="tag"] * {
            color: #ffffff !important;
        }
        .plotly-notifier .notifier-note {
            background: #111827 !important;
            color: #ffffff !important;
            opacity: 1 !important;
        }
        [data-testid="stCaptionContainer"] { opacity: 1; }
        [data-testid="stMetricLabel"] { font-size: 0.8rem; }
        [data-testid="stMetricValue"] { font-size: 1.25rem; line-height: 1.3; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def build_window(settings: CalculatorSettings) -> RunWindow | None:
    """Clamp history and trading dates to the selected local archive.

    Returns:
        A valid replay period, or none after a visible date error.

    """
    start_at = pd.Timestamp(
        timeline_datetime(
            settings.start_day,
            settings.selected_timezone,
            hour=int(settings.start_hour),
        )
    )
    end_at = pd.Timestamp(
        timeline_datetime(
            settings.end_day,
            settings.selected_timezone,
            at=time(
                hour=int(settings.end_hour),
                minute=59,
                second=59,
                microsecond=999999,
            ),
        )
    )
    if settings.local_archive is not None:
        start_at = max(start_at, pd.Timestamp(settings.local_archive.start))
        end_at = min(end_at, pd.Timestamp(settings.local_archive.end))
    if start_at >= end_at:
        _ = st.error("History start must be before history end.")
        return None
    strategy_start_at, strategy_end_at = _build_strategy_window(
        settings, start_at=start_at, end_at=end_at
    )
    anchor_at = strategy_start_at
    return RunWindow(
        start_at=start_at,
        end_at=end_at,
        strategy_start_at=strategy_start_at,
        strategy_end_at=strategy_end_at,
        anchor_at=anchor_at,
    )


def _build_strategy_window(
    settings: CalculatorSettings,
    *,
    start_at: pd.Timestamp,
    end_at: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    if settings.use_full_history_range:
        return start_at, end_at
    return (
        pd.Timestamp(
            timeline_datetime(
                settings.strategy_start_day,
                settings.selected_timezone,
                hour=int(settings.strategy_start_hour),
            )
        ),
        pd.Timestamp(
            timeline_datetime(
                settings.strategy_end_day,
                settings.selected_timezone,
                hour=int(settings.strategy_end_hour),
            )
        ),
    )


def _validate_strategy_settings(
    settings: CalculatorSettings, window: RunWindow
) -> bool:
    if (
        settings.strategy_mode != OPTIONS_GEX_MODE
        or settings.gex_hypothesis != GexHypothesis.TUNNEL
    ):
        _ = st.error("Only Snapshot tunnel is supported.")
        return False
    if settings.local_archive is None:
        _ = st.error(
            "Select a local GEX archive before running Snapshot tunnel."
        )
        return False
    if (
        settings.ticker != "BTC_USDT"
        or settings.reverse_ticker
        or settings.leverage != 1
    ):
        _ = st.error("Snapshot tunnel requires non-reversed BTC_USDT at 1x.")
        return False
    if window.strategy_start_at >= window.strategy_end_at:
        _ = st.error("Strategy start must be before strategy end.")
        return False
    if (
        window.strategy_start_at < window.start_at
        or window.strategy_end_at > window.end_at
    ):
        _ = st.error(
            "Strategy start and end must be inside the selected history range."
        )
        return False
    return _validate_session_settings(settings)


def _validate_session_settings(settings: CalculatorSettings) -> bool:
    if settings.use_weekday_schedule and not settings.selected_weekday_names:
        _ = st.error("Select at least one active weekday.")
        return False
    if (
        settings.use_weekday_schedule
        and settings.active_session_start == settings.active_session_end
    ):
        _ = st.error("Trade start and end times must be different.")
        return False
    return True


def _load_display_candles(
    settings: CalculatorSettings, window: RunWindow
) -> LoadedCandles | None:
    raw = _load_raw_candles(settings, window)
    if raw is None:
        return None
    raw = _filter_candles(raw, settings, window)
    if raw.empty:
        _ = st.warning("No completed candles returned for this range.")
        return None
    return LoadedCandles(raw=raw, display_ticker=settings.ticker)


def _load_raw_candles(
    settings: CalculatorSettings, window: RunWindow
) -> pd.DataFrame | None:
    try:
        return _fetch_raw_candles(settings, window)
    except (ValueError, requests.RequestException, sqlite3.Error) as exc:
        _ = st.error(f"Could not load candles: {exc}")
        return None


def _fetch_raw_candles(
    settings: CalculatorSettings, window: RunWindow
) -> pd.DataFrame:
    if settings.data_source != "Bybit REST" or settings.ticker != "BTC_USDT":
        msg = "Only Bybit REST BTC_USDT candles are supported."
        raise ValueError(msg)
    with st.spinner("Loading Bybit historical data..."):
        return _cached_exchange_klines(
            source="bybit_linear",
            symbol="BTCUSDT",
            settings=settings,
            window=window,
            fetcher=fetch_bybit_klines,
        )


def _cached_exchange_klines(
    *,
    source: str,
    symbol: str,
    settings: CalculatorSettings,
    window: RunWindow,
    fetcher: KlineFetcher,
) -> pd.DataFrame:
    return load_cached_klines(
        CandleMarket(
            exchange=source, symbol=symbol, interval=settings.interval
        ),
        start_ms=int(window.start_at.timestamp() * 1000),
        end_ms=int(window.end_at.timestamp() * 1000),
        fetcher=fetcher,
    )


def _filter_candles(
    raw: pd.DataFrame, settings: CalculatorSettings, window: RunWindow
) -> pd.DataFrame:
    completed = raw[
        pd.to_datetime(raw["time"], utc=True)
        + INTERVALS[settings.interval]["delta"]
        <= pd.Timestamp.now(tz="UTC")
    ]
    return completed[
        (completed["time"] >= window.start_at)
        & (completed["time"] <= window.end_at)
    ].reset_index(drop=True)


def _run_backtest(
    data: pd.DataFrame, *, settings: CalculatorSettings, window: RunWindow
) -> tuple[pd.DataFrame, list[Trade]] | None:
    try:
        equity, trades = simulate_tunnel(
            data,
            settings=settings,
            window=BacktestWindow(
                start=window.strategy_start_at,
                end=window.strategy_end_at,
                weekdays=(
                    frozenset(_active_weekdays(settings) or ())
                    if settings.use_weekday_schedule
                    else None
                ),
                timezone=settings.selected_timezone,
                session_start=settings.active_session_start,
                session_end=settings.active_session_end,
            ),
        )
    except ValueError as exc:
        _ = st.error(f"Cannot calculate backtest: {exc}")
        return None
    if equity.empty:
        _ = st.warning(
            "No candles exist inside the selected strategy dates and sessions."
        )
        return None
    return equity, trades


def _active_weekdays(settings: CalculatorSettings) -> set[int] | None:
    if not settings.use_weekday_schedule:
        return None
    return {WEEKDAYS.index(name) for name in settings.selected_weekday_names}


def _render_results(view: BacktestView) -> None:
    _render_metrics(view.equity, view.trades, view.settings)
    _render_chart(view)
    _render_trades(view.trades, view.settings)
    render_child_assets(view.trades, view.equity, view.settings)
    _render_strategy_rules()


def _render_metrics(
    equity: pd.DataFrame, trades: list[Trade], settings: CalculatorSettings
) -> None:
    stats = summarize(equity, trades, settings.initial_capital)
    metric_columns = st.columns(8)
    for column, (label, value) in zip(
        metric_columns, stats.items(), strict=True
    ):
        _ = column.metric(
            label, format_metric(value, label, settings.quote_currency)
        )


def _observed_chart_history(
    settings: CalculatorSettings, data: pd.DataFrame
) -> RecordedCharts:
    """Build charts only from the selected local archive.

    Returns:
        Receipt-time GEX history and independent oscillator observations.

    Raises:
        ValueError: If no local archive is selected.

    """
    if settings.local_archive is None:
        msg = "Select a local GEX archive."
        raise ValueError(msg)
    history = archive_gex_history(
        settings.local_archive, level_range=settings.tunnel.level_range
    )
    return RecordedCharts(
        gex=visible_observations(history, data),
        oscillators=oscillator_lines(
            archive_oscillators(settings.local_archive), data
        ),
    )


def _render_chart(view: BacktestView) -> None:
    # Streamlit exposes unknown optional chart selection types in this overload.
    _ = st.plotly_chart(  # pyright: ignore[reportUnknownMemberType]
        build_chart(
            view.data,
            view.equity,
            view.trades,
            options_history=_observed_chart_history(view.settings, view.data),
            display=ChartDisplay(
                strategy_start_at=view.window.strategy_start_at,
                strategy_end_at=view.window.strategy_end_at,
                selected_timezone=view.settings.selected_timezone,
                timezone_label=view.settings.timezone_label,
                symbol=view.display_ticker,
                quote_currency=view.settings.quote_currency,
            ),
        ),
        use_container_width=True,
    )


def _render_trades(trades: list[Trade], settings: CalculatorSettings) -> None:
    trades_df = pd.DataFrame([trade.__dict__ for trade in trades])
    if trades_df.empty:
        _ = st.info("No trades were generated for this configuration.")
        return
    trades_df["deposit_size"] = trades_df["deposit_size"].round(2)
    trades_df["entry_time"] = pd.to_datetime(
        trades_df["entry_time"], utc=True
    ).dt.tz_convert(settings.selected_timezone)
    trades_df["exit_time"] = pd.to_datetime(
        trades_df["exit_time"], utc=True
    ).dt.tz_convert(settings.selected_timezone)
    trades_df["pnl"] = trades_df["pnl"].round(8)
    trades_df["return_pct"] = trades_df["return_pct"].round(2)
    _ = st.subheader("Trades")
    _ = st.dataframe(
        trades_df,
        column_config={
            "deposit_size": f"Deposit size ({settings.quote_currency})",
            "pnl": f"P&L ({settings.quote_currency})",
        },
        use_container_width=True,
        hide_index=True,
    )


def _render_bot_config(settings: CalculatorSettings) -> None:
    _ = st.subheader("Paper bot configuration")
    _ = st.caption(
        "Exports the current Snapshot tunnel parameters for the separate"
        " local-paper CLI bot."
    )
    config = paper_bot_config(settings)
    content, error = _serialize_bot_config(config)
    if st.button(
        "Save paper bot config", type="primary", disabled=error is not None
    ):
        save_paper_bot_config(config)
    _ = st.download_button(
        "Download paper bot config",
        data=content,
        file_name=PAPER_BOT_CONFIG_FILE.name,
        mime="application/json",
        disabled=error is not None,
    )
    _ = st.caption(
        "Run or start paper_trading_bot.cli. Positive GEX uses option-level"
        " proximity and OI divergence; negative GEX uses oscillator direction"
        " and OI convergence. Enabled confirmations govern BTC entries; child"
        " assets copy executed entries and exits. Positions exit by SL/TP or"
        " the selected session boundary."
    )


def paper_bot_config(settings: CalculatorSettings) -> PaperBotConfig:
    """Export only the supported Snapshot tunnel setup.

    Returns:
        Local paper-runner configuration without a legacy strategy selector.

    Raises:
        ValueError: If a removed strategy is requested.

    """
    if (
        settings.strategy_mode != OPTIONS_GEX_MODE
        or settings.gex_hypothesis != GexHypothesis.TUNNEL
    ):
        msg = "Only Snapshot tunnel is supported."
        raise ValueError(msg)
    return PaperBotConfig(
        strategy_mode=TUNNEL_MODE,
        timeframe=settings.interval,
        trend=False,
        open_order_vwap_sigma=0,
        close_order_vwap_sigma=0,
        vwap_anchor_reset_weeks=1,
        initial_capital=settings.initial_capital,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        allow_immediate_reentry=settings.allow_reentry,
        data_source=settings.data_source,
        ticker=settings.ticker,
        minimum_order_size=settings.minimum_order_size,
        slippage_bps=settings.slippage_bps,
        tunnel=settings.tunnel,
    )


def _serialize_bot_config(
    bot_config: PaperBotConfig,
) -> tuple[str, str | None]:
    try:
        return bot_config.to_json(), None
    except ValueError as exc:
        _ = st.warning(f"Paper bot configuration unavailable: {exc}")
        return "", str(exc)


def save_paper_bot_config(bot_config: PaperBotConfig) -> None:
    """Save the current tunnel export and report persistence failures."""
    try:
        bot_config.save()
        _ = st.success(f"Saved {PAPER_BOT_CONFIG_FILE.name}")
    except (OSError, ValueError) as exc:
        _ = st.error(f"Could not save paper bot config: {exc}")


def _render_strategy_rules() -> None:
    with st.expander("Strategy rules"):
        _ = st.write(
            "Snapshot tunnel reads saved local BTC chains and independent"
            " receipt-stamped oscillators. Positive GEX requires proximity to"
            " an eligible state 1/2/3 option level, oscillator confirmation and"
            " enabled OI divergence. Negative GEX uses oscillator direction"
            " without option-level structure and requires enabled OI"
            " convergence. At least one oscillator must confirm. Negative longs"
            " retain the optional entry-time gamma-flip TP cap; without a flip,"
            " ordinary percentage TP applies. Capital funds one BTC position."
            " Child assets mirror executed BTC entries and exits. SL/TP, fees,"
            " slippage, and session-end closures remain active."
        )


def warn_tunnel_dates(data: pd.DataFrame, settings: CalculatorSettings) -> None:
    """Warn about missing oscillator coverage inside the strategy period."""
    window = build_window(settings)
    if window is None:
        return
    period = data.loc[
        data["time"].between(window.strategy_start_at, window.strategy_end_at)
    ].copy()
    period["date"] = [
        bar.time.tz_convert(settings.selected_timezone).date()
        for bar in candle_rows(period)
    ]
    for day, rows in period.groupby("date", sort=True):
        missing = ~rows["tunnel_oscillators_available"]
        if missing.any():
            extent = "Entire date" if missing.all() else "Part of date"
            _ = st.warning(
                f"{day}: Uncalculatable — {extent.lower()} lacks enough fresh "
                "data from the enabled oscillators to meet the required "
                "quorum. Affected candles are skipped for new entries. "
                f"Dates use {settings.timezone_label}."
            )


@dataclass(frozen=True, kw_only=True)
class TunnelHistory:
    """Selected chains and independent oscillator receipts for tunnel replay."""

    snapshots: tuple[Snapshot, ...]
    flow: TunnelFlow


def load_tunnel_history(settings: CalculatorSettings) -> TunnelHistory:
    """Read only the selected local GEX and independent oscillator receipts.

    Returns:
        Causal evidence from one versioned SQLite archive.

    Raises:
        ValueError: If no local archive is selected.

    """
    if settings.local_archive is None:
        msg = "Select a local GEX archive."
        raise ValueError(msg)
    return TunnelHistory(
        snapshots=archive_snapshots(settings.local_archive),
        flow=archive_tunnel_flow(
            archive_oscillators(settings.local_archive), settings.tunnel
        ),
    )


def _profile_snapshots(
    settings: CalculatorSettings,
    snapshots: tuple[Snapshot, ...],
    data: pd.DataFrame,
) -> tuple[Snapshot, ...]:
    """Keep the profile aligned with the latest recorded history observation.

    Returns:
        Available profile input without changing frozen execution chains.

    """
    if settings.local_archive is None:
        return snapshots
    cutoff = pd.to_datetime(data["time"], utc=True).max().to_pydatetime()
    latest = archive_snapshot_at(settings.local_archive, cutoff)
    return (latest,) if latest is not None else snapshots


def _prepare_options_strategy(
    data: pd.DataFrame, settings: CalculatorSettings
) -> pd.DataFrame:
    """Load point-in-time inputs and display the selected strategy provenance.

    Returns:
        Execution candles with the selected causal options signals.

    """
    history = load_tunnel_history(settings)
    snapshots = history.snapshots
    flow = history.flow
    result = replay_tunnel(
        data,
        snapshots,
        settings=settings.tunnel,
        flow=flow,
        interval=INTERVALS[settings.interval]["delta"],
    )
    warn_tunnel_dates(result, settings)
    if settings.tunnel.use_gex and result["options_gex"].isna().all():
        _ = st.warning(
            "No usable tunnel plans in this window. Check archive coverage,"
            " contract expiries and gamma flip availability."
        )
    render_options_gex_strategy(
        st,
        result,
        content=_profile_snapshots(settings, snapshots, data),
        display=OptionsDisplay(level_range=settings.tunnel.level_range),
        observed_history=_observed_chart_history(settings, data),
    )
    _ = st.caption(
        "Snapshot tunnel replay uses saved BTC chains nearest 08:15 UTC per"
        " date. Plans begin at actual receipt, last up to 24 hours and are"
        " replaced by the next selected plan. Market entries use opening quotes"
        " with fresh oscillator confirmation. Insurance orders are disabled."
        " Intrabar path and exact trigger time are unavailable from OHLC. All"
        " calculated GEX values and plan levels are shown below. Charts use"
        " every recorded five-minute observation; daily plan values remain in"
        " the execution audit. Negative GEX uses oscillator direction and OI"
        " convergence; positive GEX uses option-level proximity and OI"
        " divergence. State 0 disables GEX-confirmed entries. With GEX off,"
        " oscillator quorum alone selects entries. The available capital funds"
        " one position."
    )
    _ = st.dataframe(
        result[[
            "time",
            "tunnel_status",
            "tunnel_state",
            "tunnel_gex_enabled",
            "tunnel_oi_mode",
            "options_target_ceiling",
            "options_gex",
            "options_gamma_flip",
            "options_call_1",
            "options_call_2",
            "options_put_1",
            "options_put_2",
            "options_gex_time",
            "options_valid_until",
            "tunnel_oscillators_available",
            "tunnel_votes",
            "options_direction",
            "options_insurance",
        ]],
        hide_index=True,
    )
    return result
