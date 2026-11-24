# Migration phases

Each phase has a user-visible exit criterion. Keep the Streamlit launcher
available with its existing Python environment while Rust gains parity.
Where both apps run, use separate databases or run one as read-only.

## Source map

Paths under `gui_calculator/` and `vendor/` are relative to
`streamlit_calculator/`. Use this map to assign ownership in the work
ledger, then trace each entry point through its actual imports.

### Archived GEX (Phase 1)

**Source.** `local_archive_view.py`, `local_archive.py`, `archived_market.py`.

**Destination.** Dioxus archive controls, Axum archive endpoints, `archive`
reads.

### Exchange ingestion (Phase 2)

**Source.** `options_collector.py`, `options_source.py`, `options_candles.py`,
`candle_cache.py`, `live_oscillator_data.py`, `vendor/check_bybit_time.py`.

**Destination.** `market-data` transport and validation, server collection
workflow, `archive` persistence.

### Analytics (Phase 3)

**Source.** `gamma_search.py`, `oi_divergence.py`, `options_gex.py`,
`snapshot_analytics.py`, `vwam.py`, relevant `vendor/shared/` analytics.

**Destination.** `calculus` and Dioxus analysis screens.

### Charts (Phases 1, 3, 4)

**Source.** `charts.py`, `options_profile_chart.py`, `oscillator_dashboard/`,
other Plotly views.

**Destination.** Dioxus chart components, Plychart, Rust chart adapter.

### Strategy and replay (Phase 4)

**Source.** `app.py`, `daily_strategy.py`, `daily_plans.py`,
`tunnel_backtest.py`, `tunnel_plans.py`, `tunnel_replay.py`, relevant
`vendor/snapshot_tunnel/` and `vendor/shared/` execution paths.

**Destination.** Native strategy and replay logic, Axum workflow, Dioxus
results.

### Archive maintenance and settings (Phase 5)

**Source.** `vendor/market_storage/`, `archive_export.py`,
`vendor/snapshot_tunnel/options_csv.py`, `settings.py`, `ui_controls.py`.

**Destination.** `archive`, native maintenance CLI, server configuration and
Dioxus settings.

### Release and test tooling (Phase 6)

**Source.** `calculator`, `python/`, Python test and packaging entry points.

**Destination.** Rust release launcher, native and Chromium checks, removal of
transitional Python tooling.

## 0. Capture the baseline

Pin the Koopec commit and available external reference revisions. Record
the supported settings, workflows, archive schema, sample exports and
defaults. Capture deterministic raw exchange payloads, de-identified
archives, and intermediate strategy traces before editing the behavior.
Inventory optional contracts using `KOOPEC_SERVER_ROOT` and
`KOOPEC_AGGREGATOR_ROOT`. An unavailable peer leaves a named verification
gap until the contract can be exercised against a pinned peer.

**Exit:** Every callable Python surface has a migration or retirement entry,
and representative fixtures can reproduce the current launcher results.

## 1. Ship read-only archived GEX

Add the Axum server, shared wire types, typed API client, and Dioxus app.
Call the existing archive and calculus crates directly. Deliver archive
selection and coverage, history loading, latest and selected receipt
profiles, and the first Plychart integration. Move archive version checks
out of Streamlit's cache and into the Rust read and response path. Use
existing SQLite data without a schema change for this slice.

### Archive consistency and history

Trace the existing Streamlit archive path override, source toggle, status,
coverage and refresh behavior. Inventory the supported SQLite layouts against
`archive/src/local_archive.rs` under `backend/crates/`. Capture outputs from
the existing calculator with multiple complete collections per day,
incomplete collections and independent market receipts.

Group each Rust archive read in a consistent read-only SQLite transaction.
Check the expected archive version before and after the read, including
index reads and early empty results. A filesystem fingerprint can help
detect replacement while an open SQLite connection still references the old
file. If using the existing nanosecond modification time and size, document
that identical fingerprints can miss replacement and that a main-file
fingerprint alone cannot track WAL commits. Include a persisted generation
or another validated change token where needed. Keep the version alongside
the archive ID in cache keys. Map a stale version to a refresh outcome and
give unreadable and empty archives distinct UI states.

Reuse the batched `gex_history` implementation. Retain one chronological
row for each complete BTC collection and preserve actual receipt identity,
spot, expiry filtering and valuation. Apply optional distance only to wall
ranking. Map the current `time`, `options_price`, `options_gex`,
`options_call_gex`, `options_put_gex`, `options_absolute_gex`,
`options_gamma_flip`, `options_call_1`, `options_call_2`,
`options_put_1`, `options_put_2` and `options_gex_time` columns to named
wire fields. Preserve UTC microsecond precision and missing flips and wall
ranks. Apply the chart visibility window after retrieving history as the
existing caller does. Dioxus replaces the DataFrame adapter and load spinner.

Resolve a profile cutoff to the latest complete available collection at or
before the cutoff. Select the receipt ID before decoding the payload and
record the current tie ordering from a fixture. Validate the exact selected
collection and compare its price fields and contract set with
`archive_export.archived_snapshot`. The snapshot reader supplies profile and
replay inputs, and the scalar history builder applies its own valuation and
expiry rules. Keep existing PyO3 signatures during coexistence and build the
reference extension with the locked Python interpreter when comparing results.

