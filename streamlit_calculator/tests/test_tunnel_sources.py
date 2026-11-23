# Copyright 2026 anchored-vwam-backtest contributors
"""Require a local archive at the calculator's backend boundary."""

import pytest

from gui_calculator.app import load_tunnel_history
from gui_calculator.settings import CalculatorSettings


def test_missing_local_archive_has_no_live_or_csv_fallback() -> None:
    """Explicitly reject runs without the sole supported data source."""
    with pytest.raises(ValueError, match="local GEX archive"):
        _ = load_tunnel_history(CalculatorSettings())
