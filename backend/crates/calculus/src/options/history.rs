//! Select receipt-stamped daily option snapshots without moving availability backward.
//! `OptionSnapshot` stores whole Unix seconds, so subsecond receipt parity is not yet supported.
use super::OptionSnapshot;
use std::collections::BTreeMap;

/// Underlying of an externally validated saved chain.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapshotAsset {
    Btc,
    Eth,
}

/// A saved chain; its availability time is owned by the validated snapshot.
#[derive(Debug, Clone, PartialEq)]
pub struct SavedSnapshot {
    pub asset: SnapshotAsset,
    pub snapshot: OptionSnapshot,
}

/// Select the BTC receipt nearest 08:15 UTC on each UTC date. Earlier ties win.
/// Equal timestamps retain the first input, matching Python's stable `min`.
#[must_use]
pub fn select_daily_snapshots(snapshots: &[SavedSnapshot]) -> Vec<&SavedSnapshot> {
    let receipts = snapshots
        .iter()
        .enumerate()
        .filter_map(|(index, snapshot)| {
            (snapshot.asset == SnapshotAsset::Btc)
                .then_some((index, snapshot.snapshot.available_at()))
        });
    select_receipts(receipts, 1)
        .into_iter()
        .map(|index| &snapshots[index])
        .collect()
}

/// Select the same daily receipts from exact Unix microseconds.
pub fn select_daily_receipts(receipts: impl Iterator<Item = (usize, i64)>) -> Vec<usize> {
    select_receipts(receipts, 1_000_000)
}

fn select_receipts(receipts: impl Iterator<Item = (usize, i64)>, precision: i64) -> Vec<usize> {
    let day_units = 86_400 * precision;
    let target_offset = i128::from((8 * 3_600 + 15 * 60) * precision);
    let mut days = BTreeMap::new();
    for (index, timestamp) in receipts {
        let day = timestamp.div_euclid(day_units);
        let target = i128::from(day) * i128::from(day_units) + target_offset;
        let distance = (i128::from(timestamp) - target).abs();
        let candidate = (distance, timestamp, index);
        days.entry(day)
            .and_modify(|selected: &mut (i128, i64, usize)| {
                if candidate < *selected {
                    *selected = candidate;
                }
            })
            .or_insert(candidate);
    }
    days.into_values().map(|(_, _, index)| index).collect()
}

/// Select the newest saved daily receipt at a cutoff, expiring after 24 hours.
/// Actual strategy plans may expire earlier at a contract expiry or for other
/// strategy reasons; this is only the receipt-selection boundary.
#[must_use]
pub fn selected_snapshot_at<'a>(
    selected: &[&'a SavedSnapshot],
    cutoff: i64,
) -> Option<&'a SavedSnapshot> {
    const DAY_SECONDS: i128 = 86_400;
    selected
        .iter()
        .copied()
        .filter(|item| {
            let available = item.snapshot.available_at();
            available <= cutoff && i128::from(cutoff) - i128::from(available) < DAY_SECONDS
        })
        .max_by_key(|item| item.snapshot.available_at())
}
