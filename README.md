# Koopec

The Rust workspace is in `backend/`; the TypeScript starter frontend is in `frontend/`.

Run the API with `cd backend && cargo run -p http-api` (listens on `127.0.0.1:8000`). In a second terminal, run `cd frontend && corepack pnpm install --frozen-lockfile && corepack pnpm dev`. Vite proxies `/v1` requests to the API. The chart accepts local CSV files with `time,open,high,low,close` columns; timestamps are Unix seconds or ISO 8601. The options panel sends a snapshot JSON to the existing exposure endpoint.

The backend is a work in progress: dataset loading, candle services, backtests, and live trading are not implemented. See `backend/README.md` for the Rust workspace's current scope.
