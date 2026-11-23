use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::{collections::HashMap, path::Path};

/// Deterministic Deribit-shaped data, with OI expressed in underlying units.
pub(crate) fn example_payloads(spot: f64) -> HashMap<String, Value> {
    HashMap::from([
        (
            "instruments".into(),
            json!({"result": [{"instrument_name": "BTC-OPTION", "is_active": true,
                "base_currency": "BTC", "kind": "option", "option_type": "call",
                "expiration_timestamp": 1_795_003_200_000_i64, "strike": 100,
                "contract_size": 2}]}),
        ),
        (
            "options".into(),
            json!({"result": [{"instrument_name": "BTC-OPTION", "open_interest": 20,
                "mark_iv": 50}]}),
        ),
        ("spot".into(), json!({"result": {"index_price": spot}})),
    ])
}

/// Create two complete legacy collections in an isolated SQLite archive.
pub(crate) fn create_archive(path: &Path) {
    let db = Connection::open(path).unwrap();
    db.execute_batch("CREATE TABLE tunnel_inputs (id INTEGER PRIMARY KEY, asset TEXT, source TEXT, available_at TEXT, payload TEXT, error TEXT, collection_id TEXT)").unwrap();
    for (id, time, spot) in [
        ("older", "2026-11-09T12:00:02+00:00", 100.0),
        ("newer", "2026-11-09T12:05:02+00:00", 200.0),
    ] {
        for (source, payload) in example_payloads(spot) {
            db.execute(
                "INSERT INTO tunnel_inputs (asset,source,available_at,payload,error,collection_id) VALUES ('BTC',?1,?2,?3,'',?4)",
                params![source, time, payload.to_string(), id],
            ).unwrap();
        }
    }
}
