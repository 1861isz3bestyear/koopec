//! Transactional storage for exact source receipts.
//! This initial schema is separate from the legacy archive and does not migrate it.
use rusqlite::{Connection, OptionalExtension, params};
use std::path::Path;

/// One successful response or a recorded source failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReceiptBody {
    Payload(Vec<u8>),
    Failure(String),
}
/// Receipt metadata uses explicit Unix microseconds supplied by the caller.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Receipt {
    pub id: String,
    pub source: String,
    pub requested_at: i64,
    pub available_at: i64,
    pub body: ReceiptBody,
}
/// A committed receipt and its monotonic sequence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoredReceipt {
    pub sequence: i64,
    pub receipt: Receipt,
}
/// Invalid input or SQLite failure.
#[derive(Debug)]
pub enum ArchiveError {
    InvalidReceipt,
    Database(rusqlite::Error),
}
impl From<rusqlite::Error> for ArchiveError {
    fn from(e: rusqlite::Error) -> Self {
        Self::Database(e)
    }
}
impl std::fmt::Display for ArchiveError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for ArchiveError {}
/// SQLite-backed store with atomic receipt writes.
pub struct Archive {
    connection: Connection,
}
impl Archive {
    /// Open or create the initial schema. Reject unknown schema versions.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ArchiveError> {
        let connection = Connection::open(path)?;
        let version: i64 = connection.pragma_query_value(None, "user_version", |row| row.get(0))?;
        if version != 0 && version != 1 {
            return Err(ArchiveError::InvalidReceipt);
        }
        connection.execute_batch("BEGIN; CREATE TABLE IF NOT EXISTS receipts (sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, source TEXT NOT NULL, requested_at INTEGER NOT NULL, available_at INTEGER NOT NULL, payload BLOB, failure TEXT, CHECK ((payload IS NULL) != (failure IS NULL))); PRAGMA user_version = 1; COMMIT;")?;
        Ok(Self { connection })
    }
    /// Atomically record a new receipt. Identical bodies with different IDs remain distinct.
    pub fn append(&mut self, receipt: &Receipt) -> Result<i64, ArchiveError> {
        if receipt.id.trim().is_empty()
            || receipt.source.trim().is_empty()
            || receipt.available_at < receipt.requested_at
            || matches!(&receipt.body, ReceiptBody::Failure(s) if s.trim().is_empty())
        {
            return Err(ArchiveError::InvalidReceipt);
        }
        let (payload, failure) = match &receipt.body {
            ReceiptBody::Payload(data) => (Some(data.as_slice()), None),
            ReceiptBody::Failure(message) => (None, Some(message.as_str())),
        };
        let tx = self.connection.transaction()?;
        tx.execute("INSERT INTO receipts (id, source, requested_at, available_at, payload, failure) VALUES (?1, ?2, ?3, ?4, ?5, ?6)", params![receipt.id, receipt.source, receipt.requested_at, receipt.available_at, payload, failure])?;
        let sequence = tx.last_insert_rowid();
        tx.commit()?;
        Ok(sequence)
    }
    /// Read a receipt by ID only if committed at or before the run's high-water mark.
    pub fn get(&self, id: &str, high_water: i64) -> Result<Option<StoredReceipt>, ArchiveError> {
        Ok(self.connection.query_row("SELECT sequence, source, requested_at, available_at, payload, failure FROM receipts WHERE id = ?1 AND sequence <= ?2", params![id, high_water], |row| {
            let payload: Option<Vec<u8>> = row.get(4)?;
            let failure: Option<String> = row.get(5)?;
            let body = match (payload, failure) { (Some(bytes), None) => ReceiptBody::Payload(bytes), (None, Some(message)) => ReceiptBody::Failure(message), _ => return Err(rusqlite::Error::InvalidQuery) };
            Ok(StoredReceipt { sequence: row.get(0)?, receipt: Receipt { id: id.to_owned(), source: row.get(1)?, requested_at: row.get(2)?, available_at: row.get(3)?, body } })
        }).optional()?)
    }
}

/// Reader for existing local GEX option archives.
pub mod local_archive;
