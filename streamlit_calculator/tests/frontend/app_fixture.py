# Copyright 2026 anchored-vwam-backtest contributors
"""Run the production UI with deterministic exchange boundaries only."""

import os
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from unittest.mock import patch

import pandas as pd
import streamlit as st
from snapshot_tunnel.bitget import Growth, LoanRate
from snapshot_tunnel.oi_divergence import InterestSample, MarketSample
from snapshot_tunnel.options_data import ChainObservation
from snapshot_tunnel.options_model import CandleClose, parse_snapshots

from gui_calculator.app import configure_page, main
from gui_calculator.bitget_margin import load_bitget_growth
from gui_calculator.candle_cache import (
    HistoricalCandleCache,
    load_cached_klines,
)
from gui_calculator.data_sources import CANDLE_COLUMNS
from gui_calculator.options_gex import EXAMPLE, render_options_gex
from gui_calculator.options_store import store_snapshot
from tests.frontend.archive_fixture import write_archive

if TYPE_CHECKING:
    import requests
    from snapshot_tunnel.bitget import Period
    from snapshot_tunnel.options_model import Snapshot

STAMP = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def candles(
    symbol: str, interval: str, *, start_ms: int, end_ms: int
) -> pd.DataFrame:
    """Supply bounded hourly OHLCV data at the exchange boundary.

    Returns:
        Deterministic candles for the requested history window.

    """
    if symbol in {"DOGEUSDT", "XRPUSDT"}:
        return child_candles(symbol, interval, start_ms=start_ms, end_ms=end_ms)
    if end_ms < int((STAMP - timedelta(days=2)).timestamp() * 1000):
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    times = pd.date_range(
        pd.Timestamp(start_ms, unit="ms", tz="UTC"),
        pd.Timestamp(end_ms, unit="ms", tz="UTC"),
        periods=48,
    )
    prices = [80000 + (index % 8 - 4) * 100 for index in range(len(times))]
    return pd.DataFrame({
        "time": times,
        "open": prices,
        "high": [price + 200 for price in prices],
        "low": [price - 200 for price in prices],
        "close": prices,
        "volume": [10] * len(times),
        "quote_asset_volume": [price * 10 for price in prices],
        "number_of_trades": [100] * len(times),
    })


def child_candles(
    symbol: str, interval: str, *, start_ms: int, end_ms: int
) -> pd.DataFrame:
    """Supply real-schema child prices aligned to the requested interval.

    Returns:
        Deterministic DOGE or XRP candles with independent prices.

    """
    cache = HistoricalCandleCache(
        Path(os.environ["GUI_CALCULATOR_BROWSER_CACHE"])
    )
    times = cache.load(
        exchange="bybit_linear",
        symbol="BTCUSDT",
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
    )["time"]
    base = 0.1 if symbol == "DOGEUSDT" else 1.0
    prices = [base * (1 + (index % 5) / 100) for index in range(len(times))]
    return pd.DataFrame({
        "time": times,
        "open": prices,
        "high": [price * 1.01 for price in prices],
        "low": [price * 0.99 for price in prices],
        "close": prices,
        "volume": [10] * len(times),
        "quote_asset_volume": [price * 10 for price in prices],
        "number_of_trades": [100] * len(times),
    })


def snapshot(
    session: requests.Session, *, asset: Literal["BTC", "ETH"]
) -> ChainObservation:
    """Supply a valid current options chain without persisting user data.

    Returns:
        A fresh chain with future expiries and an older options timestamp.

    """
    _ = session
    original = parse_snapshots(EXAMPLE)[0]
    current = replace(
        original,
        asset=asset,
        timestamp=STAMP - timedelta(hours=2),
        options=tuple(
            replace(option, expiry=STAMP + timedelta(days=7))
            for option in original.options
        ),
    )
    return ChainObservation(snapshot=current, observed_at=current.timestamp)


def growth(asset: str, *, period: Period) -> tuple[Growth, ...]:
    """Supply both positive and negative observations with sufficient warmup.

    Returns:
        Hourly or daily observations through the current hour.

    """
    step = timedelta(hours=1) if period == "24h" else timedelta(days=1)
    end = STAMP
    revision = f"fixture_growth_fetched_{asset}_{period}"
    if (
        st.query_params.get("growth_refresh") == "1"
        and revision not in st.session_state
    ):
        st.session_state[revision] = True
        end -= timedelta(hours=2)
    return tuple(
        Growth(timestamp=end - index * step, growth=1 if index % 5 else -2)
        for index in range(39, -1, -1)
    )


