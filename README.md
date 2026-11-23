# Koopec

Run the API with `cd backend && cargo run -p http-api` (listens on `127.0.0.1:8000`). In a second terminal, run `cd frontend && corepack pnpm install --frozen-lockfile && corepack pnpm dev`. Vite proxies `/v1` requests to the API. The chart accepts local CSV files with `time,open,high,low,close` columns; timestamps are Unix seconds or ISO 8601. The options panel sends a snapshot JSON to the exposure endpoint, which returns GEX, ranked call and put walls within 20% of spot, and max pain with a reason when unavailable. Contracts expired at the valuation time are excluded from those results.

The backend is a work in progress: dataset loading, candle services, backtests, and live trading are not implemented. See `backend/README.md` for the Rust workspace's current scope.

To load local options data, click **Load local GEX archive** in the frontend.
Koopec reads `../gex_downloads/tunnel_inputs.sqlite` relative to this checkout,
lists complete BTC options collections, and calculates the latest collection.
Use the receipt-time selector to view another collection. Enter a different
SQLite file path in the sidebar, or set `GUI_CALCULATOR_ARCHIVE` when starting
the API to change the default. The archive is opened read-only; `.sqlite.gz` files must first be
unpacked or consolidated separately.

The selector loads one options chain at a time; it does not yet load the
archive's order-book, margin, or open-interest streams or run a backtest.
The current options API uses whole seconds, so fractional receipt times are
rounded forward to avoid using information before it was available.

Run the separate Streamlit calculator with `./calculator` from this directory.
See [streamlit_calculator](streamlit_calculator/README.md) for setup details. It connects its
selected options-profile exposure calculations to Rust through PyO3; strategy replay
and other calculations still use the sibling Python `backtest` project.
