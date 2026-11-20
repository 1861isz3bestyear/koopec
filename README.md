# Koopec

This workspace reconstructs the supplied Calculus excerpt. The original root workspace manifest and unspecified module implementations were not provided; the root configuration is minimal and the omitted modules are not invented.

`Price` and `Quantity` accept at most eight input decimal places. `Money` accepts exactly representable nonnegative decimal inputs with up to 28 fractional places; values exceeding Decimal’s range or precision are rejected. Calculated `Money` can have greater scale than price or quantity; no exchange rounding policy has yet been selected. Signed PnL requires a separate future type. The in-memory journal publishes complete monotonically numbered batches and rejects duplicate IDs and corrections to missing observations; its commit sequence is not a substitute for transactional durable storage. The exchange clock policy belongs in the future Server Bot adapter.

The `accounts` module implements a preliminary historical, full-allocation account with long/short settlement and read-only mark. Entry and exit prices must already include simulated slippage. Quantity division rounds to 16 decimal places, and intermediate multiplication rejects unrepresentable products; this precision policy must be compared against the pinned Python baseline before declaring parity. Funding, partial fills, actual exchange fees, child accounts, durable fill deduplication and live Bybit wallet accounting are not implemented. This model is not a live execution ledger.

The `execution` simulator supports ordered opening/completed events, stop and explicit capped target protection, entry-bar stop priority and simulated slippage. Entry decisions are assumed executable at their supplied reference price; order triggering and strategy decisions are caller responsibilities. Slipped prices are rounded to eight decimal places. Session/backtest finalization, replay checkpoints, duplicate fill handling and comparison with pinned Python event traces remain unimplemented. Only sequential one-candle-at-a-time processing is supported.

The proposed Rust options work is described in [the options implementation plan](docs/options_implementation_plan.md).