def prices(snapshot: Snapshot, *, days: int) -> tuple[CandleClose, ...]:
    """Supply completed candles aligned to each requested cutoff.

    Returns:
        Hourly prices ending at the previous completed hour.

    """
    end = snapshot.timestamp.replace(minute=0, second=0, microsecond=0)
    return tuple(
        CandleClose(timestamp=end - timedelta(hours=index), close=80000 + index)
        for index in range(days * 24, -1, -1)
    )


def oi_samples(snapshot: Snapshot, *, days: int) -> tuple[MarketSample, ...]:
    """Supply exchange observations on the same hourly price timeline.

    Returns:
        Snapshot-bounded positive OI and matching closes.

    """
    return tuple(
        MarketSample(
            interest=InterestSample(
                timestamp=point.timestamp, value=100 + index
            ),
            price=point.close,
        )
        for index, point in enumerate(prices(snapshot, days=days))
        if point.timestamp < snapshot.timestamp
    )


@st.cache_resource
def install_exchange_fixtures() -> ExitStack:
    """Retain deterministic boundaries during fragment-only reruns.

    Returns:
        Patch lifetime owned by this isolated browser-test server.

    """
    boundaries = ExitStack()
    history_path = Path(os.environ["GUI_CALCULATOR_BROWSER_CACHE"]).with_name(
        "options.sqlite"
    )
    original = parse_snapshots(EXAMPLE)[0]
    saved = replace(
        original,
        timestamp=STAMP - timedelta(hours=2),
        options=tuple(
            replace(option, expiry=STAMP + timedelta(days=7))
            for option in original.options
        ),
    )
    store_snapshot(
        saved, observed_at=saved.timestamp.isoformat(), path=history_path
    )
    archive_path = history_path.with_name("tunnel_inputs.sqlite")
    write_archive(archive_path, saved)
    os.environ["GUI_CALCULATOR_ARCHIVE"] = str(archive_path)

    patches = (
        patch(
            "gui_calculator.app.load_cached_klines",
            partial(
                load_cached_klines,
                cache=HistoricalCandleCache(
                    Path(os.environ["GUI_CALCULATOR_BROWSER_CACHE"])
                ),
            ),
        ),
        patch(
            "gui_calculator.child_assets.load_cached_klines",
            partial(
                load_cached_klines,
                cache=HistoricalCandleCache(
                    Path(os.environ["GUI_CALCULATOR_BROWSER_CACHE"])
                ),
            ),
        ),
        patch(
            "gui_calculator.child_assets.fetch_bybit_klines",
            side_effect=candles,
        ),
        patch(
            "gui_calculator.snapshot_dashboard.load_price_history",
            side_effect=prices,
        ),
        patch("gui_calculator.bitget_margin.fetch_growth", side_effect=growth),
        patch(
            "gui_calculator.snapshot_dashboard.load_snapshot_oi",
            side_effect=oi_samples,
        ),
        patch(
            "gui_calculator.snapshot_dashboard.saved_depth_history",
            return_value=(),
        ),
        patch("gui_calculator.app.fetch_bybit_klines", side_effect=candles),
        patch(
            "gui_calculator.snapshot_request_view.fetch_snapshot",
            side_effect=snapshot,
        ),
        patch("gui_calculator.snapshot_request_view.store_snapshot"),
        patch(
            "gui_calculator.bitget_view.load_price_history",
            side_effect=prices,
        ),
        patch(
            "gui_calculator.bitget_view.load_bitget_rate",
            return_value=LoanRate(timestamp=STAMP, daily=0.001, annual=0.365),
        ),
    )
    for boundary in patches:
        _ = boundaries.enter_context(boundary)
    return boundaries


_ = install_exchange_fixtures()
if "fixture_growth_initialized" not in st.session_state:
    load_bitget_growth.clear()
    st.session_state["fixture_growth_initialized"] = True
if st.query_params.get("analytics") == "1":
    configure_page()
    render_options_gex()
else:
    main()
