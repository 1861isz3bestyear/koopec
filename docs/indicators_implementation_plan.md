# Calculus indicators implementation plan

Status: planned; no implementation or Python baseline is asserted by this document. This plan elaborates chapters 8–9, M05, and acceptance items K11–K12 of `backtest/rust_calculus_migration_book_ru.md`. It is a design and test plan, not a claim of migration parity or an instruction to change the existing Python sources.

## 1. Goal and scope

Build deterministic, transport-independent indicator calculations inside `calculus::indicators`, consuming validated market observations and producing typed, timestamped evidence. Support the current book, Bitget margin growth, and open-interest (OI) paths; preserve separate source histories and their availability. A caller supplies every observation and time. No clock, network, JSON/CSV parsing, database, exchange client, file access, or order execution belongs in Calculus.

The milestone is an indicator result that a future strategy can consume without looking ahead. The `strategy` module owns GEX-dependent OI mode selection, vote thresholds, freshness policy at entry, quorum, mandatory OI, and the final `EntryEvaluation`. `plans` owns plan and snapshot selection. Archive and adapters own exchange schema, source units, normalization, receipt provenance, and durable persistence. `replay` or a caller owns event ordering, checkpoint storage, and restart orchestration; indicators expose enough deterministic state to support these operations. Do not implement these other modules as implicit dependencies to make this milestone appear complete.

In particular, an OI indicator is not an option-chain OI calculation and does not prove trading direction by itself. A neutral calculated value, absent input, invalid input, warming up, a gap, and stale evidence must remain distinguishable. Do not turn failure into zero or use a neighboring source as a substitute.

## 2. Source inventory and baseline gate

Before implementation, inventory actual consumers and pin the relevant source contents and behavior; the paths below identify where to start, not an independently validated baseline:

| Responsibility | Candidate reference | Investigate |
| --- | --- | --- |
| Book composition | `paper/server_bot/snapshot_tunnel/snapshot_tunnel/tunnel_oscillators.py`, `order_book.py`, `tunnel_flow.py` | Notional units, input depth, invalid levels, empty sides, precision and how recorded votes are produced. |
| Margin growth | `snapshot_tunnel/bitget.py`, `tunnel_flow.py`, `archived_market.py` | `growth_momentum`, actual 24h growth field, rolling arithmetic, gap handling, ordering, receipt handling and thresholds. Distinguish 24h growth from annual loan rate and 30d growth. |
| OI | `snapshot_tunnel/oi_divergence.py`, `tunnel_flow.py`, `daily_flow.py`, `archived_market.py` | Raw base-asset OI, price pairing, 5-minute and hourly paths, momentum, pivots, comparison, state retention, gaps, timing and each consumer's settings. |
| Composition | `snapshot_tunnel/tunnel.py`, `tunnel_flow.py`, server bot consumers and their tests | Which numerical outputs are consumed, thresholds, fresh evidence selection, direction mapping, mandatory OI and mode choice; keep these strategy responsibilities separate. |
| Other indicators | Book appendix A and actual server consumers | Create a consumer-to-input-to-output inventory. Add only live, agreed responsibilities; do not assume these three streams exhaust all Calculus indicators or copy whole source files. |

For any future Python comparison, record repository commit IDs and dirty status; hash every dirty source and input file, record dependency versions, configuration, exchange/source provenance, unit conversions, timezone, receipt times, and fixture generation command. Freeze raw and normalized fixture inputs and reference outputs **before** modifying the reference. Capture output after each observation, including availability, state, reset, pivot indices and comparison reasons, not just final votes. Document exact/absolute/relative tolerances and why they are safe near a threshold. Compare state and decisions exactly where appropriate; never let numeric tolerance excuse a different trade, direction, pivot or selected observation. Report first divergence with input index and state.

