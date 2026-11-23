#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
backtest="$root/../backtest"
export UV_PROJECT_ENVIRONMENT="$root/.test-venv"
uv sync --locked --project "$backtest"
python="$UV_PROJECT_ENVIRONMENT/bin/python"
PYO3_PYTHON="$python" "$root/python/tests/run-native.sh"
cp "$root/python/koopec_calculus.pyi" "$root/python/target/python/koopec_calculus.pyi"
cd "$root/streamlit_calculator"
export COVERAGE_RCFILE="$backtest/pyproject.toml"
export PYTHONPATH="$root/python/target/python:$root/streamlit_calculator:$backtest${PYTHONPATH:+:$PYTHONPATH}"
exec "$python" -m pytest -c "$backtest/pyproject.toml" --cov-config "$backtest/pyproject.toml" gui_calculator tests "$backtest/shared" "$backtest/paper_trading_bot" "$@"
