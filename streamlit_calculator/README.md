# Streamlit calculator

From the Koopec root, with Python 3.14, `uv`, and Cargo installed:

```sh
uv sync --locked
./calculator
```

Stop with Ctrl+C. The launcher passes arguments to Streamlit, for example
`./calculator --server.port 8502`. Koopec includes its Python dependencies
from the reference projects under [vendor](vendor/README.md) and resolves
third-party packages using its own lockfile.

The default archive is `../gex_downloads/tunnel_inputs.sqlite`, in the
`gex_downloads` directory beside Koopec. Set `GUI_CALCULATOR_ARCHIVE` or
enter a path in the UI to use a different archive.

The release-mode PyO3 extension serves the archive collection index, market
receipt reads and writes, online backups, and options snapshot and candle
persistence. It also handles strike exposure, wall ranks, max pain, Deribit
requests and chain normalization, Bitget data and momentum, Bybit OI page
parsing and momentum, and daily receipt and replay window selection.

Python provides Streamlit, HTTP transport, snapshot serialization, archive
merge and retention, SSH transfer, gamma-flip search, other analytics, and
strategy planning and execution.

## Tests

```sh
uv run --locked playwright install --with-deps chromium
./streamlit_calculator/test.sh
uv run --locked black --check .
uv run --locked ruff check .
uv run --locked basedpyright
```

The test script builds the native extension and runs Koopec's calculator,
shared-engine and real-Chromium tests. Browser traces and screenshots on failure,
and the chart renderer's executed-character coverage report, are under
`streamlit_calculator/test-results/`.

To exercise cross-project contract tests, set `KOOPEC_SERVER_ROOT` to the
directory containing `reference_bot` and `KOOPEC_AGGREGATOR_ROOT` to an
options aggregator checkout with its own locked `.venv`. The standard test run
skips the contracts whose external checkout is absent.
