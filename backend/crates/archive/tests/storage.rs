use archive::local_archive::market_index;
use archive::storage::{
    MarketWindow, Observation, SavedOptions, load_market, load_options, save_market, save_options,
};
use rusqlite::Connection;

const START: &str = "2026-11-09T12:00:00+00:00";
const RECEIPT: &str = "2026-11-09T12:00:01.125000+00:00";
const BEFORE: &str = "2026-11-09T12:00:01.124999+00:00";

#[test]
fn options_upgrade_and_insert_are_atomic_and_old_chains_are_readable() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("options.sqlite");
    assert!(load_options(&path).unwrap().is_empty());
    let db = Connection::open(&path).unwrap();
    assert!(load_options(&path).unwrap_err().sqlite_exception() == Some("OperationalError"));
    db.execute_batch("CREATE TABLE options_snapshots (available_at TEXT PRIMARY KEY, asset TEXT, observed_at TEXT, source TEXT, content TEXT);
        INSERT INTO options_snapshots VALUES ('earlier','BTC','earlier','source','old chain');").unwrap();
    let mut snapshot = SavedOptions {
        available_at: "earlier".into(),
        asset: "BTC".into(),
        observed_at: START.into(),
        source: "DERIBIT".into(),
        content: "new chain".into(),
        depth: Some("book".into()),
    };
    assert_eq!(
        save_options(&path, &snapshot)
            .unwrap_err()
            .sqlite_exception(),
        Some("IntegrityError")
    );
    let depth_columns: i64 = db.query_row("SELECT count(*) FROM pragma_table_info('options_snapshots') WHERE name='depth_content'", [], |row| row.get(0)).unwrap();
    assert_eq!(depth_columns, 0);
    assert_eq!(load_options(&path).unwrap(), [("old chain".into(), None)]);

    snapshot.available_at = "later".into();
    save_options(&path, &snapshot).unwrap();
    assert_eq!(
        load_options(&path).unwrap(),
        [
            ("old chain".into(), None),
            ("new chain".into(), Some("book".into()))
        ]
    );

    let fresh = directory.path().join("fresh.sqlite");
    save_options(&fresh, &snapshot).unwrap();
    assert_eq!(load_options(&fresh).unwrap().len(), 1);
}

fn window(asset: &str, end: &str, sources: &[&str]) -> MarketWindow {
    MarketWindow {
        asset: asset.into(),
        start: START.into(),
        end: end.into(),
        sources: sources.iter().map(|item| (*item).into()).collect(),
    }
}

fn observation(source: &str, error: &str) -> Observation {
    Observation {
        asset: "ETH".into(),
        source: source.into(),
        requested: START.into(),
        available: RECEIPT.into(),
        payload: "{\"data\":0}".into(),
        collection: "collection".into(),
        error: error.into(),
    }
}

#[test]
fn cutoff_is_inclusive_and_unselected_or_failed_receipts_are_excluded() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("nested/market.sqlite");
    save_market(&path, &observation("options", ""), None, true).unwrap();
    save_market(&path, &observation("spot", ""), Some(START), false).unwrap();
    save_market(&path, &observation("instruments", ""), None, true).unwrap();
    save_market(&path, &observation("depth", "timeout"), None, true).unwrap();
    let db = Connection::open(&path).unwrap();
    let payloads: i64 = db
        .query_row("SELECT count(*) FROM tunnel_payloads", [], |row| row.get(0))
        .unwrap();
    assert_eq!(payloads, 1);
    assert!(
        load_market(&path, window("ETH", BEFORE, &["spot"]))
            .unwrap()
            .is_empty()
    );
    assert!(
        load_market(&path, window("BTC", RECEIPT, &["spot"]))
            .unwrap()
            .is_empty()
    );
    let records =
        load_market(&path, window("ETH", RECEIPT, &["spot", "options", "depth"])).unwrap();
    assert_eq!(
        records
            .iter()
            .map(|item| item.source.as_str())
            .collect::<Vec<_>>(),
        ["spot", "options"]
    );
    assert_eq!(records[1].payload, "{\"data\":0}");
    assert_eq!(records[1].available, RECEIPT);
    assert_eq!(market_index(&path, "ETH").unwrap()[0].available_at, RECEIPT);
    assert!(market_index(&path, "BTC").unwrap().is_empty());
    assert!(market_index(&path, "DOGE").is_err());
    db.execute("UPDATE tunnel_payloads SET codec='gzip'", [])
        .unwrap();
    assert_eq!(
        load_market(&path, window("ETH", RECEIPT, &["spot"]))
            .unwrap()
            .len(),
        1
    );
    assert!(load_market(&path, window("ETH", RECEIPT, &["options"])).is_err());
}

