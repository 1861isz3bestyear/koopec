use super::{
    Observation, StorageError, backup, compact_payload, exists, insert_market, iso, payload_digest,
    prepare_market, reader, time, valid_asset, writer,
};
use chrono::DateTime;
use rusqlite::{Connection, Row, params};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fs::{File, OpenOptions},
    path::Path,
};

const SOURCES: [(&str, i64); 9] = [
    ("instruments", 300),
    ("options", 300),
    ("spot", 300),
    ("depth", 300),
    ("ticker", 300),
    ("oi", 300),
    ("bitget_growth_24h", 3600),
    ("bitget_growth_30d", 3600),
    ("bitget_loan_rate", 3600),
];

#[derive(Debug)]
pub struct Timeline {
    pub asset: String,
    pub source: &'static str,
    pub first: String,
    pub last: String,
    pub successful: usize,
    pub missing: usize,
}

#[derive(Debug, Default)]
pub struct Report {
    pub observations: usize,
    pub duplicates: usize,
    pub timelines: Vec<Timeline>,
}

fn record(row: &Row<'_>, compact: bool) -> Result<(Observation, String), StorageError> {
    let payload = if compact {
        compact_payload(row.get(4)?, row.get(8)?, row.get(9)?)
            .map_err(|_| StorageError::Invalid("Invalid compressed archive payload"))?
    } else {
        row.get(4)?
    };
    let asset: String = row.get(0)?;
    let source: String = row.get(1)?;
    let requested = time(&row.get::<_, String>(2)?)?;
    let available = time(&row.get::<_, String>(3)?)?;
    let error: String = row.get(5)?;
    let collection: String = row.get(6)?;
    let minute = time(&row.get::<_, String>(7)?)?;
    if !valid_asset(&asset)
        || !SOURCES.iter().any(|(name, _)| *name == source)
        || collection.is_empty()
        || available < requested
    {
        return Err(StorageError::Invalid(
            "Invalid archive observation identity or timing",
        ));
    }
    if minute > requested
        || minute.timestamp().rem_euclid(60) != 0
        || minute.timestamp_subsec_nanos() != 0
    {
        return Err(StorageError::Invalid(
            "Invalid collection minute in archive",
        ));
    }
    if error.is_empty() && serde_json::from_str::<serde_json::Value>(&payload).is_err() {
        return Err(StorageError::Invalid(
            "Invalid successful archive payload JSON",
        ));
    }
    Ok((
        Observation {
            asset,
            source,
            requested: iso(requested),
            available: iso(available),
            payload,
            collection,
            error,
        },
        iso(minute),
    ))
}

fn append(db: &Connection, item: &Observation, minute: &str) -> Result<bool, StorageError> {
    let mut query = db.prepare_cached(
        "SELECT digest FROM tunnel_observations WHERE asset=?1 AND source=?2
         AND requested_at=?3 AND available_at=?4 AND error=?5",
    )?;
    let mut matches = query.query(params![
        item.asset,
        item.source,
        item.requested,
        item.available,
        item.error
    ])?;
    if let Some(row) = matches.next()? {
        let previous: String = row.get(0)?;
        if previous != payload_digest(item.payload.as_bytes()) || matches.next()?.is_some() {
            return Err(StorageError::Invalid(
                "Conflicting payloads for the same observation time",
            ));
        }
        return Ok(false);
    }
    insert_market(db, item, minute, true)?;
    Ok(true)
}