Python fixture generation and parity checks are explicitly deferred by the current request. Implementers may use independently derived Rust test examples now, but must not claim source parity or M05 acceptance until the separately authorized baseline and event-by-event comparisons exist. Record unspecified or conflicting behavior as an open decision, rather than silently declaring a new default.

## 3. Design contracts and dependency direction

Proposed structure, subject to responsibility and actual consumers: `indicators/{mod,error,observation,book,margin,oi,momentum,pivots}.rs`. Split OI files only when each has coherent ownership; avoid a generic framework and placeholder public APIs. `indicators` may depend on `types`, but `types` must not depend on indicators; no dependency on strategy, archive, bot, HTTP, or execution. Cross-module contracts should use named public domain types with private fields and fallible constructors, and explicit model/policy versions when semantics change.

- Define or reuse a UTC Unix timestamp type and checked duration/interval arithmetic with explicit resolution. Record `observed_at`, actual `available_at`, and, for a derived pivot, `pivot_at` and `detected_at`; none means the same thing. Reject `available_at < observed_at` and arithmetic overflow. Specify event time versus receipt time for freshness rather than accidentally using a derived calculation's publication time.
- Require explicit instrument, venue/source identity and units where needed to prevent joining different markets. Define whether the timestamp represents a completed candle, snapshot, or interval boundary. Reject mixed source, asset, interval or units in a state instance unless a documented reset/new instance is requested.
- Represent model prices and quantities as positive, finite validated values; OI is explicitly base-asset quantity, not USD notional or contract count. Define zero quantity and empty side rules separately per source. Signed growth is finite and may be negative or zero. Use checked conversion at a Decimal/model-float boundary; never silently round into zero or substitute invalid input.
- Carry input identity/provenance and a calculation configuration or fingerprint sufficient to reproduce an output. Preserve original observation and receipt information through rolling calculations. Fingerprints must include the period, thresholds, interval, pivot policy, model version, normalization policy, and any rounding/summation choices; define canonical encoding before calling one a stable fingerprint.
- Expose explicit input errors separately from valid unavailable states. A useful state shape is `Unknown`, `WarmingUp { observed, required }`, `Ready(value)`, and `Gap { ... }`, but pin exact transitions and post-gap representation with the reference before stabilizing the API. Neutral `Ready` stays calculable. Do not represent several inconsistent states with unrelated optional fields.
- Define a small directional evidence type only if its meaning is shared, distinguishing `Long`, `Short`, `Neutral` and unavailable. Do not encode unknown as neutral, use numeric sentinels, or decide strategy quorum in indicator code.
- Choose immutable configuration types with validated closed enums for intervals, comparison modes, and pivot kind. Keep raw momentum and raw OI comparisons distinct. Reject unsupported settings, zero or negative durations, and nonfinite thresholds. Do not require callers to supply meaningless settings for an unrelated algorithm.

State transitions must be explicit and atomic: validate an entire new observation and any arithmetic before committing state. On an invalid or duplicate/out-of-order input, return a typed error and leave state unchanged. A valid but missing expected interval causes a documented gap/reset, not silent interpolation. Specify how same-time corrections, receipt reordering, source restarts, equal timestamps, and historical backfill are admitted: preserve data availability and never retroactively make a late observation usable in an earlier decision. Do not assume any policy without fixtures and consumer agreement.

## 4. Book indicator

### Contract

For validated levels, compute bid and ask quote notional independently: `bid = sum(price * quantity)` and `ask = sum(price * quantity)`. The rate is `100 * bid / (bid + ask)` in percentage points, not a fraction. Example: bid notional 600 and ask notional 400 yield 60. Values at 0 and 100 are possible if the agreed input contract permits a single empty side; both sides empty/zero yield an explicit unavailable/error outcome, never a confirmed 0. Preserve receipt/observation metadata.

Choose and document level validation (positive price, quantity domain, duplicates, order and depth); distinguish malformed books, a genuinely empty book and a valid one-sided book. Archive owns normalization from an exchange-specific depth representation. Use checked multiplication and accumulation; define summation and rounding against the eventual baseline. A nonfinite product, sum or result is an arithmetic failure. A quantity of zero and a negative quantity must be independently specified and tested. No indicator result may be produced by partially applying invalid levels.

