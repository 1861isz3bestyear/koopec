# Koopec

Run the Streamlit calculator with `./calculator`. See
[streamlit_calculator](streamlit_calculator/README.md) for setup.

The Rust backend contains `calculus` for calculations, `archive` for local
archive access, `market-data` for exchange data, and `server-bot` for the
future bot. The calculator migration is incomplete: its selected options
profile uses Rust, while archive loading, strategy replay and other calculations
still use the sibling Python reference project. The Rust archive reader is not
yet connected to the calculator.