#[test]
fn reads_legacy_raw_rows_and_rejects_invalid_windows_and_writes() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("legacy.sqlite");
    let db = Connection::open(&path).unwrap();
    db.execute_batch("CREATE TABLE tunnel_inputs (id INTEGER PRIMARY KEY, asset TEXT, source TEXT, requested_at TEXT, available_at TEXT, payload TEXT, error TEXT);").unwrap();
    db.execute(
        "INSERT INTO tunnel_inputs VALUES (1,'ETH','spot',?1,?2,'{}','')",
        [START, RECEIPT],
    )
    .unwrap();
    let records = load_market(&path, window("ETH", RECEIPT, &["spot"])).unwrap();
    assert_eq!(records[0].collection, "legacy:raw:1");
    assert!(load_market(&path, window("ETH", "invalid", &["spot"])).is_err());
    assert!(load_market(&path, window("DOGE", RECEIPT, &["spot"])).is_err());
    let mut invalid = observation("spot", "");
    invalid.available = "2025-01-01T00:00:00+00:00".into();
    assert!(save_market(&path, &invalid, None, false).is_err());
    save_market(&path, &observation("spot", ""), None, false).unwrap();
    assert_eq!(
        load_market(&path, window("ETH", RECEIPT, &["spot"]))
            .unwrap()
            .len(),
        2
    );
}

#[test]
fn candle_upserts_and_download_ranges_are_market_specific_and_inclusive() {
    use archive::storage::candles::{self, Candle, Market};

    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("candles.sqlite");
    candles::initialize(&path).unwrap();
    let market = Market {
        exchange: "Bybit".into(),
        symbol: "BTCUSDT".into(),
        interval: "1m".into(),
    };
    let other = Market {
        exchange: "Bybit".into(),
        symbol: "ETHUSDT".into(),
        interval: "1m".into(),
    };
    let mut candle = Candle {
        open_time_ms: 10,
        open: 1.0,
        high: 3.0,
        low: 1.0,
        close: 2.0,
        volume: 5.0,
        quote_volume: 8.0,
        trades: 2,
    };
    candles::upsert(&path, &market, std::slice::from_ref(&candle)).unwrap();
    candle.close = 3.0;
    candles::upsert(&path, &market, std::slice::from_ref(&candle)).unwrap();
    assert_eq!(candles::load(&path, &market, (10, 10)).unwrap(), [candle]);
    assert!(candles::load(&path, &market, (0, 9)).unwrap().is_empty());
    assert!(candles::load(&path, &other, (10, 10)).unwrap().is_empty());

    for bounds in [(2, 4), (2, 4), (4, 5), (7, 9)] {
        candles::mark_downloaded(&path, &market, bounds).unwrap();
    }
    assert_eq!(
        candles::missing_ranges(&path, &market, (1, 10)).unwrap(),
        [(1, 1), (6, 6), (10, 10)]
    );
    assert!(
        candles::missing_ranges(&path, &market, (2, 5))
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        candles::missing_ranges(&path, &other, (1, 10)).unwrap(),
        [(1, 10)]
    );
}

#[test]
fn failed_compact_receipt_does_not_leave_an_orphan_payload() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("market.sqlite");
    save_market(&path, &observation("options", ""), None, true).unwrap();
    let db = Connection::open(&path).unwrap();
    db.execute_batch(
        "CREATE TRIGGER reject_spot BEFORE INSERT ON tunnel_observations
         WHEN NEW.source='spot' BEGIN SELECT RAISE(ABORT, 'rejected receipt'); END;",
    )
    .unwrap();
    let mut rejected = observation("spot", "");
    rejected.payload = "{\"data\":1}".into();
    assert!(save_market(&path, &rejected, None, true).is_err());
    let count: i64 = db
        .query_row("SELECT count(*) FROM tunnel_payloads", [], |row| row.get(0))
        .unwrap();
    assert_eq!(count, 1);
    assert!(
        load_market(&path, window("ETH", RECEIPT, &["spot"]))
            .unwrap()
            .is_empty()
    );
}