### Tests

Use independently calculated examples for 600/400, balanced 50, bid-only 100 and ask-only 0 if allowed. Cover empty and zero-denominator books, negative/zero/nonfinite prices and quantities, duplicate levels under the chosen policy, large products and sum overflow, shuffled levels and sensitivity to accumulation order, timestamps and source mismatches. Check input immutability on error and exact units of output. Confirm an invalid newer book cannot be silently replaced by an older valid book when a consumer asks for latest evidence.

## 5. Margin growth momentum

### Contract

The current reference's `growth_momentum` uses a trailing window of **14 consecutive** signed growth observations. With `g_i` in the same source units, the calculated rate is `100 * sum(max(g_i, 0)) / sum(abs(g_i))`; an all-zero full window yields 50. The reference scales by the largest absolute growth before summation to reduce overflow. The `24h` source period uses one-hour observation steps; its name describes the source field, not a 24-hour sampling interval. The candidate reference also supports a daily step for its `30d` period; implement that only if the consumer inventory establishes it is required and model it as a different validated setting.

Thirteen hourly observations are warming up; the fourteenth is the first candidate result. Any missing or irregular expected hour breaks the consecutive run and requires a new full warmup. Duplicates and time reversal are input errors, not gaps. Validate the entire update before mutation. Define gap state and reset behavior explicitly, including whether the current post-gap observation counts as the first in the new run.

A derived result must not be available before every observation it actually depends on was received. The present reference `margin_votes` uses a cumulative maximum of receipts from the beginning of the input, not merely the current 14-value window. Verify intended behavior and version any change: a window-only maximum and cumulative maximum can differ after a late observation leaves the window. Capture both observation and receipt order. A newly received historical value must never generate an earlier available timestamp. Specify how corrections/replay are applied before offering online updates.

### Tests

Use explicit 14-value windows: all positive => 100, all negative => 0, all zero => 50, and e.g. seven +2 and seven -1 => 200/3. Test 13/14/15 samples and sliding-window replacement, one timestamp just short of and just beyond the expected hour, missing hour, full rewarm after a gap, duplicate/out-of-order rejection and unchanged state. Exercise alternating signs, extreme finite inputs, scaling behavior, nonfinite inputs, valid negative growth, delayed and out-of-order receipts, and an old observation published today. Compare incremental and one-batch results and every chunk split, including gap/reset points. Strategy tests later decide how a value maps to a directional threshold.

## 6. OI momentum and causal availability

### Input and formula

A market sample combines a positive finite base-asset OI observation and its matched positive finite price. Identify the actual price source, matching interval, close semantics, and how separately received inputs are joined; availability is no earlier than the latest required constituent receipt. The reference settings permit five-minute and hourly sampling; support only confirmed consumer configurations and do not infer source interval from UI display resolution.

For a 12-hour lookback and interval `Δ`, use `L = 12h / Δ` whole intervals. At index `i`, raw percentage growth is `100 * (OI_i / OI_(i-L) - 1)`; momentum is the mean of the three most recent raw growth values. At five-minute intervals `L = 144`: the first full result is zero-based index 146, after 147 consecutive observations. At hourly intervals `L = 12`, the corresponding first index is 14 (15 observations). A missing interval resets momentum, pivot history, and held evidence according to the separately specified state policy. Zero OI cannot be a divisor; the candidate `InterestSample` requires positive OI throughout. Detect ratio and accumulation overflow without publishing partial state.

