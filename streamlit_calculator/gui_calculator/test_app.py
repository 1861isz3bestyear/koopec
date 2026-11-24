# Copyright 2026 anchored-vwam-backtest contributors
"""Verify the local-only tunnel application and its failure boundaries."""

import runpy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests
from shared.gex_rules import GexHypothesis
from shared.strategy_data import BacktestWindow
from snapshot_tunnel.local_archive import inspect_archive
from snapshot_tunnel.options_model import parse_snapshots

from gui_calculator import app
from gui_calculator.options_gex import EXAMPLE
from gui_calculator.settings import CalculatorSettings
from gui_calculator.tunnel_backtest import simulate_tunnel
from tests.frontend.archive_fixture import write_archive
from tests.support import call_args, mock_child


@pytest.fixture
def settings(tmp_path: Path) -> CalculatorSettings:
    """Provide a real local archive and its selectable replay window.

    Returns:
        Snapshot tunnel inputs with receipt-stamped independent evidence.

    """
    snapshot = parse_snapshots(EXAMPLE)[0]
    path = tmp_path / "tunnel.sqlite"
    write_archive(path, snapshot)
    source = inspect_archive(path)
    return CalculatorSettings(
        local_archive=source,
        start_day=source.start.date(),
        end_day=source.end.date(),
        start_hour=source.start.hour,
        end_hour=source.end.hour,
        initial_capital=1000,
        stop_loss_pct=2,
        take_profit_pct=5,
        interval="5m",
    )


@pytest.fixture
def ui(
    monkeypatch: pytest.MonkeyPatch, settings: CalculatorSettings
) -> tuple[MagicMock, pd.DataFrame, MagicMock]:
    """Stub candle IO while exercising real archive replay and rendering.

    Returns:
        Recorded UI calls, chronological prices and the exchange adapter.

    """
    st = MagicMock()
    mock_child(st, "columns").return_value = [MagicMock() for _ in range(8)]
    mock_child(st, "button").return_value = False
    monkeypatch.setattr(app, "st", st)
    monkeypatch.setattr(app, "render_sidebar", lambda: settings)
    source = settings.local_archive
    assert source is not None
    raw = pd.DataFrame({
        "time": pd.date_range(source.start, source.end, freq="5min"),
    })
    raw = raw.assign(
        open=80000.0, high=81000.0, low=79000.0, close=80000.0, volume=10.0
    )
    loader = MagicMock(return_value=raw)
    monkeypatch.setattr(app, "load_cached_klines", loader)
    return st, raw, loader


def test_local_archive_runs_without_other_strategy_dispatch(
    ui: tuple[MagicMock, pd.DataFrame, MagicMock],
) -> None:
    """Render actual local tunnel analytics, account metrics and export."""
    st, _, loader = ui
    app.main()
    loader.assert_called_once()
    mock_child(st, "plotly_chart").assert_called()
    mock_child(st, "error").assert_not_called()
    assert not hasattr(app, "backtest")
    assert not hasattr(app, "load_daily_strategy")
    assert not hasattr(app, "load_strategy_options")


@pytest.mark.parametrize(
    "mode",
    [
        "AVWAP crossover",
        "VWAP band mean reversion",
        "VWAP zero hedge",
        "Trade/Book imbalance",
    ],
)
def test_removed_strategy_cannot_run_or_export(
    ui: tuple[MagicMock, pd.DataFrame, MagicMock],
    settings: CalculatorSettings,
    mode: str,
) -> None:
    """Backend rejection cannot be bypassed by changing hidden settings."""
    st, _, loader = ui
    settings.strategy_mode = mode
    window = app.build_window(settings)
    assert window is not None
    app.render_strategy_backtest(settings, window)
    loader.assert_not_called()
    assert "Only Snapshot tunnel" in str(call_args(mock_child(st, "error")))
    with pytest.raises(ValueError, match="Only Snapshot tunnel"):
        _ = app.paper_bot_config(settings)