#[test]
fn online_backup_includes_committed_wal_and_validates_schema() {
    use archive::storage::backup::{snapshot, validate};
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("source.sqlite");
    let copy = directory.path().join("backup.sqlite");
    let connection = Connection::open(&path).unwrap();
    connection
        .pragma_update(None, "journal_mode", "WAL")
        .unwrap();
    save_market(&path, &observation("spot", ""), None, true).unwrap();
    assert!(snapshot(&path, &path).is_err());
    snapshot(&path, &copy).unwrap();
    assert_eq!(
        load_market(&copy, window("ETH", RECEIPT, &["spot"]))
            .unwrap()
            .len(),
        1
    );
    connection
        .pragma_update(None, "foreign_keys", false)
        .unwrap();
    connection
        .execute("DELETE FROM tunnel_payloads", [])
        .unwrap();
    assert!(validate(&path).is_err());
    validate(&copy).unwrap();
}

#[test]
fn archive_validation_rejects_unrelated_files_and_incomplete_schema() {
    use archive::storage::backup::validate;
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("invalid.sqlite");
    let connection = Connection::open(&path).unwrap();
    assert!(validate(&path).is_err());
    connection
        .execute_batch("CREATE TABLE tunnel_inputs (id INTEGER PRIMARY KEY)")
        .unwrap();
    assert!(validate(&path).is_err());
}

#[test]
fn merge_compacts_raw_rows_deduplicates_and_preserves_destination_on_conflict() {
    use archive::storage::merge::{check, merge};
    let directory = tempfile::tempdir().unwrap();
    let source = directory.path().join("source.sqlite");
    let destination = directory.path().join("output.sqlite");
    let item = observation("spot", "");
    save_market(&source, &item, None, false).unwrap();
    save_market(&source, &item, None, true).unwrap();
    let report = merge(&source, &destination).unwrap();
    assert_eq!((report.observations, report.duplicates), (1, 1));
    let spot = report
        .timelines
        .iter()
        .find(|row| row.source == "spot")
        .unwrap();
    assert_eq!((spot.successful, spot.missing), (1, 0));
    assert_eq!(spot.first, START);
    let empty = report
        .timelines
        .iter()
        .find(|row| row.source == "oi")
        .unwrap();
    assert_eq!((empty.successful, empty.missing), (0, 1));

    let mut conflict = observation("spot", "");
    conflict.payload = "{\"data\":1}".into();
    let other = directory.path().join("conflict.sqlite");
    save_market(&other, &conflict, None, true).unwrap();
    let before = std::fs::read(&destination).unwrap();
    assert!(
        merge(&other, &destination)
            .unwrap_err()
            .to_string()
            .contains("Conflicting")
    );
    assert_eq!(std::fs::read(&destination).unwrap(), before);
    assert_eq!(check(&destination).unwrap().observations, 1);
}

#[test]
fn collection_due_and_retention_preserve_receipt_cutoffs_and_copy_managed_files() {
    use archive::storage::{market_due, prune_unmanaged};
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("market.sqlite");
    assert!(market_due(&path, "ETH", "spot", RECEIPT, 300).unwrap());
    assert!(!prune_unmanaged(&path, RECEIPT).unwrap());
    save_market(&path, &observation("spot", ""), None, true).unwrap();
    save_market(&path, &observation("oi", "failed"), None, false).unwrap();
    assert!(market_due(&path, "ETH", "spot", BEFORE, 300).unwrap());
    assert!(!market_due(&path, "ETH", "spot", RECEIPT, 300).unwrap());
    assert!(market_due(&path, "ETH", "oi", RECEIPT, 300).unwrap());
    assert!(market_due(&path, "ETH", "oi", RECEIPT, 0).is_err());

    assert!(!prune_unmanaged(&path, RECEIPT).unwrap());
    assert_eq!(
        load_market(&path, window("ETH", RECEIPT, &["spot"]))
            .unwrap()
            .len(),
        1
    );
    let later = "2026-11-09T12:00:02+00:00";
    let db = Connection::open(&path).unwrap();
    db.execute_batch("CREATE TABLE copy_receipts (fingerprint TEXT)")
        .unwrap();
    assert!(prune_unmanaged(&path, later).unwrap());
    assert_eq!(
        load_market(&path, window("ETH", RECEIPT, &["spot"]))
            .unwrap()
            .len(),
        1
    );
    db.execute_batch("DROP TABLE copy_receipts").unwrap();
    assert!(!prune_unmanaged(&path, later).unwrap());
    let payloads: i64 = db
        .query_row("SELECT count(*) FROM tunnel_payloads", [], |row| row.get(0))
        .unwrap();
    assert_eq!(payloads, 0);
}
