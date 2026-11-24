//! Select replay and chart snapshots before reading their archived payloads.
use super::{
    ArchiveError, ArchiveVersion, Collection, collections, normalized_chain, payloads, tables,
};
use calculus::options::select_daily_receipts;
use chrono::DateTime;
use market_data::deribit;
use rusqlite::{Connection, OpenFlags};
use std::{cmp::Reverse, path::Path};

/// Which receipts are needed by the calculator.
pub enum ReplaySelection {
    Daily,
    Through(i64),
}

/// The complete BTC chain available at a receipt, preserving exchange units.
pub struct ReplaySnapshot {
    pub receipt_us: i64,
    pub spot: f64,
    pub contracts: Vec<deribit::Contract>,
}

fn selected_indices(receipts: &[i64], selection: ReplaySelection) -> Vec<usize> {
    let receipts = receipts.iter().copied().enumerate();
    match selection {
        ReplaySelection::Daily => select_daily_receipts(receipts),
        ReplaySelection::Through(cutoff) => receipts
            .filter(|&(_, timestamp)| timestamp <= cutoff)
            .max_by_key(|&(index, timestamp)| (timestamp, Reverse(index)))
            .map(|(index, _)| index)
            .into_iter()
            .collect(),
    }
}

fn snapshot(
    db: &Connection,
    tables: &[&str],
    collection: &Collection,
    receipt_us: i64,
) -> Result<ReplaySnapshot, ArchiveError> {
    let values = payloads(db, tables, collection)?;
    let spot = deribit::spot(values.get("spot").ok_or(ArchiveError::Invalid)?)
        .map_err(|_| ArchiveError::Invalid)?;
    let contracts = normalized_chain(&values)?
        .into_iter()
        .filter(|item| item.expiry_ms > receipt_us.div_euclid(1000))
        .collect();
    Ok(ReplaySnapshot {
        receipt_us,
        spot,
        contracts,
    })
}

/// Read selected BTC chains in a single transaction, verifying the inspected version.
pub fn replay_snapshots(
    path: &Path,
    version: ArchiveVersion,
    selection: ReplaySelection,
) -> Result<Vec<ReplaySnapshot>, ArchiveError> {
    version.require_current(path)?;
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    db.execute_batch("BEGIN DEFERRED")?;
    let tables = tables(&db)?;
    let collections = collections(&db, &tables, "BTC")?;
    let receipts = collections
        .iter()
        .map(|collection| {
            DateTime::parse_from_rfc3339(&collection.available_at)
                .map(|time| time.timestamp_micros())
                .map_err(|_| ArchiveError::Invalid)
        })
        .collect::<Result<Vec<_>, _>>()?;
    let snapshots = selected_indices(&receipts, selection)
        .into_iter()
        .map(|index| snapshot(&db, &tables, &collections[index], receipts[index]))
        .collect::<Result<Vec<_>, _>>()?;
    version.require_current(path)?;
    Ok(snapshots)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cutoff_is_inclusive_and_keeps_the_first_equal_receipt() {
        let receipts = [30, 10, 20, 20];
        assert!(selected_indices(&receipts, ReplaySelection::Through(9)).is_empty());
        assert_eq!(
            selected_indices(&receipts, ReplaySelection::Through(20)),
            [2]
        );
        assert_eq!(
            selected_indices(&receipts, ReplaySelection::Through(30)),
            [0]
        );
    }
}