fn collect(path: &Path, destination: &Connection, report: &mut Report) -> Result<(), StorageError> {
    backup::validate(path)?;
    let source = reader(path)?;
    for (compact, table, query) in [
        (false, "tunnel_inputs", "SELECT asset,source,requested_at,available_at,payload,error,collection_id,minute_at FROM tunnel_inputs"),
        (true, "tunnel_observations", "SELECT o.asset,o.source,o.requested_at,o.available_at,p.payload,o.error,o.collection_id,o.minute_at,p.digest,p.codec
         FROM tunnel_observations o LEFT JOIN tunnel_payloads p ON p.digest=o.digest"),
    ] {
        if !exists(&source, table)? {
            continue;
        }
        let mut statement = source.prepare(query)?;
        let mut rows = statement.query([])?;
        while let Some(row) = rows.next()? {
            let (item, minute) = record(row, compact)?;
            if append(destination, &item, &minute)? {
                report.observations += 1;
            } else {
                report.duplicates += 1;
            }
        }
    }
    Ok(())
}

fn display_time(timestamp: i64) -> Result<String, StorageError> {
    Ok(iso(DateTime::from_timestamp(timestamp, 0).ok_or(
        StorageError::Invalid("Invalid archive coverage time"),
    )?))
}

fn timelines(db: &Connection) -> Result<Vec<Timeline>, StorageError> {
    let mut statement =
        db.prepare("SELECT asset,source,requested_at,error FROM tunnel_observations")?;
    let mut rows = statement.query([])?;
    let mut bounds = BTreeMap::new();
    let mut buckets: HashMap<(String, String), HashSet<i64>> = HashMap::new();
    while let Some(row) = rows.next()? {
        let asset: String = row.get(0)?;
        let source: String = row.get(1)?;
        let stamp = time(&row.get::<_, String>(2)?)?;
        let second = stamp.timestamp()
            + i64::from(stamp.timestamp() < 0 && stamp.timestamp_subsec_nanos() > 0);
        let error: String = row.get(3)?;
        if error.is_empty() {
            let (_, interval) = SOURCES
                .iter()
                .find(|(name, _)| *name == source)
                .ok_or(StorageError::Invalid("Unknown archive source"))?;
            buckets
                .entry((asset.clone(), source))
                .or_default()
                .insert(second.div_euclid(*interval));
        }
        let bound = bounds.entry(asset).or_insert((second, second));
        *bound = (bound.0.min(second), bound.1.max(second));
    }
    let mut output = Vec::new();
    for (asset, (first, last)) in bounds {
        for (source, interval) in SOURCES {
            let successful = buckets
                .get(&(asset.clone(), source.to_owned()))
                .map_or(0, HashSet::len);
            let total = usize::try_from(last.div_euclid(interval) - first.div_euclid(interval) + 1)
                .map_err(|_| StorageError::Invalid("Invalid archive coverage range"))?;
            output.push(Timeline {
                asset: asset.clone(),
                source,
                first: display_time(first)?,
                last: display_time(last)?,
                successful,
                missing: total - successful,
            });
        }
    }
    Ok(output)
}

fn build(source: &Path, previous: Option<&Path>, staging: &Path) -> Result<Report, StorageError> {
    let mut db = writer(staging)?;
    let tx = db.transaction()?;
    prepare_market(&tx)?;
    tx.execute_batch("CREATE INDEX merge_identity ON tunnel_observations(asset,source,requested_at,available_at,error)")?;
    let mut report = Report::default();
    if let Some(previous) = previous {
        collect(previous, &tx, &mut report)?;
    }
    collect(source, &tx, &mut report)?;
    report.timelines = timelines(&tx)?;
    tx.commit()?;
    backup::validate(staging)?;
    Ok(report)
}

pub fn check(path: &Path) -> Result<Report, StorageError> {
    let staging = tempfile::NamedTempFile::new()?;
    build(path, None, staging.path())
}

/// Publish the validated union using the same destination lock as the existing tools.
pub fn merge(source: &Path, destination: &Path) -> Result<Report, StorageError> {
    let parent = destination
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    std::fs::create_dir_all(parent)?;
    let mut lock_path = destination.as_os_str().to_owned();
    lock_path.push(".lock");
    let lock = OpenOptions::new()
        .create(true)
        .append(true)
        .open(lock_path)?;
    lock.lock()?;
    let staging = tempfile::NamedTempFile::new_in(parent)?;
    let previous = destination.try_exists()?.then_some(destination);
    let report = build(source, previous, staging.path())?;
    staging.as_file().sync_all()?;
    staging.persist(destination).map_err(|error| error.error)?;
    File::open(parent)?.sync_all()?;
    Ok(report)
}
