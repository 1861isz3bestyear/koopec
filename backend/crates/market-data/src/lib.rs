//! Exchange-specific public market-data requests and validated responses.
//! Transport and receipt timestamps are supplied by the caller.
use calculus::indicators::{BookLevel, GrowthObservation};
use serde_json::Value;
use std::collections::BTreeMap;

/// Public exchange requests supported by the oscillator adapters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    BybitBook,
    BitgetHourlyGrowth,
    BitgetDailyGrowth,
    BitgetLoanRate,
}

/// A public endpoint and query parameters; the caller owns HTTP and scheduling.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Request {
    pub url: &'static str,
    pub parameters: Vec<(&'static str, String)>,
}

/// Invalid asset, exchange response, timestamp, or numeric value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InvalidData;

/// Construct the request for a supported underlying.
pub fn request(source: Source, asset: &str) -> Result<Request, InvalidData> {
    if !matches!(asset, "BTC" | "ETH") {
        return Err(InvalidData);
    }
    let symbol = format!("{asset}USDT");
    let request = match source {
        Source::BybitBook => Request {
            url: "https://api.bybit.com/v5/market/orderbook",
            parameters: vec![
                ("category", "linear".into()),
                ("symbol", symbol),
                ("limit", "50".into()),
            ],
        },
        Source::BitgetHourlyGrowth | Source::BitgetDailyGrowth => Request {
            url: "https://api.bitget.com/api/v3/market/margin-loan-growth",
            parameters: vec![
                ("symbol", symbol),
                ("coin", asset.into()),
                (
                    "period",
                    if source == Source::BitgetHourlyGrowth {
                        "24h"
                    } else {
                        "30d"
                    }
                    .into(),
                ),
            ],
        },
        Source::BitgetLoanRate => Request {
            url: "https://api.bitget.com/api/v3/market/margin-loans",
            parameters: vec![("coin", asset.into()), ("level", "vip0".into())],
        },
    };
    Ok(request)
}

fn number(value: &Value) -> Result<f64, InvalidData> {
    let n = match value {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.parse().ok(),
        _ => None,
    }
    .ok_or(InvalidData)?;
    if n.is_finite() {
        Ok(n)
    } else {
        Err(InvalidData)
    }
}

fn bitget(text: &str) -> Result<Value, InvalidData> {
    let value: Value = serde_json::from_str(text).map_err(|_| InvalidData)?;
    if value.get("code").and_then(Value::as_str) != Some("00000") {
        return Err(InvalidData);
    }
    Ok(value)
}

/// Parse Bitget growth history, preserving exchange and receipt times in milliseconds.
/// Duplicate timestamps with conflicting values are rejected.
pub fn growth(text: &str, available_ms: i64) -> Result<Vec<(i64, f64)>, InvalidData> {
    let body = bitget(text)?;
    let rows = body
        .get("data")
        .and_then(Value::as_array)
        .ok_or(InvalidData)?;
    let mut points = BTreeMap::new();
    for row in rows {
        let raw = number(row.get("ts").ok_or(InvalidData)?)?;
        if raw.fract() != 0.0 || raw < 0.0 || raw > 253_402_300_799_000.0 {
            return Err(InvalidData);
        }
        let timestamp = raw as i64;
        let value = number(row.get("growthRate").ok_or(InvalidData)?)?;
        if timestamp > available_ms {
            return Err(InvalidData);
        }
        if let Some(old) = points.insert(timestamp, value)
            && old != value
        {
            return Err(InvalidData);
        }
    }
    Ok(points.into_iter().collect())
}

/// Convert an exact-second growth record to the Calculus indicator input.
pub fn growth_observation(
    timestamp_ms: i64,
    available_ms: i64,
    value: f64,
) -> Result<GrowthObservation, InvalidData> {
    if timestamp_ms % 1000 != 0 || available_ms < timestamp_ms {
        return Err(InvalidData);
    }
    let available = available_ms.div_euclid(1000) + i64::from(available_ms.rem_euclid(1000) != 0);
    GrowthObservation::new(timestamp_ms.div_euclid(1000), available, value).map_err(|_| InvalidData)
}

/// A two-sided validated book with millisecond timestamps.
#[derive(Debug, Clone, PartialEq)]
pub struct Book {
    pub observed_ms: i64,
    pub available_ms: i64,
    pub bids: Vec<BookLevel>,
    pub asks: Vec<BookLevel>,
}

fn levels(value: &Value) -> Result<(Vec<BookLevel>, Vec<f64>), InvalidData> {
    let rows = value.as_array().ok_or(InvalidData)?;
    if rows.is_empty() || rows.len() > 50 {
        return Err(InvalidData);
    }
    let mut levels = Vec::new();
    let mut prices = Vec::new();
    for row in rows {
        let pair = row.as_array().ok_or(InvalidData)?;
        if pair.len() != 2 {
            return Err(InvalidData);
        }
        let price = number(&pair[0])?;
        let quantity = number(&pair[1])?;
        levels.push(BookLevel::new(price, quantity).map_err(|_| InvalidData)?);
        prices.push(price);
    }
    Ok((levels, prices))
}

/// Validate a Bybit book, including symbol, crossed prices, and receipt freshness.
pub fn book(text: &str, asset: &str, available_ms: i64) -> Result<Book, InvalidData> {
    if !matches!(asset, "BTC" | "ETH") {
        return Err(InvalidData);
    }
    let body: Value = serde_json::from_str(text).map_err(|_| InvalidData)?;
    let result = body.get("result").ok_or(InvalidData)?;
    if body.get("retCode").and_then(Value::as_i64) != Some(0)
        || result.get("s").and_then(Value::as_str) != Some(&format!("{asset}USDT"))
    {
        return Err(InvalidData);
    }
    let timestamp = number(result.get("ts").ok_or(InvalidData)?)?;
    if timestamp.fract() != 0.0 || timestamp < 0.0 || timestamp > 253_402_300_799_000.0 {
        return Err(InvalidData);
    }
    let observed_ms = timestamp as i64;
    let age = available_ms.checked_sub(observed_ms).ok_or(InvalidData)?;
    if !(0..=10_000).contains(&age) {
        return Err(InvalidData);
    }
    let (bids, bid_prices) = levels(result.get("b").ok_or(InvalidData)?)?;
    let (asks, ask_prices) = levels(result.get("a").ok_or(InvalidData)?)?;
    if bid_prices.iter().copied().fold(f64::NEG_INFINITY, f64::max)
        >= ask_prices.iter().copied().fold(f64::INFINITY, f64::min)
    {
        return Err(InvalidData);
    }
    Ok(Book {
        observed_ms,
        available_ms,
        bids,
        asks,
    })
}

/// Bitget's current lending quote, separate from the growth oscillator.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct LoanRate {
    pub observed_ms: i64,
    pub daily: f64,
    pub annual: f64,
}

/// Parse the current VIP0 loan rate.
pub fn loan_rate(text: &str) -> Result<LoanRate, InvalidData> {
    let body = bitget(text)?;
    let data = body.get("data").ok_or(InvalidData)?;
    let timestamp = number(body.get("requestTime").ok_or(InvalidData)?)?;
    let daily = number(data.get("dailyInterest").ok_or(InvalidData)?)?;
    let annual = number(data.get("annualInterest").ok_or(InvalidData)?)?;
    if timestamp.fract() != 0.0
        || !(0.0..=253_402_300_799_000.0).contains(&timestamp)
        || daily < 0.0
        || annual < 0.0
    {
        return Err(InvalidData);
    }
    Ok(LoanRate {
        observed_ms: timestamp as i64,
        daily,
        annual,
    })
}