The candidate reference `MomentumPoint.available` uses actual `received` if supplied, otherwise an assumed one-minute publication delay. In `oi_votes`, receipt is supplied for momentum but omitted for swing modes; later vote construction applies a cumulative receipt maximum. These are distinct behaviors and do not automatically establish that every intermediate pivot is causally timestamped. Do not invent a historical receipt for missing provenance. Record the discrepancy, pin the actual consumer behavior, and define/version a causal policy that takes the maximum availability of **all dependencies**, including late OI, matched price, smoothing window, pivot neighbors and any earlier evidence used in a comparison. Decide and document cumulative versus dependency-window maxima and correction semantics before claiming parity.

### Tests

Use a hand-calculated ramp where each of the three relevant ratios is known. Verify the first available indices 146 and 14 and values immediately before/after; constant OI => zero momentum. Test zero, negative, NaN and infinite OI or price, ratio overflow, exact interval, gap and recovery, duplicate/reversed time, and source/unit mismatches. Delay each of the oldest lookback point, a current point and paired price independently: the result cannot be available earlier than its latest dependency. Test ingestion and availability cutoff separately, equal-cutoff inclusion, and future receipts. Compare all prefixes, all chunk splits and state after rejected input; no signal may appear at an earlier cutoff when future data is appended.

## 7. Pivots, divergence and convergence

### Candidate source rules to validate

`oi_divergence.py` currently uses a five-point price window centered at `i` (two neighbors on either side). A strict high exceeds all four neighbors; a strict low is below all four. Prominence is the smaller of the left and right price excursions divided by the pivot price, in percent; equality at the configured threshold is accepted by the candidate code. No plateau qualifies. Its default minimum swing is 0.1 percent; its default minimum OI change is 0.05, with units depending on comparison mode.

The candidate finds an OI/oscillator extreme at center, one before or one after, with selection tie order center, previous, next. Raw-OI convergence additionally requires that selected OI be a strict local extreme against its adjacent samples. All five points require a ready momentum rate even in raw-OI mode in the candidate code. This may be surprising: record and test it rather than replacing it with an apparently simpler independent raw-OI warmup.

Compare each qualifying high only to the prior high, and low only to prior low. The candidate replaces the prior pivot with each qualifying pivot before assessing whether the comparison emits a signal. It requires a new outward price extreme, a nonzero oscillator change, and changes at or above the configured thresholds. Momentum comparison uses a difference in momentum percentage points; raw OI comparison uses percentage change in OI. A high with increasing OI measure or low with decreasing OI measure agrees; the opposite diverges. For directional evidence, divergence reverses price-swing direction; convergence follows it. A nonmatching regime clears the held direction in the relevant reference path. Preserve both modes independently; do not satisfy one with the other's evidence.

A center pivot cannot be detected before its second right-hand sample and the actual availability of every dependency. Keep pivot time, detection/event time, earliest usable time and source identity separate. Preserve the last qualifying state only under an explicit reference-backed hold policy; no previous signal, a neutral/opposite-regime signal, invalid input and a gap each have distinct effects. Gap resets previous high/low pivots and held state in the candidate series. Decide whether an error leaves previous state intact (recommended atomicity contract) versus a valid gap resetting it; test both.

### Tests

Construct minimal independent price/OI sequences for strict high and low, equal-price plateau, one side insufficient, prominence just below/equal/above threshold, and adjacent OI extreme at center/left/right including ties. Verify strict raw OI turning points and non-turning points. For both high and low, use a decision table over outward/inward/equal price, agreeing/opposing/equal oscillator, and below/equal/above both thresholds; verify divergence and convergence direction independently. Cover prior-high/low separation and the update of prior pivot even when a comparison emits nothing.

Assert the pivot is absent on each prefix before the second right point, appears only when all required data is available, and retains original `pivot_at`. Delay the right point, a matched OI neighbor and an older baseline point separately; ensure none leaks earlier. Verify all prefixes and split/restart state, signal hold, clear, gap reset and rewarm; convergence and divergence cannot substitute for one another. Test OI difference units and zero/nonfinite thresholds. Exercise multiple events at one availability time under a documented tie policy. Where source semantics remain disputed, preserve the failing/blocked case as an explicit unresolved requirement rather than assert invented behavior.

