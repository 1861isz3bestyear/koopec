# Copyright 2026 anchored-vwam-backtest contributors
"""Exercise real local-archive replay, HTTP candles, SQLite and paper export."""

from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING

import pytest
from shared.paper_config import PaperBotConfig
from shared.tunnel_config import TUNNEL_MODE
from streamlit.testing.v1 import AppTest

from gui_calculator import app, data_sources
from gui_calculator.candle_cache import (
    HistoricalCandleCache,
    load_cached_klines,
)
from gui_calculator.test_app import settings as settings

if TYPE_CHECKING:
    from pathlib import Path

    from gui_calculator.settings import CalculatorSettings
    from tests.conftest import MarketHTTP

pytestmark = pytest.mark.e2e


def calculator_entrypoint() -> None:
    """Launch the production local-only calculator."""
    from gui_calculator.app import main

    main()


def test_complete_local_tunnel_calculation_and_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    market_http: MarketHTTP,
    *,
    settings: CalculatorSettings,
) -> None:
    """Preserve actual fills and equity through the single supported backend."""
    source = settings.local_archive
    assert source is not None
    offset = int(source.start.timestamp() * 1000) - market_http.start
    for row in market_http.rows:
        row[0] = str(int(row[0]) + offset)
    settings.interval = "1m"
    settings.fee_pct = 0.1
    settings.tunnel = replace(settings.tunnel, use_gex=False)
    monkeypatch.setattr(app, "render_sidebar", lambda: settings)
    monkeypatch.setattr(data_sources, "BYBIT_KLINES_URL", market_http.url)
    data_sources.fetch_bybit_klines.clear()
    monkeypatch.setattr(
        app,
        "load_cached_klines",
        partial(
            load_cached_klines,
            cache=HistoricalCandleCache(tmp_path / "candles.sqlite"),
        ),
    )
    destination = tmp_path / "paper.json"
    save = PaperBotConfig.save

    def save_config(config: PaperBotConfig) -> None:
        save(config, destination)

    monkeypatch.setattr(PaperBotConfig, "save", save_config)
    page = AppTest.from_function(
        calculator_entrypoint, default_timeout=30
    ).run()
    assert not page.exception
    assert not page.error
    assert (
        next(
            metric for metric in page.metric if metric.label == "Final equity"
        ).value
        == "1,017.96102000 USDT"
    )
    calls = len(market_http.requests)
    _ = (
        next(
            button
            for button in page.button
            if button.label == "Save paper bot config"
        )
        .click()
        .run()
    )
    assert not page.exception
    assert not page.error
    assert len(market_http.requests) == calls
    exported = PaperBotConfig.load(destination)
    assert exported.strategy_mode == TUNNEL_MODE
    assert exported.tunnel == settings.tunnel
    data_sources.fetch_bybit_klines.clear()
