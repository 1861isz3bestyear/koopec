# Goal and current system

Koopec will ship as an Axum service and a Dioxus web app compiled to
WebAssembly, with Plychart for browser charts. A fresh checkout of the final
project can build, test, and launch Koopec without a Python interpreter,
Streamlit, PyO3, or Python packages. Browser tooling and Rust-generated
JavaScript bindings are part of the web build. This book proposes changes
and defines their acceptance criteria.

Build the book with `mdbook build docs/migration` from the Koopec root. The
[table of contents](SUMMARY.md) also works when browsing the Markdown source.

## Starting point

### Archive

**Already in Rust.** SQLite indexing and payload reads, receipts, snapshots
and candles, online backup, ordinary retention, audit and merge, archived GEX
history.

**To migrate.** Archive selection and cache coordination, CSV, download and
SSH transport, acknowledged-copy retention, maintenance commands and UI.

### Market data

**Already in Rust.** Deribit requests and chain normalization, Bitget lending
data and momentum, Bybit depth and OI parsing.

**To migrate.** HTTP and WebSocket transport still used by the calculator,
candle feeds, refresh and collection orchestration, Python validation
adapters.

### Analytics

**Already in Rust.** Strike exposure profiles, walls, max pain, archived GEX,
book and OI oscillators.

**To migrate.** Gamma-flip search paths still in Python, OI divergence, and
remaining snapshot, GEX, volume-profile, VWAM and related analytics.

### Strategies

**Already in Rust.** Daily and active replay selection, positive-GEX wall
decisions, confirmation gate, separate order-state crate.

**To migrate.** Daily and tunnel plan assembly, fills and account execution,
trade and equity results, remaining spot, hedge and book-execution logic.

### Product

**Already in Rust.** PyO3 provides native calls to the current app.

**To migrate.** Streamlit settings, workflows, charts and exports, Plotly
views, standalone oscillator Canvas renderer, Python browser and contract
harnesses.

Trace ownership using these paths from the Koopec root:

- `streamlit_calculator/README.md` for launcher and runtime behavior.
- `streamlit_calculator/vendor/README.md` for the bundled Python sources.
- `python/koopec_calculus.pyi` for the PyO3 interface.

Some feature names span both languages. Inspect the actual
entry point and its fallback paths before estimating a port. The vendored
modules are local reference implementations. External bot and aggregator
deployments are integration peers.

## Work ledger

Before porting a surface, record its launch path or UI control, Python and
Rust call sites, fixtures and data formats, contract owner, expected results,
and the Rust acceptance test that will replace it. Assign each reachable
Python path to a phase in this book. For unused modules, record the evidence
for retirement. Trace CLI entry points, dynamic imports, fallback paths,
and optional external contracts as well as direct imports.

Open product decisions include archive selection on remote hosts, supported
exchange and deployment modes, and distribution targets beyond those already
tested. The plan starts with a local, single-user deployment and preserves
existing behavior where fixtures and contracts establish it.
