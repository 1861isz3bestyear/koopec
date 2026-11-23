use super::{ArchiveError, collections, normalized_chain, payloads, tables};
use calculus::gex::{aggregate, observed_flip, ranked_walls};
use calculus::options::{
    IdentifiedContract, OptionContract, OptionKind, OptionSnapshot, Valuation,
};
use chrono::DateTime;
use market_data::deribit;
use rusqlite::{Connection, OpenFlags};
use std::{path::Path, thread};

/// One receipt-time chart row, with unavailable flips and ranks represented explicitly.
pub struct GexHistoryRow {
    pub receipt_us: i64,
    pub spot: f64,
    pub net: f64,
    pub call: f64,
    pub put: f64,
    pub absolute: f64,
    pub flip: Option<f64>,
    pub calls: [Option<f64>; 2],
    pub puts: [Option<f64>; 2],
}

fn contract(item: deribit::Contract) -> Result<IdentifiedContract, ArchiveError> {
    let side = match item.side {
        deribit::Side::Call => OptionKind::Call,
        deribit::Side::Put => OptionKind::Put,
    };
    let contract = OptionContract::new(
        side,
        item.strike,
        item.expiry_ms * 1000,
        item.iv,
        item.open_interest,
        item.multiplier,
    )
    .map_err(|_| ArchiveError::Invalid)?;
    IdentifiedContract::new(item.instrument, contract).map_err(|_| ArchiveError::Invalid)
}

fn row(
    receipt_us: i64,
    spot: f64,
    contracts: Vec<IdentifiedContract>,
    distance: Option<f64>,
) -> Result<GexHistoryRow, ArchiveError> {
    let valuation =
        Valuation::with_microseconds(spot, receipt_us).map_err(|_| ArchiveError::Invalid)?;
    let snapshot = OptionSnapshot::new(receipt_us, receipt_us, valuation, contracts)
        .map_err(|_| ArchiveError::Invalid)?;
    let summary = aggregate(&snapshot).map_err(|_| ArchiveError::Invalid)?;
    let walls = ranked_walls(&summary, spot, distance).map_err(|_| ArchiveError::Invalid)?;
    Ok(GexHistoryRow {
        receipt_us,
        spot,
        net: summary.totals.signed,
        call: summary.strikes.iter().map(|level| level.call).sum(),
        put: summary.strikes.iter().map(|level| level.put).sum(),
        absolute: summary.totals.absolute,
        flip: observed_flip(&snapshot).map_err(|_| ArchiveError::Invalid)?,
        calls: std::array::from_fn(|index| walls.calls.get(index).map(|level| level.strike)),
        puts: std::array::from_fn(|index| walls.puts.get(index).map(|level| level.strike)),
    })
}

struct Chain {
    receipt_us: i64,
    spot: f64,
    contracts: Vec<IdentifiedContract>,
}

fn calculate_batch(
    chains: &mut [Chain],
    workers: usize,
    distance: Option<f64>,
) -> Result<Vec<GexHistoryRow>, ArchiveError> {
    let chunk_size = chains.len().div_ceil(workers).max(1);
    thread::scope(|scope| {
        let jobs: Vec<_> = chains
            .chunks_mut(chunk_size)
            .map(|chunk| {
                scope.spawn(move || {
                    chunk
                        .iter_mut()
                        .map(|chain| {
                            row(
                                chain.receipt_us,
                                chain.spot,
                                std::mem::take(&mut chain.contracts),
                                distance,
                            )
                        })
                        .collect::<Result<Vec<_>, _>>()
                })
            })
            .collect();
        let mut rows = Vec::new();
        for job in jobs {
            rows.extend(job.join().map_err(|_| ArchiveError::Invalid)??);
        }
        Ok(rows)
    })
}

/// Calculate every complete BTC collection in one consistent read transaction.
/// Read bounded batches of chains and value them concurrently.
pub fn gex_history(path: &Path, distance: Option<f64>) -> Result<Vec<GexHistoryRow>, ArchiveError> {
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    db.execute_batch("BEGIN DEFERRED")?;
    let tables = tables(&db)?;
    let collections = collections(&db, &tables, "BTC")?;
    let workers = thread::available_parallelism()
        .map_or(1, |count| count.get())
        .min(8);
    let capacity = 4 * workers;
    let mut batch = Vec::with_capacity(capacity);
    let mut history = Vec::with_capacity(collections.len());
    for collection in &collections {
        let available = DateTime::parse_from_rfc3339(&collection.available_at)
            .map_err(|_| ArchiveError::Invalid)?
            .timestamp_micros();
        let values = payloads(&db, &tables, collection)?;
        let spot = deribit::spot(values.get("spot").ok_or(ArchiveError::Invalid)?)
            .map_err(|_| ArchiveError::Invalid)?;
        let contracts = normalized_chain(&values)?
            .into_iter()
            .filter(|item| item.expiry_ms * 1000 > available)
            .map(contract)
            .collect::<Result<Vec<_>, _>>()?;
        batch.push(Chain {
            receipt_us: available,
            spot,
            contracts,
        });
        if batch.len() == capacity {
            history.extend(calculate_batch(&mut batch, workers, distance)?);
            batch.clear();
        }
    }
    history.extend(calculate_batch(&mut batch, workers, distance)?);
    history.sort_by_key(|item| item.receipt_us);
    Ok(history)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::{Observation, save_market};
    use serde_json::json;

    #[test]
    fn history_keeps_the_exact_receipt_and_excludes_expired_contracts() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("history.sqlite");
        let available = "2026-01-01T00:00:00.125000+00:00";
        let receipt = DateTime::parse_from_rfc3339(available).unwrap();
        let expiry = receipt.timestamp_millis() + 86_400_000;
        let definition = |name: &str, strike: f64, expiry: i64| {
            json!({
                "instrument_name": name, "kind": "option", "base_currency": "BTC",
                "option_type": "call", "is_active": true, "contract_size": 1.0,
                "strike": strike, "expiration_timestamp": expiry,
            })
        };
        for (source, result) in [
            ("spot", json!({"index_price": 100.0})),
            (
                "instruments",
                json!([
                    definition("live", 100.0, expiry),
                    definition("expired", 101.0, receipt.timestamp_millis())
                ]),
            ),
            (
                "options",
                json!([
                    {"instrument_name": "live", "open_interest": 5.0, "mark_iv": 50.0},
                    {"instrument_name": "expired", "open_interest": 999.0, "mark_iv": 50.0}
                ]),
            ),
        ] {
            save_market(
                &path,
                &Observation {
                    asset: "BTC".into(),
                    source: source.into(),
                    requested: available.into(),
                    available: available.into(),
                    collection: "first".into(),
                    payload: json!({"result":result}).to_string(),
                    error: String::new(),
                },
                None,
                source != "spot",
            )
            .unwrap();
        }
        let rows = gex_history(&path, Some(0.2)).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].receipt_us, receipt.timestamp_micros());
        assert_eq!(rows[0].calls, [Some(100.0), None]);
        assert_eq!(rows[0].puts, [None, None]);
        assert!(rows[0].net > 0.0);
        assert_eq!(rows[0].net, rows[0].call);
        assert_eq!(rows[0].absolute, rows[0].call);
        assert_eq!(rows[0].flip, None);
    }
}
