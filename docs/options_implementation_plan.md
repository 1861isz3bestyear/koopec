# Calculus options implementation plan

Status: planned, not implemented. This plan realizes chapters 5–6 and milestone M04 of `backtest/rust_calculus_migration_book_ru.md`. The canonical Python reference is `paper/server_bot/snapshot_tunnel/snapshot_tunnel/`, especially `options_model.py`, `gamma_search.py` and `option_levels.py`. Verify the exact revision and its consumers before using it as a baseline. `options_data.py` and `options_csv.py` describe external normalization and parsing; their transport and CSV responsibilities do not move into Calculus. `daily_gex.py` and snapshot selection belong to the later plans/strategy work.

## 0. Capture the baseline

1. Record revisions and dirty-tree status of backtest, paper and storage, Python dependency versions, configuration, source provenance, input files and valuation timestamps. A dirty baseline needs a content hash, not only a commit ID.
2. Save normalized input fixtures and Python outputs for individual exposure, strike aggregation, net/absolute exposure, ranked walls, flip search, candle revaluation and max pain. Record explicit units, model settings, input order, timestamps and missing/error reasons.
3. Include actual reference traces with puts/calls, multiple expiries, zero OI, expired contracts, ties, cancellation near zero, no flip and multiple flips. Record source behavior for invalid IV, expiry and empty chain before choosing a Rust API. Preserve outputs before changing Python.
4. Define per-output absolute and relative tolerances based on error analysis and representative fixtures; IDs, statuses, ordering, timestamps and selection decisions compare exactly. A tolerance cannot excuse a changed regime or root selection. Do not claim parity before fixture comparisons pass.

## 1. Workspace and typed boundary

Add `pub mod options;` to `crates/calculus/src/lib.rs` and implement `options/{mod,model,exposure,levels,flip,max_pain,error}.rs`; split further only when responsibilities warrant it. The module has no network, filesystem, system clock, pandas or SQLite. Callers supply valuation time and normalized data; Archive owns source-unit conversion, receipt provenance and transport.

Use private fields and fallible constructors for `OptionContract`, `OptionKind::{Call, Put}`, `OptionSnapshot` and model settings. Contracts carry an instrument/source identity, strike, expiry, IV as fraction, normalized OI and multiplier. A snapshot carries spot, contracts and explicit valuation/availability time; do not conflate observation, receipt and valuation. Distinguish raw contract-count OI from already-normalized base-asset OI with distinct input types or an explicit validated normalization contract, so the multiplier cannot be applied twice. Reject nonfinite inputs and invalid units at the boundary. Specify duplicate identity and deterministic ordering before implementation.

`Price` and `Money` in current `types` are decimal trading quantities, not a ready-made `f64` Greek input. Introduce a validated positive finite model price and explicit checked conversion at the boundary; never silently coerce invalid values to zero. Keep model `f64` arithmetic separate from exchange Decimal settlement. Evaluate whether `Micros` needs a validated Unix timestamp wrapper; do not use local time or call a clock.

## 2. Single-contract exposure

Implement pure `exposure(contract, valuation)` returning a typed contribution or a typed failure/status, not a sentinel. Follow the baseline's zero-rate Black–Scholes model: `T = (expiry - valued_at) / (365 * 86400)` seconds, `d1 = (ln(S/K) + 0.5 * iv^2 * T) / (iv * sqrt(T))`, gamma `phi(d1)/(S*iv*sqrt(T))`, and signed USD GEX for a 1% move `gamma * OI * multiplier * S^2 * 0.01`. Calls are positive and puts negative by project convention; this is not proof of dealer positioning. Apply multiplier exactly once. Preserve actual baseline handling of expired, zero-IV, zero-OI and invalid contracts; if a proposed contract differs, document and version the change rather than silently inventing defaults.

Tests: independently computed reference values for one call and one put, symmetric cancellation, doubling OI/multiplier, IV 50% represented as 0.5, expiry boundary, zero OI versus invalid data, zero/negative/nonfinite IV/spot/strike/multiplier and overflow. Specify a tested normal-density implementation and comparison tolerance; verify numerical behavior for extreme finite inputs.

## 3. Aggregate and rank strikes

Implement deterministic strike contributions, signed net and sum of absolute contributions as distinct named results. Specify stable input ordering, summation method and error handling; use a compensated method only after measuring its numerical and parity effects against Python. Do not silently change a near-zero sign or classification. Revalue a snapshot at a supplied candle-close time/spot without accepting information unavailable at that cutoff; preserve original snapshot provenance and filter expiry according to baseline behavior.

Rank call and put walls independently; return absent ranks as `Option`, never zero. Preserve Python's tie and sign semantics; the book requires smaller strike as tie breaker and inclusive range edges when the ±20% restriction is enabled. Configuration captures any optional range and is part of the calculation fingerprint. Keep max pain separate from GEX signals: for one expiry and usable OI, minimize intrinsic payout with the lowest strike breaking ties; return a reasoned absence for mixed expiry or zero OI as the baseline does.

Tests: unsorted contracts, duplicate policy, equal contributions, inclusive range boundaries and just-outside values, missing second wall, separate sides, net zero versus absolute nonzero, cancellation-sensitive input permutations, no valid contracts, revaluation at expiry and mixed expiry/max-pain ties. Compare numeric outputs to pinned Python fixtures.

## 4. Flip search and result contract

Translate `gamma_search.py` and the underlying curve evaluation with explicit immutable `FlipSearchConfig`: range, grid resolution, convergence tolerance, iteration limit and root selection/tie policy. Define typed result/status for roots, zero plateaus, no crossing in the configured range, invalid inputs, insufficient resolution and nonconvergence according to the source contract. Keep every root needed for deterministic selection; a missing root in the configured range is not a claim that no root exists elsewhere. Search settings and model version must contribute to the result fingerprint.

Tests: a known bracketed root, exact grid zero, zero plateau, no crossing, boundary roots, multiple roots and equal-distance ties, near-zero cancellation, malformed settings and forced nonconvergence. Check residuals and brackets against an independent mathematical reference as well as Python outputs. Evaluate refinement near expiry and extreme spot/IV; never hide NaN or infinity.

## 5. Integration and acceptance

Expose small named results such as `Exposure`, `StrikeExposure`, `RankedWalls` and `FlipResult`; use `Result` for invalid inputs and explicit status for valid but unavailable outputs. Positive/negative regime interpretation and 08:15 snapshot selection belong to plans/strategy and are separate from numerical exposure. Pin exact API signatures only after the baseline validates time, precision and absence semantics; avoid a public interface that assumes unspecified behavior.

Compare Rust and pinned Python event-by-event: contract contribution, ranked levels, root/status and selected outcome before final GEX or trading PnL. Exercise prefix/availability behavior and split inputs where relevant; identify the first divergence. Run the required formatter, Clippy, full workspace tests and `cargo llvm-cov --workspace --summary-only`; maintain strictly more than 95% executable-line coverage without exclusions. Assess risk-based test design, coverage and linting separately per `AGENTS.md`, and report any unavailable baseline or unresolved model policy. The feature is complete only when these checks and M04's agreed selector integration pass; this document does not claim those results.
