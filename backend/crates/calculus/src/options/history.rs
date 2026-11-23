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
    const DAY_SECONDS: i64 = 86_400;
    const TARGET_SECONDS: i128 = 8 * 3_600 + 15 * 60;
    let mut days: BTreeMap<i64, (&SavedSnapshot, i128)> = BTreeMap::new();
    for item in snapshots {
        if item.asset != SnapshotAsset::Btc {
            continue;
        }
        let timestamp = item.snapshot.available_at();
        let day = timestamp.div_euclid(DAY_SECONDS);
        let target = i128::from(day) * i128::from(DAY_SECONDS) + TARGET_SECONDS;
        let distance = (i128::from(timestamp) - target).abs();
        days.entry(day)
            .and_modify(|selected| {
                if (distance, timestamp) < (selected.1, selected.0.snapshot.available_at()) {
                    *selected = (item, distance);
                }
            })
            .or_insert((item, distance));
    }
    days.into_values().map(|(item, _)| item).collect()
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