**Exit:** HTTP tests and Chromium exercise one fixture from archive
selection to the exact strike profile. Reloading after an archive change
shows coherent data. Clicking receipts after pan and zoom works.

## 2. Move exchange ingestion and persistence

Inventory actual Deribit, Bybit and Bitget endpoints and candle sources,
including WebSocket subscribe and reconnect behavior where used. Reuse
Rust parsers and clients where present. Port Python transport, candle
fetching, time checks, scheduled refresh, and collection state. Validate
external payloads before converting them to domain types. Preserve UTC,
units, receipt IDs, pairing and completeness semantics. Keep snapshots,
depth, OI, margin, and candles coherent through retries and partial feeds.
Use bounded timeouts and distinguish stale values from current values.
Reuse the archive crate for atomic writes and make collection replay
idempotent using the existing storage identity where applicable.

**Exit:** Deterministic exchange fixtures drive the real Rust collection
path and an existing archive can be read and extended. Tests exercise
malformed data, partial collection, repeated receipt, disconnect and
recovery. Users can inspect live and archived data from Dioxus.

## 3. Complete analytics and chart parity

Port the Python analytics actually reachable from dashboard and strategy
entry points. Start with gamma-flip search, divergence, then remaining
VWAM, volume-profile, leverage, child-asset, expiry, snapshot balance and
comparison paths as identified by the ledger. Reuse Rust implementations
where they already exist and move table and export formatting to
boundaries. Preserve signed GEX, missing observations, warmup windows,
matching direction and tolerances, and causal cutoff rules.

Port the corresponding snapshot/history, daily comparisons, live
oscillators, expiry and analytics screens. Use Plychart for supported
series. Implement gap rendering, hover, overlays and any other verified
feature gaps in the Rust chart adapter. Replace the existing oscillator
renderer after its interaction and accessibility contract passes.

### Recorded archive oscillators

Trace `calculate_oscillators` and the current archive loader in the
vendored `snapshot_tunnel/archived_market.py` and `local_archive.py`.
Use the selected BTC window and the `DEPTH`, `GROWTH_HOURLY`, `OI` and
`TICKER` source set. Preserve inclusive hourly chunk endpoints and the
microsecond advance into the next chunk. Verify there are no dropped or
repeated boundary receipts. Preserve causal matching to market and OI
samples, warmup, gaps and stale evidence. Return typed independent streams
and verify which streams feed margin and order-book charts and replay.

**Exit:** Independent examples and pinned fixtures match across numeric
and temporal boundaries. All analytics screens pass their browser
acceptance tests, including the migrated oscillator.

## 4. Port strategies and execution

Port daily and tunnel replay in slices. Move settings and mode validation,
plan construction, confirmations, ordered decisions, execution, and
reporting in that order. Inventory vendored spot, book, hedge and
child-asset behavior and the primary backtester and bot configuration
screens. Reuse existing Rust selection, confirmation and wall operations.
Use typed decisions and positions, then apply mutations through one
account owner. Keep simulated fills separate from any existing order-state
integration. Preserve how data availability, fees, rounding and
simultaneous conditions affect what happens first.

### Daily archive chains for replay

Reuse the complete-collection index and the Rust selection behind
`daily_receipts`. Select at most one complete collection per UTC day,
nearest 08:15 UTC, with the earlier time winning an equal-distance tie.
Select IDs before reading payloads and preserve actual receipt time,
normalized contract data and identity. Compare this path with the vendored
`load_archive_snapshots` separately from the chart cutoff loader. Trace
remaining vendored callers before retiring their wrappers and exercise the
external paper bot contract as a peer integration.

**Exit:** For supported settings, a Rust replay produces the same ordered
plans, fills, position transitions, trades, balances and equity as the
reference traces within agreed tolerances. The Dioxus workflow can run
the replay and display its outputs and errors.

## 5. Finish archive operations, exports and settings

Move the remaining maintenance entry points to a Rust CLI or existing
native service according to who invokes them. Reuse Rust backup, audit,
merge, and ordinary retention. Port download and authenticated SSH
transfer, checksum or receipt verification where the existing contract
requires it, and acknowledged-copy retention. Preserve support for
existing SQLite files and export contracts, including columns, ordering,
UTC formatting and missing values. Map current configuration inputs and
defaults to the Rust launcher, CLI and Dioxus UI. Keep controls for
product workflows that are currently present, including archive refresh
and the existing backtest settings.

**Exit:** Fixture archives can be opened, backed up, restored, exported,
merged and transferred through the supported interfaces. A failed or
unacknowledged transfer cannot trigger the acknowledged-copy deletion
path. A restore drill succeeds before changing the production launcher.

## 6. Cut over and remove Python

Use the [cutover checklist](cutover.md). Replace migration-time reference
tools with pinned fixtures and native or browser checks. Remove the
Python application and bridge only after Rust passes all accepted
workflow and compatibility gates.
