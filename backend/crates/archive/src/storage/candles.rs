//! SQLite storage for cached candles and completed download windows.
use super::{StorageError, reader, writer};
use rusqlite::{Connection, params};
use std::path::Path;

pub struct Market {
    pub exchange: String,
    pub symbol: String,
    pub interval: String,
}

#[derive(Debug, PartialEq)]
pub struct Candle {
    pub open_time_ms: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
    pub quote_volume: f64,
    pub trades: i64,
}

pub fn initialize(path: &Path) -> Result<(), StorageError> {
    let db = writer(path)?;
    db.pragma_update(None, "journal_mode", "WAL")?;
    db.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS candles (
            exchange TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL,
            open_time_ms INTEGER NOT NULL, open REAL NOT NULL, high REAL NOT NULL,
            low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL,
            quote_asset_volume REAL NOT NULL, number_of_trades INTEGER NOT NULL,
            PRIMARY KEY (exchange, symbol, interval, open_time_ms)
        );
        CREATE TABLE IF NOT EXISTS downloaded_ranges (
            exchange TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL,
            start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
            PRIMARY KEY (exchange, symbol, interval, start_ms, end_ms)
        );",
    )?;
    Ok(())
}

/// Insert a batch atomically, replacing revised bars for the same market and time.
pub fn upsert(path: &Path, market: &Market, candles: &[Candle]) -> Result<(), StorageError> {
    let mut db = writer(path)?;
    let tx = db.transaction()?;
    {
        let mut statement = tx.prepare(
            "INSERT INTO candles VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)
             ON CONFLICT(exchange,symbol,interval,open_time_ms) DO UPDATE SET
             open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
             volume=excluded.volume, quote_asset_volume=excluded.quote_asset_volume,
             number_of_trades=excluded.number_of_trades",
        )?;
        for candle in candles {
            statement.execute(params![
                market.exchange,
                market.symbol,
                market.interval,
                candle.open_time_ms,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                candle.quote_volume,
                candle.trades
            ])?;
        }
    }
    tx.commit()?;
    Ok(())
}

pub fn mark_downloaded(
    path: &Path,
    market: &Market,
    bounds: (i64, i64),
) -> Result<(), StorageError> {
    let db = writer(path)?;
    db.execute(
        "INSERT OR IGNORE INTO downloaded_ranges VALUES (?1,?2,?3,?4,?5)",
        params![
            market.exchange,
            market.symbol,
            market.interval,
            bounds.0,
            bounds.1
        ],
    )?;
    Ok(())
}

fn ranges(
    db: &Connection,
    market: &Market,
    bounds: (i64, i64),
) -> Result<Vec<(i64, i64)>, StorageError> {
    let mut statement = db.prepare(
        "SELECT start_ms, end_ms FROM downloaded_ranges WHERE exchange=?1 AND symbol=?2 AND interval=?3
         AND end_ms>=?4 AND start_ms<=?5 ORDER BY start_ms",
    )?;
    let rows = statement.query_map(
        params![
            market.exchange,
            market.symbol,
            market.interval,
            bounds.0,
            bounds.1
        ],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    Ok(rows.collect::<Result<_, _>>()?)
}

/// Return inclusive ranges not already covered by successful downloads.
pub fn missing_ranges(
    path: &Path,
    market: &Market,
    (start, end): (i64, i64),
) -> Result<Vec<(i64, i64)>, StorageError> {
    let db = reader(path)?;
    let mut cursor = start;
    let mut missing = Vec::new();
    for (covered_start, covered_end) in ranges(&db, market, (start, end))? {
        if covered_start > cursor {
            missing.push((cursor, end.min(covered_start - 1)));
        }
        if covered_end >= end {
            return Ok(missing);
        }
        cursor = cursor.max(covered_end + 1);
    }
    if cursor <= end {
        missing.push((cursor, end));
    }
    Ok(missing)
}

pub fn load(path: &Path, market: &Market, bounds: (i64, i64)) -> Result<Vec<Candle>, StorageError> {
    let db = reader(path)?;
    let mut statement = db.prepare(
        "SELECT open_time_ms,open,high,low,close,volume,quote_asset_volume,number_of_trades
         FROM candles WHERE exchange=?1 AND symbol=?2 AND interval=?3
         AND open_time_ms>=?4 AND open_time_ms<=?5 ORDER BY open_time_ms",
    )?;
    let rows = statement.query_map(
        params![
            market.exchange,
            market.symbol,
            market.interval,
            bounds.0,
            bounds.1
        ],
        |row| {
            Ok(Candle {
                open_time_ms: row.get(0)?,
                open: row.get(1)?,
                high: row.get(2)?,
                low: row.get(3)?,
                close: row.get(4)?,
                volume: row.get(5)?,
                quote_volume: row.get(6)?,
                trades: row.get(7)?,
            })
        },
    )?;
    Ok(rows.collect::<Result<_, _>>()?)
}
