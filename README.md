# Koopec

Run the Streamlit calculator with `./calculator`. See
[streamlit_calculator](streamlit_calculator/README.md) for setup.

The Rust backend contains `calculus` for calculations, `archive` for local
archive access, `market-data` for exchange adapters, and `server-bot` for
order state. Through PyO3, the calculator uses these crates for BTC archive
coverage and payload reads, snapshot and candle persistence, strike exposure
profiles, wall ranks, max pain, Deribit requests and chain normalization, and
public Bitget lending data and momentum. The local Python dependencies under
`streamlit_calculator/vendor/` still provide archive maintenance and SSH
transfer, other analytics, and strategy replay.

See the [full-stack Rust migration book](docs/migration/src/SUMMARY.md) for
the Axum, Dioxus, and Plychart migration plan.
