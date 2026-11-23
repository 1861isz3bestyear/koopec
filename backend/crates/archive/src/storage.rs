//! Preserve the calculator's existing options history and market archive schemas.
use crate::local_archive::{compact_payload, payload_digest};
use crate::raw_collection;
use chrono::{DateTime, SecondsFormat, Utc};
use flate2::{Compression, write::ZlibEncoder};
use rusqlite::{Connection, OpenFlags, TransactionBehavior, params};
use std::{io::Write, path::Path, time::Duration};

#[derive(Debug)]
pub enum StorageError {
    Sql(rusqlite::Error),
    Io(std::io::Error),
    Invalid(&'static str),
}

impl From<rusqlite::Error> for StorageError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Sql(error)
    }
}

impl From<std::io::Error> for StorageError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

impl StorageError {
    pub fn sqlite_exception(&self) -> Option<&'static str> {
        match self {
            Self::Sql(rusqlite::Error::SqliteFailure(error, _))
                if error.code == rusqlite::ErrorCode::ConstraintViolation =>
            {
                Some("IntegrityError")
            }
            Self::Sql(_) => Some("OperationalError"),
            _ => None,
        }
    }
}

impl std::fmt::Display for StorageError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Sql(error) => error.fmt(f),
            Self::Io(error) => error.fmt(f),
            Self::Invalid(message) => f.write_str(message),
        }
    }
}

fn writer(path: &Path) -> Result<Connection, StorageError> {
    let connection = Connection::open(path)?;
    connection.busy_timeout(Duration::from_secs(30))?;
    Ok(connection)
}

fn reader(path: &Path) -> Result<Connection, StorageError> {
    let connection = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    connection.execute_batch("BEGIN DEFERRED")?;
    Ok(connection)
}

#[derive(Debug)]
pub struct SavedOptions {
    pub available_at: String,
    pub asset: String,
    pub observed_at: String,
    pub source: String,
    pub content: String,
    pub depth: Option<String>,
}

fn has_depth(db: &Connection) -> Result<bool, StorageError> {
    Ok(db.query_row(
        "SELECT EXISTS (SELECT 1 FROM pragma_table_info('options_snapshots') WHERE name='depth_content')",
        [],
        |row| row.get(0),
    )?)
}

/// Save the snapshot and attached depth together, upgrading legacy tables in the same transaction.
pub fn save_options(path: &Path, snapshot: &SavedOptions) -> Result<(), StorageError> {
    let mut db = writer(path)?;
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS options_snapshots (
        available_at TEXT NOT NULL, asset TEXT NOT NULL, observed_at TEXT NOT NULL,
        source TEXT NOT NULL, content TEXT NOT NULL, depth_content TEXT,
        PRIMARY KEY (available_at, asset))",
    )?;
    if !has_depth(&tx)? {
        tx.execute_batch("ALTER TABLE options_snapshots ADD COLUMN depth_content TEXT")?;
    }
    tx.execute(
        "INSERT INTO options_snapshots
         (available_at, asset, observed_at, source, content, depth_content) VALUES (?1,?2,?3,?4,?5,?6)",
        params![snapshot.available_at, snapshot.asset, snapshot.observed_at, snapshot.source, snapshot.content, snapshot.depth],
    )?;
    tx.commit()?;
    Ok(())
}

/// Read payloads from either snapshot schema without modifying the database.
pub fn load_options(path: &Path) -> Result<Vec<(String, Option<String>)>, StorageError> {
    if !path.try_exists()? {
        return Ok(Vec::new());
    }
    let db = reader(path)?;
    let query = if has_depth(&db)? {
        "SELECT content, depth_content FROM options_snapshots ORDER BY available_at, asset"
    } else {
        "SELECT content, NULL FROM options_snapshots ORDER BY available_at, asset"
    };
    let mut statement = db.prepare(query)?;
    let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
    Ok(rows.collect::<Result<_, _>>()?)
}