@pytest.mark.parametrize(
    "hypothesis",
    [GexHypothesis.DAILY, GexHypothesis.SIGN, GexHypothesis.REGIME],
)
def test_other_gex_setups_cannot_run(
    settings: CalculatorSettings, hypothesis: GexHypothesis
) -> None:
    """The single executor rejects the old GEX strategies."""
    settings.gex_hypothesis = hypothesis
    with pytest.raises(ValueError, match="Only Snapshot tunnel"):
        _ = simulate_tunnel(
            pd.DataFrame(),
            settings=settings,
            window=BacktestWindow(
                start=pd.Timestamp("2026-01-01", tz="UTC"),
                end=pd.Timestamp("2026-01-02", tz="UTC"),
            ),
        )


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "reversed",
        "leverage",
        "dates",
        "outside",
        "weekdays",
        "session",
    ],
)
def test_invalid_local_setup_stops_before_price_loading(
    ui: tuple[MagicMock, pd.DataFrame, MagicMock],
    settings: CalculatorSettings,
    fault: str,
) -> None:
    """Reject invalid market and session selections before external IO."""
    st, _, loader = ui
    window = app.build_window(settings)
    assert window is not None
    if fault == "missing":
        settings.local_archive = None
    elif fault == "reversed":
        settings.reverse_ticker = True
    elif fault == "leverage":
        settings.leverage = 2
    elif fault == "dates":
        window = replace(window, strategy_end_at=window.strategy_start_at)
    elif fault == "outside":
        window = replace(
            window, strategy_end_at=window.end_at + timedelta(days=1)
        )
    elif fault == "weekdays":
        settings.use_weekday_schedule = True
    else:
        settings.use_weekday_schedule = True
        settings.selected_weekday_names = ["Monday"]
        settings.active_session_start = settings.active_session_end
    app.render_strategy_backtest(settings, window)
    loader.assert_not_called()
    mock_child(st, "error").assert_called_once()


@pytest.mark.parametrize("failure", ["empty", "network", "prices"])
def test_price_failures_are_visible(
    ui: tuple[MagicMock, pd.DataFrame, MagicMock], failure: str
) -> None:
    """An empty response or bad external data never becomes a trade."""
    st, raw, loader = ui
    if failure == "network":
        loader.side_effect = requests.RequestException("offline")
    else:
        loader.return_value = (
            raw.iloc[:0] if failure == "empty" else raw.assign(high=1)
        )
    app.main()
    assert mock_child(st, "warning").called or mock_child(st, "error").called


def test_disabled_simulation_keeps_analytics(
    ui: tuple[MagicMock, pd.DataFrame, MagicMock],
    settings: CalculatorSettings,
) -> None:
    """Analytics remain available when trade simulation is disabled."""
    st, _, _ = ui
    settings.simulate_trades = False
    app.main()
    assert not any("Final equity" in str(call) for call in st.mock_calls)
    mock_child(st, "dataframe").assert_called()


@pytest.mark.parametrize("failed", [False, True])
def test_paper_configuration_save(
    ui: tuple[MagicMock, pd.DataFrame, MagicMock],
    settings: CalculatorSettings,
    *,
    failed: bool,
) -> None:
    """Persist the tunnel export and show actionable filesystem errors."""
    st, _, _ = ui
    config = app.paper_bot_config(settings)
    with patch.object(
        type(config),
        "save",
        side_effect=OSError("read only") if failed else None,
    ):
        app.save_paper_bot_config(config)
    mock_child(st, "error" if failed else "success").assert_called_once()


def test_streamlit_script_invokes_only_local_application() -> None:
    """The script entrypoint exposes no legacy strategy compatibility API."""
    with patch("gui_calculator.app.main") as main:
        namespace = runpy.run_path(
            str(Path(__file__).with_name("main.py")), run_name="__main__"
        )
    main.assert_called_once_with()
    assert "backtest" not in namespace
    assert "add_anchored_vwap" not in namespace
