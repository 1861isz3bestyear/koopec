//! Normalize Deribit instrument definitions and book summaries into option contracts.
use serde_json::Value;
use std::{collections::HashMap, fmt};

const MAX_EXPIRY_MS: i64 = 253_402_300_799_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Side {
    Call,
    Put,
}

impl Side {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Call => "call",
            Self::Put => "put",
        }
    }
}

#[derive(Debug, PartialEq)]
pub struct Contract {
    pub instrument: String,
    pub side: Side,
    pub strike: f64,
    pub expiry_ms: i64,
    pub iv: f64,
    pub open_interest: f64,
    pub multiplier: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InvalidChain(&'static str);

impl fmt::Display for InvalidChain {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}

impl std::error::Error for InvalidChain {}

/// Decode the selected exchange result and reject unsuccessful JSON-RPC envelopes.
pub fn result(envelope: &Value) -> Result<&Value, InvalidChain> {
    if envelope.get("error").is_some() {
        return Err(InvalidChain("Deribit returned an error"));
    }
    envelope
        .get("result")
        .ok_or(InvalidChain("Deribit returned a missing result"))
}

fn rows(value: &Value) -> Result<&[Value], InvalidChain> {
    value
        .as_array()
        .map(Vec::as_slice)
        .ok_or(InvalidChain("Invalid Deribit response rows"))
}

fn name(row: &Value) -> Result<&str, InvalidChain> {
    row.get("instrument_name")
        .and_then(Value::as_str)
        .ok_or(InvalidChain("Invalid Deribit instrument name"))
}

fn indexed(rows: &[Value]) -> Result<HashMap<&str, &Value>, InvalidChain> {
    let mut result = HashMap::with_capacity(rows.len());
    for row in rows {
        if result.insert(name(row)?, row).is_some() {
            return Err(InvalidChain("Duplicate Deribit instrument"));
        }
    }
    Ok(result)
}

fn number(row: &Value, key: &str, allow_zero: bool) -> Result<f64, InvalidChain> {
    row.get(key)
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite() && (*value > 0.0 || allow_zero && *value == 0.0))
        .ok_or(InvalidChain("Invalid Deribit numeric field"))
}

pub fn spot(index: &Value) -> Result<f64, InvalidChain> {
    number(result(index)?, "index_price", false)
}

fn contract(
    instrument: &Value,
    quote: &Value,
    instrument_name: &str,
) -> Result<Contract, InvalidChain> {
    let side = match instrument.get("option_type").and_then(Value::as_str) {
        Some("call") => Side::Call,
        Some("put") => Side::Put,
        _ => return Err(InvalidChain("Unsupported Deribit contract")),
    };
    if instrument.get("kind").and_then(Value::as_str) != Some("option") {
        return Err(InvalidChain("Unsupported Deribit contract"));
    }
    let expiry_ms = instrument
        .get("expiration_timestamp")
        .and_then(Value::as_i64)
        .filter(|expiry| (1..=MAX_EXPIRY_MS).contains(expiry))
        .ok_or(InvalidChain("Invalid Deribit expiration timestamp"))?;
    let multiplier = number(instrument, "contract_size", false)?;
    let open_interest = number(quote, "open_interest", true)? / multiplier;
    let iv = number(quote, "mark_iv", false)? / 100.0;
    if !open_interest.is_finite() || iv <= 0.0 {
        return Err(InvalidChain("Invalid normalized Deribit quote"));
    }
    Ok(Contract {
        instrument: instrument_name.to_owned(),
        side,
        strike: number(instrument, "strike", false)?,
        expiry_ms,
        iv,
        open_interest,
        multiplier,
    })
}

/// Normalize all active definitions in wire order, including zero-interest contracts.
/// The caller applies its live or archive expiry policy against the exact receipt.
pub fn normalize_chain(
    instruments: &Value,
    quotes: &Value,
    asset: &str,
) -> Result<Vec<Contract>, InvalidChain> {
    if !matches!(asset, "BTC" | "ETH") {
        return Err(InvalidChain("Unexpected underlying currency"));
    }
    let instruments = rows(instruments)?;
    indexed(instruments)?;
    let quotes = indexed(rows(quotes)?)?;
    let mut chain = Vec::new();
    for instrument in instruments {
        if !instrument
            .get("is_active")
            .and_then(Value::as_bool)
            .ok_or(InvalidChain("Invalid Deribit active flag"))?
        {
            continue;
        }
        if instrument.get("base_currency").and_then(Value::as_str) != Some(asset) {
            return Err(InvalidChain("Unexpected underlying currency"));
        }
        let name = name(instrument)?;
        let quote = quotes
            .get(name)
            .ok_or(InvalidChain("Incomplete Deribit chain"))?;
        chain.push(contract(instrument, quote, name)?);
    }
    if chain.is_empty() {
        return Err(InvalidChain("Deribit returned an empty active chain"));
    }
    Ok(chain)
}
