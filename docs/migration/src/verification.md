# Parity and verification

Define expected results from requirements, independently calculated
examples, and pinned reference traces before porting. Where Python and an
independent example disagree, record the discrepancy and decide the
intended behavior explicitly. Freeze the clock and fixture inputs.
Compare exact identifiers, timestamps, missingness, ordering, and state
transitions. Define unit-specific absolute and relative tolerances for
floating-point outputs before comparing them.

- **Archive lookahead.** A cutoff at a receipt includes that receipt. A cutoff
  between receipts uses the earlier complete receipt. A cutoff before the
  first complete receipt yields no profile.
- **Receipt boundaries.** Distinct same-day receipts remain distinct. Test
  daily selection immediately around 08:15 UTC, a tie, and a date rollover
  against the reference. A contract expiring at valuation time is excluded
  where the archive contract specifies it.
- **Archived history.** Use multiple complete collections on one day and a
  fixture with incomplete collections. Verify chronological receipt identity,
  strike rank, both exposure signs, missing flip and walls, and on/off wall
  distance against independently valued examples.
- **Recorded oscillators.** Exercise hourly sample boundaries, future or
  missing matching samples and incomplete warmup. Compare missingness, causal
  votes and receipt identity in both chart and replay consumers.
- **Archive replacement.** Replace the archive between reads. An old version
  is rejected or refreshed according to the API contract. A single screen
  never combines mismatched versions.
- **Live-data recovery.** Send duplicate, malformed, missing, and out-of-order
  observations, then reconnect. Confirm accepted data, stale state and receipt
  counts against the contract.
- **Strategy precedence.** Use a decision table for competing exit, entry and
  confirmation conditions. Compare the full ordered trace. Include long and
  short profit and loss, fees, rounding, and failed arithmetic with no partial
  mutation.
- **Transfer retention.** Exercise interruption, verification failure and
  retry. Deletion requires the expected acknowledged state. Confirm archive
  integrity by opening the restored copy.
- **Chart mapping.** Select a known receipt before and after zoom or pan, with
  gaps and on a resized high-DPI canvas. The displayed receipt and causal
  hover values match the fixture. Reset restores the original chart pixels and
  clears its tooltip.

Start with the existing archive and calculus tests and
`streamlit_calculator/gui_calculator/test_observed_history.py`. Test
invalid archives, empty complete indexes, independent size and
modification-time changes, and cache reuse after refresh. Coordinate file
replacement in tests with synchronization. Exercise the actual launcher and
fixture in Chromium when switching each consumer.

## Gates during transition

- Run the backend's format, Clippy with warnings denied, workspace tests,
  and `cargo llvm-cov --workspace --summary-only`. Preserve the requirement
  of strictly above 95% executable-line coverage and the current CI
  threshold. Cover handlers, adapters and storage failure paths alongside
  pure calculations.
- Keep the locked Python format, lint, type, and full pytest gates while
  Python ships. Use the pytest configuration in `pyproject.toml`
  for measured scope, including `snapshot_tunnel`, and preserve the minimum
  92% line/branch gate. Keep the 92% V8 executed-character gate for the
  production oscillator `chart.js` while it ships. Preserve its handling
  of unexecuted nested ranges and its coverage report.
- Build the actual Dioxus WASM target and exercise the production Axum +
  Dioxus application in real Chromium. Keep browser runs isolated and
  deterministic. Assert readiness through locators. Fail on uncaught
  errors, console errors, failed requests, HTTP errors in normal
  workflows, and unexpected external requests. Explicitly assert HTTP
  errors in scenarios designed to exercise them. Retain screenshots and
  traces on failures.
- Carry over the existing axe WCAG A, AA, and AAA audits and independent
  7:1 Canvas text contrast checks. Exercise light and dark backgrounds,
  phone and desktop layouts, horizontal overflow, empty and single
  observations, gaps, margin and limit-order data, keyboard focus, and
  zoom, pan and reset. Include the low-contrast regression. Report
  accessibility results as automated checks.

When a transitional PyO3 adapter changes, run its native checks with the
locked interpreter. Run the existing launcher against the fixture and use
the repository test script to rebuild the extension for the Python suite.

```sh
uv sync --locked
export PYO3_PYTHON="$(uv run --locked python -c 'import sys; print(sys.executable)')"
cargo fmt --manifest-path python/Cargo.toml --all --check
cargo clippy --manifest-path python/Cargo.toml --all-targets -- -D warnings
uv run --locked playwright install --with-deps chromium
./streamlit_calculator/test.sh
```

## Gates after migration

Move the browser harness to a Python-free Chromium runner before removing
pytest. A Node Playwright harness is an option for test tooling. Browser
test tooling can use JavaScript or TypeScript while production application
and chart behavior stay in Rust. Cover the web workspace's shared
contracts, client, and Rust chart adapter, including pure viewport and
selection logic in native tests where possible and the WASM path in
Chromium.

The V8 gate measures executed JavaScript characters and cannot verify a
replacement Rust renderer. Before retiring that gate with its source,
document the replacement measurement and source scope, validate the
instrumentation on the actual Rust/WASM renderer and demonstrate that
it detects unexecuted code. Keep the browser behavior and accessibility
checks through the replacement. A passing native suite alone leaves
browser execution unverified. Record any unresolved tooling gap before
cutover.
