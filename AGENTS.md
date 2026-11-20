# Project instructions

- Preserve the workspace configuration and keep Calculus deterministic and independent of network, system clocks, and exchange adapters.
- Run `cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace` before completing Rust changes.
- Maintain Rust test coverage strictly above 95% of executable lines across the workspace. Run `cargo llvm-cov --workspace --summary-only` and report the actual result and any setup limitation. A result of exactly 95% does not meet the requirement. Do not exclude production code or lower the threshold merely to pass.

## Test design

Apply ISTQB test principles and techniques proportionately to the change; do not claim ISTQB certification or standards compliance merely because these practices are followed.

- Derive tests from specified behavior and risk. Prioritize financial calculations, data integrity, invalid inputs, and other failures with significant consequences. Identify assumptions and missing requirements instead of inventing expected behavior.
- Use equivalence partitioning and boundary value analysis for meaningful input classes and limits. Include valid and invalid inputs and values immediately around important boundaries.
- Use decision tables for consequential combinations of conditions, and state-transition tests for stateful behavior, including invalid transitions and recovery where applicable. Preserve and verify chronological order and action precedence when they matter.
- Test observable outcomes and failure paths at appropriate unit, integration, and system boundaries. Use independently calculated examples or a trustworthy reference for expected results; avoid tests that merely repeat the implementation.
- Keep tests deterministic, isolated, repeatable, and independent of execution order. Control external dependencies at boundaries while exercising real components where integration behavior matters.
- Relate significant tests to the requirements or risks they cover, using descriptive names or concise documentation. Review and update tests as behavior and risks change; add regression tests for meaningful defects.
- Treat coverage as a way to identify untested code, not proof of correctness. Consider requirements, risks, and relevant input and state combinations alongside the required coverage measurement. Report failures and unverified behavior honestly.
