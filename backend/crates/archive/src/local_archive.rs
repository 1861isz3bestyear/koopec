//! Read complete option collections from a local Python market-storage archive.
use crate::raw_collection;
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize, Serialize)]
pub struct ExposureRequest {
    pub observed_at: i64,
    pub available_at: i64,
    pub valued_at: i64,
    pub spot: f64,
    pub contracts: Vec<Contract>,
}
#[derive(Debug, Deserialize, Serialize)]
pub struct Contract {
    pub id: String,
    pub kind: Kind,
    pub strike: f64,
    pub expiry: i64,
    pub iv: f64,
    pub open_interest: f64,
    pub multiplier: f64,
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Call,
    Put,
}
use chrono::{DateTime, Utc};
use flate2::read::ZlibDecoder;
use market_data::deribit;
use rusqlite::{Connection, OpenFlags, params};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{HashMap, HashSet},
    io::Read,
    path::Path,
};

#[derive(Debug)]
pub enum ArchiveError {
    Database,
    Invalid,
}
impl From<rusqlite::Error> for ArchiveError {
    fn from(_: rusqlite::Error) -> Self {
        Self::Database
    }
}

#[derive(Serialize)]
pub struct Collection {
    pub id: String,
    pub first_available_at: String,
    pub available_at: String,
}
#[derive(Serialize)]
pub struct LoadedArchive {
    pub collections: Vec<Collection>,
    pub selected: String,
    pub snapshot: ExposureRequest,
}
#[derive(Deserialize)]
pub struct Selection {
    pub collection: Option<String>,
    pub path: Option<String>,
}

fn tables(db: &Connection) -> Result<Vec<&'static str>, ArchiveError> {
    let mut found = Vec::new();
    for table in ["tunnel_inputs", "tunnel_observations"] {
        let exists: bool = db.query_row(
            "SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1)",
            [table],
            |row| row.get(0),
        )?;
        if exists {
            found.push(table);
        }
    }
    Ok(found)
}
fn collections(
    db: &Connection,
    tables: &[&str],
    asset: &str,
) -> Result<Vec<Collection>, ArchiveError> {
    if tables.is_empty() {
        return Ok(Vec::new());
    }
    let mut queries = Vec::new();
    for table in tables {
        queries.push(if *table == "tunnel_inputs" {
            let identity = raw_collection(db)?;
            format!("SELECT {identity} AS collection, available_at,source FROM tunnel_inputs WHERE asset=?1 AND error='' AND source IN ('instruments','options','spot')")
        } else {
            "SELECT collection_id AS collection, available_at,source FROM tunnel_observations WHERE asset=?1 AND error='' AND source IN ('instruments','options','spot')".to_owned()
        });
    }
    let query = format!(
        "SELECT collection, MIN(available_at), MAX(available_at) FROM ({}) GROUP BY collection HAVING COUNT(DISTINCT source)=3 ORDER BY MAX(available_at),collection",
        queries.join(" UNION ALL ")
    );
    let mut statement = db.prepare(&query)?;
    let mapped = statement.query_map([asset], |row| {
        Ok(Collection {
            id: row.get(0)?,
            first_available_at: row.get(1)?,
            available_at: row.get(2)?,
        })
    })?;
    let mut result = Vec::new();
    for row in mapped {
        let item = row?;
        DateTime::parse_from_rfc3339(&item.first_available_at)
            .map_err(|_| ArchiveError::Invalid)?;
        DateTime::parse_from_rfc3339(&item.available_at).map_err(|_| ArchiveError::Invalid)?;
        result.push(item);
    }
    Ok(result)
}
pub(crate) fn payload_digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|value| format!("{value:02x}"))
        .collect()
}