#[derive(Debug)]
pub struct MarketWindow {
    pub asset: String,
    pub start: String,
    pub end: String,
    pub sources: Vec<String>,
}

#[derive(Debug)]
pub struct Observation {
    pub asset: String,
    pub source: String,
    pub requested: String,
    pub available: String,
    pub payload: String,
    pub collection: String,
    pub error: String,
}

fn exists(db: &Connection, table: &str) -> Result<bool, StorageError> {
    Ok(db.query_row(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1)",
        [table],
        |row| row.get(0),
    )?)
}

fn valid_asset(asset: &str) -> bool {
    matches!(asset, "BTC" | "ETH")
}

fn time(value: &str) -> Result<DateTime<Utc>, StorageError> {
    DateTime::parse_from_rfc3339(value)
        .map(|value| value.with_timezone(&Utc))
        .map_err(|_| StorageError::Invalid("Invalid archive timestamp"))
}

fn iso(value: DateTime<Utc>) -> String {
    let format = if value.timestamp_subsec_micros() == 0 {
        SecondsFormat::Secs
    } else {
        SecondsFormat::Micros
    };
    value.to_rfc3339_opts(format, false)
}

fn read_market_table(
    db: &Connection,
    window: &MarketWindow,
    compact: bool,
) -> Result<Vec<(DateTime<Utc>, Observation)>, StorageError> {
    let table = if compact {
        "tunnel_observations"
    } else {
        "tunnel_inputs"
    };
    if !exists(db, table)? {
        return Ok(Vec::new());
    }
    let query = if compact {
        "SELECT o.source,o.requested_at,o.available_at,p.payload,o.collection_id,p.digest,p.codec
         FROM tunnel_observations o LEFT JOIN tunnel_payloads p ON p.digest=o.digest
         WHERE o.asset=?1 AND o.error='' AND o.available_at>=?2 AND o.available_at<=?3
         ORDER BY o.available_at,o.id"
            .to_owned()
    } else {
        let identity = raw_collection(db)?;
        format!(
            "SELECT source,requested_at,available_at,payload,{identity},NULL,NULL
          FROM tunnel_inputs WHERE asset=?1 AND error='' AND available_at>=?2 AND available_at<=?3
          ORDER BY available_at,id"
        )
    };
    let mut statement = db.prepare(&query)?;
    let mut rows = statement.query(params![window.asset, window.start, window.end])?;
    let mut observations = Vec::new();
    while let Some(row) = rows.next()? {
        let source: String = row.get(0)?;
        if !window.sources.contains(&source) {
            continue;
        }
        let requested: String = row.get(1)?;
        let available: String = row.get(2)?;
        let collection: String = row.get(4)?;
        let receipt = time(&available)?;
        if collection.is_empty() || receipt < time(&requested)? {
            return Err(StorageError::Invalid(
                "Invalid archive observation identity or timing",
            ));
        }
        let payload = if compact {
            compact_payload(row.get(3)?, row.get(5)?, row.get(6)?)
                .map_err(|_| StorageError::Invalid("Invalid compressed archive payload"))?
        } else {
            row.get(3)?
        };
        observations.push((
            receipt,
            Observation {
                asset: window.asset.clone(),
                source,
                requested,
                available,
                payload,
                collection,
                error: String::new(),
            },
        ));
    }
    Ok(observations)
}

/// Read requested streams at an inclusive receipt cutoff using a single SQLite read snapshot.
pub fn load_market(
    path: &Path,
    mut window: MarketWindow,
) -> Result<Vec<Observation>, StorageError> {
    let start = time(&window.start)?;
    let end = time(&window.end)?;
    if !valid_asset(&window.asset) || start > end {
        return Err(StorageError::Invalid("Invalid archive window"));
    }
    window.start = iso(start);
    window.end = iso(end);
    let db = reader(path)?;
    let mut result = read_market_table(&db, &window, false)?;
    result.extend(read_market_table(&db, &window, true)?);
    result.sort_by_key(|(receipt, _)| *receipt);
    Ok(result
        .into_iter()
        .map(|(_, observation)| observation)
        .collect())
}