## 8. Integration boundary and strategy handoff

Expose each source's independently timestamped result, readiness/reason and applicable configuration. A future strategy should select evidence **as of a supplied decision cutoff**, not by wall clock. The latest available observation may be unavailable or stale; it must not fall back past a newer invalid/warming observation. Specify equality at the maximum-age boundary and whether age derives from observation or receipt with explicit tests. Strategy owns the thresholds and rule that, when GEX and OI confirmation are on, negative GEX selects convergence and positive GEX selects divergence; OI is then mandatory even when book and margin meet quorum. With GEX off, use the explicitly selected standalone mode; with OI off, OI cannot become a hidden filter.

Add integration tests only at real available boundaries: indicators must provide distinct results and timestamps for future strategy/replay. Do not introduce fake strategy, archive or exchange implementations merely to mark M05 complete. Once those modules exist, test every GEX sign × OI on/off × available/matching/opposing/missing/stale combination, independent book/margin quorum, cutoff equality, mode switch, gap, restart and late receipt. Confirm indicator results do not alter account state or create orders.

## 9. Implementation sequence and review gates

1. **Requirements and source review:** produce the consumer inventory and record the exact semantics, units, timing, supported intervals and unresolved policies above. Review risk partitions, independent expected results and state transitions before writing behavior. No Python fixture generation is required in this phase under the current deferral.
2. **Typed boundary:** add validated observations, identity, units, times, configuration, state and error contracts. Review causal and atomic failure behavior. Add validation and timestamp boundary tests first.
3. **Book:** implement pure notional calculation and independently derived test table. Specify accumulation and error behavior.
4. **Margin:** implement rolling state and gap/receipt handling; verify warmup, resets, prefixes and all chunk boundaries before optimization.
5. **OI momentum:** implement interval-aware lookback and smoothing with explicit availability dependency tracking. Verify 5-minute and hourly index boundaries and late arrivals.
6. **Pivots and modes:** implement pure pivot classification and comparison before stateful holding. Exercise the full decision tables, causal detection and independent mode states; audit source differences and version intentional changes.
7. **Handoff:** expose only the evidence and state needed by actual consumers. Test as-of behavior at the indicator/consumer boundary when the consumer exists. Leave strategy, selector and replay integration explicitly outstanding until implemented.
8. **Deferred baseline:** when authorized, capture pinned traces, compare every output and transition, resolve first differences, and document tolerances and intentional policy versions. Finish M05 only after the end-to-end strategy decisions and selected source agree under an approved contract.

## 10. Verification and acceptance

Apply the repository's `AGENTS.md` test design: equivalence partitions, boundary values, consequential decision tables and state transitions; independent numerical examples; deterministic isolated tests; invalid inputs, arithmetic failures and no partial mutation; chronological precedence and recovery; baseline comparisons when available. Explicitly review each requirement, risk, boundary, transition and expected result against tests. Coverage is a diagnostic, not evidence that the algorithm is correct.

After any repository modification, run from `koopec`: `cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D warnings`, `cargo test --workspace`, and `cargo llvm-cov --workspace --summary-only`. The last must report **strictly more than 95% executable lines across the workspace**; do not add exclusions or weaken thresholds. Applicable parent-project checks are `uv run black --check .`, `uv run ruff check .`, `uv run basedpyright`, and `uv run pytest` from the parent root. Report actual command outcomes and setup failures, not inferred passes. Respect any later user instruction that explicitly defers Python checks.

Report the three acceptance criteria independently: (1) risk-based tests and any unverified requirements, (2) actual executable-line coverage and threshold, and (3) formatter and lint results. Also report source revision/provenance, baseline/parity status, independent numerical tolerances, unresolved causality or normalization policies, and missing real integration. No implementation, documentation, passing test or coverage result alone establishes parity, complete M05, or trading correctness.
