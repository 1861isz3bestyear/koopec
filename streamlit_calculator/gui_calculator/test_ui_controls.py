# Copyright 2026 anchored-vwam-backtest contributors
"""Test ui controls."""

from __future__ import annotations

import pytest

from gui_calculator.data_sources import BYBIT_TICKERS, MEXC_TICKERS
from gui_calculator.ui_controls import normalize_order_size, ticker_options


def test_normalize_order_size_accepts_minimum_and_keeps_two_decimals() -> None:
    """Verify normalize order size accepts minimum and keeps two decimals."""
    assert normalize_order_size(0.01) == pytest.approx(0.01)
    assert normalize_order_size(1.239) == pytest.approx(1.24)


def test_normalize_order_size_rejects_less_than_one_cent() -> None:
    """Verify normalize order size rejects less than one cent."""
    with pytest.raises(ValueError, match=r"at least 0\.01"):
        _ = normalize_order_size(0.004)


def test_mexc_vet_ticker_maps_to_exchange_symbol() -> None:
    """Verify mexc vet ticker maps to exchange symbol."""
    assert MEXC_TICKERS["VET_USDT"] == "VETUSDT"


def test_bybit_ticker_options_map_to_exchange_symbols() -> None:
    """Verify bybit ticker options map to exchange symbols."""
    expected = {
        "BTC_USDT": "BTCUSDT",
        "XRP_USDT": "XRPUSDT",
        "DOGE_USDT": "DOGEUSDT",
        "ADA_USDT": "ADAUSDT",
        "TRX_USDT": "TRXUSDT",
        "LINK_USDT": "LINKUSDT",
        "AVAX_USDT": "AVAXUSDT",
        "DOT_USDT": "DOTUSDT",
        "TON_USDT": "TONUSDT",
        "NEAR_USDT": "NEARUSDT",
    }
    assert expected == BYBIT_TICKERS
    assert ticker_options("Bybit REST") == list(expected)


def test_non_exchange_sources_remain_btc_only() -> None:
    """Verify non exchange sources remain btc only."""
    assert ticker_options("Binance REST") == ["BTC_USDT"]
    assert ticker_options("Built-in sample") == ["BTC_USDT"]
