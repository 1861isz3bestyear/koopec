#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export UV_PROJECT_ENVIRONMENT="$root/.test-venv"
export PYTHONDONTWRITEBYTECODE=1
uv sync --locked --project "$root"
python="$UV_PROJECT_ENVIRONMENT/bin/python"
PYO3_PYTHON="$python" "$root/python/tests/run-native.sh"
cp "$root/python/koopec_calculus.pyi" "$root/python/target/python/koopec_calculus.pyi"
cd "$root/streamlit_calculator"
export COVERAGE_RCFILE="$root/pyproject.toml"
export PYTHONPATH="$root/python/target/python:$root/streamlit_calculator:$root/streamlit_calculator/vendor"
exec "$python" -m pytest -c "$root/pyproject.toml" "$@"