pub(crate) fn compact_payload(
    bytes: Vec<u8>,
    digest: String,
    codec: String,
) -> Result<String, ArchiveError> {
    if codec != "zlib" {
        return Err(ArchiveError::Invalid);
    }
    let mut decoded = Vec::new();
    ZlibDecoder::new(bytes.as_slice())
        .take(64 * 1024 * 1024)
        .read_to_end(&mut decoded)
        .map_err(|_| ArchiveError::Invalid)?;
    let actual = payload_digest(&decoded);
    if actual != digest {
        return Err(ArchiveError::Invalid);
    }
    String::from_utf8(decoded).map_err(|_| ArchiveError::Invalid)
}
fn payloads(
    db: &Connection,
    tables: &[&str],
    id: &str,
) -> Result<HashMap<String, Value>, ArchiveError> {
    let mut values = HashMap::new();
    for table in tables {
        let query = if *table == "tunnel_inputs" {
            let identity = raw_collection(db)?;
            format!(
                "SELECT source,payload,NULL,NULL FROM tunnel_inputs WHERE asset='BTC' AND error='' AND source IN ('instruments','options','spot') AND {identity}=?1"
            )
        } else {
            "SELECT o.source,p.payload,p.digest,p.codec FROM tunnel_observations o LEFT JOIN tunnel_payloads p ON p.digest=o.digest WHERE o.asset='BTC' AND o.error='' AND o.source IN ('instruments','options','spot') AND o.collection_id=?1".to_owned()
        };
        let mut statement = db.prepare(&query)?;
        let mut rows = statement.query(params![id])?;
        while let Some(row) = rows.next()? {
            let source: String = row.get(0)?;
            let text = if *table == "tunnel_inputs" {
                row.get(1)?
            } else {
                compact_payload(row.get(1)?, row.get(2)?, row.get(3)?)?
            };
            let payload: Value = serde_json::from_str(&text).map_err(|_| ArchiveError::Invalid)?;
            if values.insert(source, payload).is_some() {
                return Err(ArchiveError::Invalid);
            }
        }
    }
    if values.len() != 3 {
        return Err(ArchiveError::Invalid);
    }
    Ok(values)
}
fn parse_contracts(
    values: &HashMap<String, Value>,
    available_ms: i64,
) -> Result<Vec<Contract>, ArchiveError> {
    let result = |source: &str| {
        deribit::result(values.get(source).ok_or(ArchiveError::Invalid)?)
            .map_err(|_| ArchiveError::Invalid)
    };
    let chain = deribit::normalize_chain(result("instruments")?, result("options")?, "BTC")
        .map_err(|_| ArchiveError::Invalid)?;
    let mut contracts = Vec::new();
    let mut identities = HashSet::new();
    for contract in chain
        .into_iter()
        .filter(|item| item.expiry_ms > available_ms)
    {
        if !identities.insert((contract.expiry_ms, contract.strike.to_bits(), contract.side)) {
            return Err(ArchiveError::Invalid);
        }
        contracts.push(Contract {
            id: contract.instrument,
            kind: match contract.side {
                deribit::Side::Call => Kind::Call,
                deribit::Side::Put => Kind::Put,
            },
            strike: contract.strike,
            expiry: contract.expiry_ms.div_euclid(1000),
            iv: contract.iv,
            open_interest: contract.open_interest,
            multiplier: contract.multiplier,
        });
    }
    if contracts.is_empty() || contracts.len() > 10_000 {
        return Err(ArchiveError::Invalid);
    }
    Ok(contracts)
}
/// Read complete BTC collection bounds without opening their payloads.
pub fn index(path: &Path) -> Result<Vec<Collection>, ArchiveError> {
    let collections = market_index(path, "BTC")?;
    if collections.is_empty() {
        return Err(ArchiveError::Invalid);
    }
    Ok(collections)
}

/// Read collection bounds for a supported asset, allowing an empty result.
pub fn market_index(path: &Path, asset: &str) -> Result<Vec<Collection>, ArchiveError> {
    if !matches!(asset, "BTC" | "ETH") {
        return Err(ArchiveError::Invalid);
    }
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    db.execute_batch("BEGIN DEFERRED")?;
    collections(&db, &tables(&db)?, asset)
}

