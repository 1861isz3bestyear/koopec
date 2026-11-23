use calculus::options::{
    OptionSnapshot, SavedSnapshot, SnapshotAsset, Valuation, select_daily_snapshots,
    selected_snapshot_at,
};

fn saved(asset: SnapshotAsset, time: i64, spot: f64) -> SavedSnapshot {
    SavedSnapshot {
        asset,
        snapshot: OptionSnapshot::new(time, time, Valuation::new(spot, time).unwrap(), vec![])
            .unwrap(),
    }
}
// Python tunnel_plans.py SHA-256 35555543024b2a19c335b163f2974820fc3216a9462a84ea89b595db9d9e0e02.
// Reference selected (availability, spot): (-56700, 105), (29400, 101), (116100, 104).
#[test]
fn selects_daily_btc_nearest_to_0815_with_earlier_ties() {
    let records = vec![
        saved(SnapshotAsset::Btc, 30_000, 100.0),
        saved(SnapshotAsset::Btc, 29_400, 101.0),
        saved(SnapshotAsset::Btc, 29_400, 102.0),
        saved(SnapshotAsset::Eth, 29_700, 103.0),
        saved(SnapshotAsset::Btc, 86_400 + 29_700, 104.0),
        saved(SnapshotAsset::Btc, -86_400 + 29_700, 105.0),
    ];
    let selected = select_daily_snapshots(&records);
    assert_eq!(selected.len(), 3);
    assert_eq!(selected[0].snapshot.available_at(), -56_700);
    assert!(std::ptr::eq(selected[1], &records[1]));
    assert_eq!(selected[2].snapshot.available_at(), 116_100);
}
#[test]
fn selection_respects_receipt_and_exclusive_day_expiry() {
    let records = vec![
        saved(SnapshotAsset::Btc, 29_700, 100.0),
        saved(SnapshotAsset::Btc, 116_100, 100.0),
    ];
    let selected = select_daily_snapshots(&records);
    assert!(selected_snapshot_at(&selected, 29_699).is_none());
    assert!(std::ptr::eq(
        selected_snapshot_at(&selected, 29_700).unwrap(),
        &records[0]
    ));
    assert!(std::ptr::eq(
        selected_snapshot_at(&selected, 116_099).unwrap(),
        &records[0]
    ));
    assert!(std::ptr::eq(
        selected_snapshot_at(&selected, 116_100).unwrap(),
        &records[1]
    ));
    assert!(selected_snapshot_at(&selected, 202_500).is_none());
    assert!(select_daily_snapshots(&[]).is_empty());
}
