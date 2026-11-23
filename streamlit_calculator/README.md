# Streamlit calculator

This is a copy of the GUI Calculator from the sibling `backtest` project. It
uses that project's Python environment and shared modules, so keep `backtest`
next to `koopec` and install its locked dependencies with `uv sync --locked`
in `backtest`.

From the `koopec` directory, start the calculator with:

```sh
./calculator
```

Stop it with Ctrl+C. Additional arguments are passed to Streamlit, for
example `./calculator --server.port 8502`. The launcher requires `cargo` and `uv`.

The default local archive is `../gex_downloads/tunnel_inputs.sqlite` relative
to the workspace containing `koopec`.

Selected options-profile strike exposures are calculated in-process by a PyO3 extension using the Rust calculus crate. The launcher builds the extension in release mode. The extension currently uses whole-second timestamps and is not yet the backtest engine. The
archive reader, strategy replay, backtests, and other calculations still use
Python code from the reference project. This is not yet a complete migration to
the Rust backend; it requires the sibling Python project to run.

## Tests and CI

Run `./streamlit_calculator/test.sh` from Koopec to build the extension and run
the copied GUI, shared-engine, and real-Chromium tests with the backtest lock
file. It creates `.test-venv` in Koopec. Install Chromium and its system libraries once, from Koopec:

```sh
UV_PROJECT_ENVIRONMENT="$PWD/.test-venv" uv run --locked --project ../backtest \
  playwright install --with-deps chromium
```

The run retains browser failure traces and screenshots and writes the JavaScript
executed-character coverage report under `streamlit_calculator/test-results/`.

GitHub Actions needs repository variables `BACKTEST_REPOSITORY` and
`MARGIN_OSCILLATOR_REPOSITORY` in `owner/name` form. Optional `BACKTEST_REF`,
`PAPER_REF`, and `MARGIN_OSCILLATOR_REF` select revisions; pin them to tested
commits for reproducibility. The paper repository is
`1861isz3bestyear/paper_reference_bot`. For private dependencies, provide a
`KOOPEC_DEPENDENCIES_TOKEN` secret with read access. These checkouts must contain
the same sibling packages and compatible lockfile used locally.
