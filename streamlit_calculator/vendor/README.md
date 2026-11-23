# Python dependencies bundled with Koopec

These are local copies of the Python modules still exercised by the calculator.
They keep Koopec runnable from its own checkout while the Rust migration
continues.

- `shared/` and `check_bybit_time.py` came from the local anchored VWAM backtest
  checkout at `177e4102b51729264c06bd0498a1ed4bebd4051b`.
- `snapshot_tunnel/` and `market_storage/` came from the supplied
  `paper/server_bot` reference tree.

The local configuration defaults write inside Koopec. The optional server
contract tests can target a separate deployment checkout with
`KOOPEC_SERVER_ROOT`.
