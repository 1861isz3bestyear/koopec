# Koopec

Run the Streamlit calculator with `./calculator`. See
[streamlit_calculator](streamlit_calculator/README.md) for setup.

The Rust backend contains `calculus` for calculations, `archive` for local
archive access, `market-data` for exchange adapters, and `server-bot` for
order state. Through PyO3, the calculator uses these crates for BTC archive
coverage, strike exposure profiles, wall ranks, max pain, and public Bitget
lending data and momentum. The local Python dependencies under `streamlit_calculator/vendor/` still
provide archive payload loading, other analytics, and strategy replay.
