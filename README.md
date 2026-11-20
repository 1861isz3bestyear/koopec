# Koopec

This workspace reconstructs the supplied Calculus excerpt. The original root workspace manifest and unspecified module implementations were not provided; the root configuration is minimal and the omitted modules are not invented.

`Price` and `Quantity` accept at most eight input decimal places. `Money` accepts exactly representable nonnegative decimal inputs with up to 28 fractional places; values exceeding Decimal’s range or precision are rejected. Calculated `Money` can have greater scale than price or quantity; no exchange rounding policy has yet been selected. Signed PnL requires a separate future type. The in-memory journal publishes complete monotonically numbered batches and rejects duplicate IDs and corrections to missing observations; its commit sequence is not a substitute for transactional durable storage. The exchange clock policy belongs in the future Server Bot adapter.