fn prepare_market(db: &Connection) -> Result<(), StorageError> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS tunnel_inputs (
        id INTEGER PRIMARY KEY, asset TEXT NOT NULL, source TEXT NOT NULL,
        requested_at TEXT NOT NULL, available_at TEXT NOT NULL, payload TEXT NOT NULL,
        error TEXT NOT NULL, collection_id TEXT, minute_at TEXT);
        CREATE TABLE IF NOT EXISTS tunnel_payloads (digest TEXT PRIMARY KEY, codec TEXT NOT NULL, payload BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS tunnel_observations (
        id INTEGER PRIMARY KEY, asset TEXT NOT NULL, source TEXT NOT NULL,
        requested_at TEXT NOT NULL, available_at TEXT NOT NULL, digest TEXT NOT NULL REFERENCES tunnel_payloads(digest),
        error TEXT NOT NULL, collection_id TEXT NOT NULL, minute_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS tunnel_inputs_source_time ON tunnel_inputs(asset,source,available_at);
        CREATE INDEX IF NOT EXISTS tunnel_observations_source_time ON tunnel_observations(asset,source,available_at);")?;
    for (name, upgrade) in [
        (
            "collection_id",
            "ALTER TABLE tunnel_inputs ADD COLUMN collection_id TEXT",
        ),
        (
            "minute_at",
            "ALTER TABLE tunnel_inputs ADD COLUMN minute_at TEXT",
        ),
    ] {
        let present: bool = db.query_row(
            "SELECT EXISTS(SELECT 1 FROM pragma_table_info('tunnel_inputs') WHERE name=?1)",
            [name],
            |row| row.get(0),
        )?;
        if !present {
            db.execute_batch(upgrade)?;
        }
    }
    Ok(())
}

/// Save the exact observation in the raw or compressed legacy format.
pub fn save_market(
    path: &Path,
    item: &Observation,
    collection_start: Option<&str>,
    compact: bool,
) -> Result<(), StorageError> {
    let requested = time(&item.requested)?;
    let available = time(&item.available)?;
    if !valid_asset(&item.asset)
        || item.collection.is_empty()
        || item.source.is_empty()
        || available < requested
    {
        return Err(StorageError::Invalid(
            "Invalid archive observation identity or timing",
        ));
    }
    let start = collection_start.map(time).transpose()?.unwrap_or(requested);
    let minute = DateTime::from_timestamp(start.timestamp().div_euclid(60) * 60, 0)
        .ok_or(StorageError::Invalid("Invalid archive collection minute"))?;
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        std::fs::create_dir_all(parent)?;
    }
    let mut db = writer(path)?;
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    prepare_market(&tx)?;
    let (sql, body) = if compact {
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(item.payload.as_bytes())?;
        let digest = payload_digest(item.payload.as_bytes());
        tx.execute(
            "INSERT OR IGNORE INTO tunnel_payloads VALUES (?1,'zlib',?2)",
            params![digest, encoder.finish()?],
        )?;
        ("INSERT INTO tunnel_observations
          (asset,source,requested_at,available_at,digest,error,collection_id,minute_at) VALUES (?1,?2,?3,?4,?5,?6,?7,?8)", digest)
    } else {
        ("INSERT INTO tunnel_inputs
          (asset,source,requested_at,available_at,payload,error,collection_id,minute_at) VALUES (?1,?2,?3,?4,?5,?6,?7,?8)", item.payload.clone())
    };
    tx.execute(
        sql,
        params![
            item.asset,
            item.source,
            iso(requested),
            iso(available),
            body,
            item.error,
            item.collection,
            iso(minute)
        ],
    )?;
    tx.commit()?;
    Ok(())
}

/// Historical candle cache and downloaded range persistence.
pub mod candles;
