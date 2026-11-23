use super::{StorageError, exists, reader};
use rusqlite::{Connection, MAIN_DB, OpenFlags};
use std::path::Path;

fn schema(db: &Connection, table: &str, body: &str) -> Result<(), StorageError> {
    let mut statement = db.prepare("SELECT name FROM pragma_table_info(?1)")?;
    let columns = statement.query_map([table], |row| row.get::<_, String>(0))?;
    let columns = columns.collect::<Result<Vec<_>, _>>()?;
    for name in [
        "asset",
        "source",
        "requested_at",
        "available_at",
        "error",
        "collection_id",
        "minute_at",
        body,
    ] {
        if !columns.iter().any(|column| column == name) {
            return Err(StorageError::Invalid("Market archive schema is incomplete"));
        }
    }
    Ok(())
}

/// Check SQLite integrity, required columns and compact payload references.
pub fn validate(path: &Path) -> Result<(), StorageError> {
    let db = reader(path)?;
    let mut check = db.prepare("PRAGMA integrity_check")?;
    let findings = check.query_map([], |row| row.get::<_, String>(0))?;
    if findings.collect::<Result<Vec<_>, _>>()? != ["ok"] {
        return Err(StorageError::Invalid(
            "SQLite archive integrity check failed",
        ));
    }
    let raw = exists(&db, "tunnel_inputs")?;
    let compact = exists(&db, "tunnel_observations")?;
    if !raw && !compact {
        return Err(StorageError::Invalid(
            "Downloaded database is not a market archive",
        ));
    }
    if raw {
        schema(&db, "tunnel_inputs", "payload")?;
    }
    if compact {
        schema(&db, "tunnel_observations", "digest")?;
        let missing: bool = db.query_row(
            "SELECT EXISTS(SELECT 1 FROM tunnel_observations o LEFT JOIN tunnel_payloads p
             ON p.digest=o.digest WHERE p.digest IS NULL)",
            [],
            |row| row.get(0),
        )?;
        if missing {
            return Err(StorageError::Invalid(
                "Market archive has missing compressed payloads",
            ));
        }
    }
    Ok(())
}

/// Copy committed SQLite data, including WAL contents.
pub fn snapshot(source: &Path, destination: &Path) -> Result<(), StorageError> {
    if destination.try_exists()? && source.canonicalize()? == destination.canonicalize()? {
        return Err(StorageError::Invalid(
            "Backup destination must differ from the source",
        ));
    }
    let source = Connection::open_with_flags(source, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    source.backup(MAIN_DB, destination, None)?;
    validate(destination)
}
