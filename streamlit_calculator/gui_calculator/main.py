# Copyright 2026 anchored-vwam-backtest contributors
"""Streamlit entry point for the local-archive Snapshot tunnel backtester."""

import sys
from pathlib import Path

# Streamlit executes this file as a script and places gui_calculator/, rather
# than the repository root, on sys.path. Add the root before importing the
# package so the documented `streamlit run gui_calculator/main.py` command
# works reliably.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gui_calculator.app import main

if __name__ == "__main__":
    main()