/// Read the collection index and one complete selected chain. Input is never modified.
pub fn load(path: &Path, selection: Option<&str>) -> Result<LoadedArchive, ArchiveError> {
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    db.execute_batch("BEGIN DEFERRED")?;
    let tables = tables(&db)?;
    let collections = collections(&db, &tables, "BTC")?;
    let selected = match selection {
        Some(id) => collections
            .iter()
            .find(|item| item.id == id)
            .ok_or(ArchiveError::Invalid)?,
        None => collections.last().ok_or(ArchiveError::Invalid)?,
    };
    let available = DateTime::parse_from_rfc3339(&selected.available_at)
        .map_err(|_| ArchiveError::Invalid)?
        .with_timezone(&Utc);
    let available_ms = available.timestamp_millis();
    let seconds = available
        .timestamp()
        .checked_add(i64::from(available.timestamp_subsec_nanos() != 0))
        .ok_or(ArchiveError::Invalid)?;
    let values = payloads(&db, &tables, &selected.id)?;
    let spot = deribit::spot(values.get("spot").ok_or(ArchiveError::Invalid)?)
        .map_err(|_| ArchiveError::Invalid)?;
    let contracts = parse_contracts(&values, available_ms)?;
    let selected = selected.id.clone();
    Ok(LoadedArchive {
        collections,
        selected,
        snapshot: ExposureRequest {
            observed_at: seconds,
            available_at: seconds,
            valued_at: seconds,
            spot,
            contracts,
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::{Compression, write::ZlibEncoder};
    use std::io::Write;

    mod support {
        include!(concat!(env!("CARGO_MANIFEST_DIR"), "/tests/support/mod.rs"));
    }
    use support::{create_archive, example_payloads};
    fn data() -> HashMap<String, Value> {
        example_payloads(200.0)
    }
    fn zipped(input: &[u8]) -> (Vec<u8>, String) {
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(input).unwrap();
        let digest = Sha256::digest(input)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        (encoder.finish().unwrap(), digest)
    }
    #[test]
    fn index_reports_complete_receipt_bounds_without_reading_payloads() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("index.sqlite");
        create_archive(&path);
        let db = Connection::open(&path).unwrap();
        db.execute("UPDATE tunnel_inputs SET payload='invalid'", [])
            .unwrap();
        db.execute("UPDATE tunnel_inputs SET available_at='2026-11-09T12:00:00+00:00' WHERE collection_id='older' AND source='spot'", []).unwrap();
        let collections = index(&path).unwrap();
        assert_eq!(collections.len(), 2);
        assert_eq!(collections[0].id, "older");
        assert_eq!(
            collections[0].first_available_at,
            "2026-11-09T12:00:00+00:00"
        );
        assert_eq!(collections[0].available_at, "2026-11-09T12:00:02+00:00");
        assert!(load(&path, Some("older")).is_err());
        db.execute(
            "UPDATE tunnel_inputs SET available_at='invalid' WHERE collection_id='older'",
            [],
        )
        .unwrap();
        assert!(index(&path).is_err());
    }

    #[test]
    fn compressed_payload_integrity_and_codec_are_checked() {
        let (data, digest) = zipped(br#"{"price":100}"#);
        assert_eq!(
            compact_payload(data.clone(), digest.clone(), "zlib".into()).unwrap(),
            "{\"price\":100}"
        );
        assert!(compact_payload(data.clone(), digest.clone(), "gzip".into()).is_err());
        assert!(compact_payload(data.clone(), "wrong".into(), "zlib".into()).is_err());
        assert!(compact_payload(vec![0], digest, "zlib".into()).is_err());
        let (data, digest) = zipped(&[0xff]);
        assert!(compact_payload(data, digest, "zlib".into()).is_err());
    }
    #[test]
    fn rejects_invalid_and_incomplete_exchange_data() {
        let original = data();
        let mut missing_quote = original.clone();
        missing_quote.get_mut("options").unwrap()["result"] = serde_json::json!([]);
        let mut invalid_side = original.clone();
        invalid_side.get_mut("instruments").unwrap()["result"][0]["option_type"] = "invalid".into();
        let mut foreign = original.clone();
        foreign.get_mut("instruments").unwrap()["result"][0]["base_currency"] = "ETH".into();
        let mut bad_expiry = original.clone();
        bad_expiry.get_mut("instruments").unwrap()["result"][0]["expiration_timestamp"] = 0.into();
        let mut bad_interest = original.clone();
        bad_interest.get_mut("options").unwrap()["result"][0]["open_interest"] = (-1).into();
        let mut inactive = original.clone();
        inactive.get_mut("instruments").unwrap()["result"][0]["is_active"] = false.into();
        let mut duplicate = original.clone();
        let first = duplicate["instruments"]["result"][0].clone();
        duplicate.get_mut("instruments").unwrap()["result"]
            .as_array_mut()
            .unwrap()
            .push(first);
        for invalid in [
            missing_quote,
            invalid_side,
            foreign,
            bad_expiry,
            bad_interest,
            inactive,
            duplicate,
        ] {
            assert!(parse_contracts(&invalid, 1_794_225_902_000).is_err());
        }
        assert!(parse_contracts(&original, 1_900_000_000_000).is_err());
    }
    #[test]
    fn compact_archive_loads_and_receipt_time_rounds_forward() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("compact.sqlite");
        let db = Connection::open(&path).unwrap();
        db.execute_batch("CREATE TABLE tunnel_payloads (digest TEXT,codec TEXT,payload BLOB); CREATE TABLE tunnel_observations (asset TEXT,source TEXT,available_at TEXT,digest TEXT,error TEXT,collection_id TEXT)").unwrap();
        for (source, payload) in data() {
            let (bytes, digest) = zipped(payload.to_string().as_bytes());
            db.execute(
                "INSERT INTO tunnel_payloads VALUES (?1,'zlib',?2)",
                params![digest, bytes],
            )
            .unwrap();
            db.execute("INSERT INTO tunnel_observations VALUES ('BTC',?1,'2026-11-09T12:05:02.500+00:00',?2,'','test')",params![source,digest]).unwrap();
        }
        let loaded = load(&path, None).unwrap();
        assert_eq!(loaded.collections.len(), 1);
        assert_eq!(loaded.snapshot.available_at, 1_794_225_903);
        assert_eq!(loaded.snapshot.contracts.len(), 1);
        db.execute("UPDATE tunnel_payloads SET codec='gzip'", [])
            .unwrap();
        assert!(load(&path, None).is_err());
    }
    #[test]
    fn rejects_unrelated_database_empty_and_duplicate_source() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("bad.sqlite");
        let db = Connection::open(&path).unwrap();
        assert!(load(&path, None).is_err());
        db.execute_batch("CREATE TABLE tunnel_inputs (id INTEGER,asset TEXT,source TEXT,available_at TEXT,payload TEXT,error TEXT,collection_id TEXT)").unwrap();
        assert!(load(&path, None).is_err());
        let copied = dir.path().join("duplicate.sqlite");
        create_archive(&copied);
        let db = Connection::open(&copied).unwrap();
        db.execute("INSERT INTO tunnel_inputs (asset,source,available_at,payload,error,collection_id) SELECT asset,source,available_at,payload,error,collection_id FROM tunnel_inputs WHERE collection_id='newer' AND source='spot'",[]).unwrap();
        assert!(load(&copied, None).is_err());
    }
}

#[cfg(test)]
mod boundary_tests {
    use super::*;
    use serde_json::json;

    fn chain() -> HashMap<String, Value> {
        HashMap::from([
            (
                "instruments".into(),
                json!({"result":[{"instrument_name":"a","is_active":true,"base_currency":"BTC","kind":"option","option_type":"put","expiration_timestamp":1795003200000_i64,"strike":100,"contract_size":2}]}),
            ),
            (
                "options".into(),
                json!({"result":[{"instrument_name":"a","open_interest":20,"mark_iv":50}]}),
            ),
        ])
    }
    #[test]
    fn put_normalization_and_expiry_boundary_are_causal() {
        let records = chain();
        let live = parse_contracts(&records, 1_795_003_199_999).unwrap();
        assert!(matches!(live[0].kind, Kind::Put));
        assert_eq!(live[0].open_interest, 10.0);
        assert_eq!(live[0].iv, 0.5);
        assert!(parse_contracts(&records, 1_795_003_200_000).is_err());
    }
    #[test]
    fn rejects_arithmetic_overflow_and_duplicate_economic_identity() {
        let mut overflow = chain();
        overflow.get_mut("instruments").unwrap()["result"][0]["contract_size"] = json!(1e-300);
        overflow.get_mut("options").unwrap()["result"][0]["open_interest"] = json!(1e300);
        assert!(parse_contracts(&overflow, 1).is_err());
        let mut duplicate = chain();
        let mut item = duplicate["instruments"]["result"][0].clone();
        item["instrument_name"] = "b".into();
        duplicate.get_mut("instruments").unwrap()["result"]
            .as_array_mut()
            .unwrap()
            .push(item);
        let mut quote = duplicate["options"]["result"][0].clone();
        quote["instrument_name"] = "b".into();
        duplicate.get_mut("options").unwrap()["result"]
            .as_array_mut()
            .unwrap()
            .push(quote);
        assert!(parse_contracts(&duplicate, 1).is_err());
    }
}
