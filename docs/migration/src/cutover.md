# Cutover and Python retirement

## Rehearse

1. Build the native Axum binary and Dioxus assets from locked dependencies
   in clean CI. Package them together and run an archived GEX browser
   smoke test using the release artifact.
2. Run the full parity suite on pinned fixtures and verify both end-to-end
   exchange and archive compatibility at the relevant boundaries. Record
   actual results, coverage, missing peers and any unresolved differences.
3. Take a consistent SQLite backup with the existing archive tooling.
   Verify a restore on a separate copy and rehearse starting the previous
   release against that copy. For any schema change, prove old-reader
   compatibility or document restore and reconciliation before deployment.
4. Rehearse release startup with settings for archive paths, ports and
   exchange transports. Verify support for an existing archive and confirm
   collection and archive maintenance have one writer.

## Switch the launcher

Replace the implementation behind `./calculator` with the Rust release
launcher and document the supported command and configuration mapping.
Stop Python collection before starting Rust collection against the active
archive. Check UI readiness and archive coverage, run a read-only snapshot
selection and replay, then verify that new collections advance coverage
and can be read back. Use logs and persisted receipt timestamps to detect
stale, repeated or incomplete writes.

If cutover fails, stop the Rust writer first. Start the previous release
against a compatible archive or restore the verified backup. Account for
records written since the backup before restarting collection. Preserve
the written archive for reconciliation when restoration is necessary.

## Remove Python

After the accepted release and rollback rehearsal, remove the calculator's
Streamlit app and vendored runtime, Python launcher logic, PyO3 package and
bridge tests, Python-only build metadata, lockfile, and CI jobs. Verify
that fixtures extracted for parity remain consumable from Rust and the
browser harness. Replace the old coverage gates only when their measured
production source is retired and the replacement checks described in
[verification](verification.md) have passed. Keep the prior release and
its archive recovery instructions available as release artifacts.

The migration is complete when a clean environment without Python can
build the releases, run Rust checks and real-browser acceptance checks,
launch Koopec, open existing archives, ingest supported exchange data,
run the supported analytics and strategies, and complete backup, restore,
transfer and export workflows. Document the shipped native binary and web
assets, the exact supported formats and workflows, and the measured
verification results in the project README.
